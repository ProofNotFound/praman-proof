"""Evaluation alignment (TRD §17 step 3)."""

import importlib.util
import json
import sys

from helpers import claim

from praman.config import ROOT

spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def _label(quote, location="description", rules="R02"):
    return {"claim_quote": quote, "location": location, "rule_ids": rules}


def test_close_quotes_align():
    c = [claim("100% ecofriendly, 0% plastic.", id_="C5"), claim("Leak proof", id_="C3")]
    best, score = run_eval.align(_label("100% ecofriendly, 0% plastic"), c)
    assert best.id == "C5" and score >= 80


def test_label_joining_two_phrases_finds_the_longer_part():
    c = [claim("Oxo-biodegradable bags", id_="C2"), claim("eco-friendly disposal", id_="C3")]
    best, _ = run_eval.align(_label("Oxo-biodegradable bags for eco-friendly disposal"), c)
    assert best.id == "C2"


def test_required_label_rows_match_derived_label_checks():
    lab = claim(
        "Required label: compostable only under industrial composting",
        id_="C7",
        rule_ids=["R08"],
        location="n/a",
    )
    lab.derived_from = "C1"
    c = [claim("100% compostable garbage bags", id_="C1", rule_ids=["R02", "R07", "R08"]), lab]
    best, _ = run_eval.align(
        _label("compostable only under industrial composting (required label)", "n/a", "R08"), c
    )
    assert best.id == "C7"


def test_unrelated_quotes_do_not_align():
    best, score = run_eval.align(_label("Zero waste oral care"), [claim("Leak proof")])
    assert best is None and score < 80


# ---------------------------------------------------------------------------
# W5: label checker, splits, holdout, metrics

check_spec = importlib.util.spec_from_file_location(
    "check_labels", ROOT / "eval" / "check_labels.py"
)
check_labels = importlib.util.module_from_spec(check_spec)
sys.modules["check_labels"] = check_labels  # dataclasses look their module up by name
check_spec.loader.exec_module(check_labels)

HEADER = (
    "listing_id,split,claim_ref,claim_quote,claim_type,scope,location,rule_ids,"
    "evidence_source,evidence_detail,covers_claim,expected_verdict,labeller,notes\n"
)


def _csv(tmp_path, body, header=HEADER, name="labels.csv"):
    p = tmp_path / name
    p.write_text(header + body)
    return p


def test_template_labels_are_valid():
    rep = check_labels.check(ROOT / "eval" / "labels_template.csv")
    assert rep.ok, rep.errors
    assert rep.by_split() == {"dev": {"listings": 3, "claims": 5}}


def test_label_checker_names_each_problem_with_its_row(tmp_path):
    p = _csv(
        tmp_path,
        "L14,dev,L14-C1,100% compostable,specific,product,description,R02;R07,photo,x,yes,Not Backed,S,\n"
        "L99,dev,L99-C1,eco,vague,product,description,R01,,,,Backed,S,\n"
        "L06,,L06-C1,eco,vague,product,description,R01,,,,Backed,S,\n"
        "L08,test,L08-C1,eco,vague,product,somewhere,R42,,,,Backed,S,\n"
        "L14,holdout,L14-C1,again,vague,product,title,R01,,,maybe,Backed,S,\n",
    )
    rep = check_labels.check(p)
    text = "\n".join(rep.errors)
    assert (
        'row 2: expected_verdict "Not Backed" is not a verdict (did you mean "Not backed"?)' in text
    )
    assert 'row 3: listing_id "L99" isn\'t in data/listings_seed.csv' in text
    assert "row 4: split is empty" in text
    assert 'row 5: split "test" is not allowed' in text
    assert 'row 5: location "somewhere"' in text and "row 5: unknown rule ID(s) R42" in text
    assert 'row 6: listing L14 is "holdout" here but "dev" in row 2' in text
    assert 'row 6: claim_ref "L14-C1" repeats row 2' in text
    assert 'row 6: covers_claim "maybe"' in text
    assert check_labels.main(["--labels", str(p)]) == 1


def test_label_checker_needs_the_columns(tmp_path):
    p = _csv(
        tmp_path,
        "L14,L14-C1,x,Backed\n",
        header="listing_id,claim_ref,claim_quote,expected_verdict\n",
    )
    rep = check_labels.check(p)
    assert rep.errors and rep.errors[0].startswith("header: missing column(s) split")
    assert not check_labels.check(tmp_path / "nope.csv").ok


def test_holdout_listings_are_never_run_by_default():
    labels = [
        {"listing_id": "L14", "split": "dev"},
        {"listing_id": "L06", "split": "holdout"},
        {"listing_id": "L14", "split": "dev"},
    ]
    assert run_eval.listings_to_run(labels, include_holdout=False) == (["L14"], ["L06"])
    assert run_eval.listings_to_run(labels, include_holdout=True) == (["L14", "L06"], [])


def _row(lid, exp, agent, base, sources=("photo",)):
    side = lambda label: {"label": label, "sources": list(sources), "run_id": f"{lid}-x"}  # noqa: E731
    return {
        "listing_id": lid,
        "split": "dev",
        "claim_ref": f"{lid}-{exp}",
        "quote": "q",
        "expected": exp,
        "agent": side(agent),
        "baseline": side(base),
    }


def test_summary_has_confusion_false_backed_and_per_listing_costs():
    rows = [
        _row("L1", "Backed", "Backed", "Not backed"),
        _row("L1", "Not backed", "Backed", None),  # a false Backed for the agent
        _row("L2", "Contradicted", "Contradicted", "Not backed"),
    ]
    stats = {
        ("L1", "agent"): {"model_calls": 6, "cost_inr": 1.0, "seconds": 2.0, "failed": False},
        ("L1", "baseline"): {"model_calls": 1, "cost_inr": 0.2, "seconds": 0.5, "failed": False},
        ("L2", "agent"): {"model_calls": 4, "cost_inr": 0.6, "seconds": 1.0, "failed": False},
        ("L2", "baseline"): {"model_calls": 1, "cost_inr": 0.2, "seconds": 0.5, "failed": False},
    }
    s = run_eval.summarise(rows, stats, ["L1", "L2"])
    a, b = s["modes"]["agent"], s["modes"]["baseline"]
    assert a["false_backed"] == 1 and b["false_backed"] == 0
    assert a["confusion"]["Not backed"] == {"Backed": 1}
    assert b["confusion"]["Not backed"] == {"Not found": 1}
    assert a["agree"] == 2 and b["missed"] == 1
    assert a["per_listing_avg"] == {"model_calls": 5.0, "cost_inr": 0.8, "seconds": 1.5}
    assert [p["listing_id"] for p in s["per_listing"]] == ["L1", "L2"]
    assert s["proof_only_agent"][0]["claim_ref"] == "L1-Backed"


def test_eval_runs_dev_only_and_reports_holdout_as_not_run(tmp_path, monkeypatch):
    import praman.agent

    ran = []
    real = praman.agent.run_listing

    def spy(listing, mode="agent", *a, **k):
        ran.append(listing.id)
        return real(listing, mode, *a, **k)

    monkeypatch.setattr(praman.agent, "run_listing", spy)
    labels = _csv(
        tmp_path,
        "L21,dev,L21-C1,Building Blocks of Sustainability,vague,brand,title,R11,none,x,n/a,Not a claim,S,\n"
        "L14,holdout,L14-C1,100% compostable garbage bags,specific,product,description,R02;R07;R08,,,yes,Backed,S,\n",
    )
    assert (
        run_eval.main(["--labels", str(labels), "--llm", "offline", "--out-dir", str(tmp_path)])
        == 0
    )
    assert set(ran) == {"L21"}  # the holdout listing never ran
    res = json.loads((tmp_path / "results.json").read_text())
    assert res["splits"]["holdout"] == {
        "status": "not_run",
        "listings": ["L14"],
        "n_labelled": 1,
        "hand_checked": 0,
    }
    dev = res["splits"]["dev"]["modes"]["agent"]
    assert dev["agree"] == 1 and dev["false_backed"] == 0
    assert "not run yet" in (tmp_path / "results.md").read_text()


def test_without_labels_the_evaluation_is_pending(tmp_path):
    out = run_eval.main(["--labels", str(tmp_path / "labels.csv"), "--out-dir", str(tmp_path)])
    assert out == 0
    assert json.loads((tmp_path / "results.json").read_text())["status"] == "pending"
    assert "Pending labels" in (tmp_path / "results.md").read_text()


def _hand_check():
    spec = importlib.util.spec_from_file_location("hand_check", ROOT / "eval" / "hand_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hand_check_signs_rows_keeps_history_and_writes_back(tmp_path, monkeypatch):
    hc = _hand_check()
    src = (ROOT / "eval" / "labels.csv").read_text()
    path = tmp_path / "labels.csv"
    path.write_text(src)
    import csv

    rows = list(csv.DictReader(path.open()))
    todo = hc.to_check(rows, "all", 3)
    assert all(rows[i]["split"] == "holdout" for i in todo)  # holdout first: no human labels yet
    first = rows[todo[0]]
    new = "Needs review" if first["expected_verdict"] != "Needs review" else "Not backed"

    answers = iter(["5" if new == "Needs review" else "3", "photo unreadable", "", "q"])
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))
    assert hc.main(["--name", "Asha", "--labels", str(path), "--n", "3"]) == 0

    after = list(csv.DictReader(path.open()))
    assert len(after) == len(rows) and list(after[0]) == list(rows[0])
    a, b = after[todo[0]], after[todo[1]]
    assert a["expected_verdict"] == new and a["labeller"] == "Asha (hand-checked)"
    assert f"Hand-check: {first['expected_verdict']} → {new} (photo unreadable)" in a["notes"]
    assert b["expected_verdict"] == rows[todo[1]]["expected_verdict"] and hc.hand_checked(
        b["labeller"]
    )
    assert not hc.hand_checked(after[todo[2]]["labeller"])  # quit before the third
    assert hc.to_check(after, "all", 1000) == [
        i for i in hc.to_check(rows, "all", 1000) if i not in todo[:2]
    ]
