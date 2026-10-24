from helpers import claim, listing, photo_print

from praman import llm
from praman.models import CheckConsistencyOut
from praman.models import Conflict as LLMConflict
from praman.tools.consistency import fact_lines, model_conflicts, rule_conflicts

BAGS = listing(
    title="Compostable Garbage Bags",
    body="Made from cornstarch\n100% compostable garbage bags\nBreaks down naturally in the environment",
    tags=["garbage_bags"],
)


def test_r07_zero_plastic_claim_conflicts_with_compostable_plastic():
    c1 = claim("100% compostable garbage bags", rule_ids=["R02", "R07", "R08"])
    c2 = claim("100% ecofriendly, 0% plastic.", id_="C2", rule_ids=["R02"], location="photo:7")
    out = rule_conflicts(c2, [c1, c2], BAGS, None, {"text"})
    assert len(out) == 1
    assert out[0].rule_id == "R07" and out[0].other_claim_id == "C1"
    # The anchor claim itself isn't contradicted by it
    assert rule_conflicts(c1, [c1, c2], BAGS, None, {"text"}) == []


def test_r08_breaks_down_naturally_conflicts_with_industrial_label():
    c1 = claim("100% compostable garbage bags", rule_ids=["R02", "R07", "R08"])
    c2 = claim("Breaks down naturally in the environment", id_="C2", rule_ids=["R02"])
    out = rule_conflicts(c2, [c1, c2], BAGS, None, {"text"})
    assert [o.rule_id for o in out] == ["R08"]


def test_r09_virgin_pe_on_the_pack_contradicts_biodegradable():
    lst = listing(
        title="Oxo-Biodegradable Disposable Bags",
        body="Oxo-biodegradable bags for eco-friendly disposal.",
    )
    c = claim("Oxo-biodegradable bags", rule_ids=["R02", "R09"])
    pp = photo_print((3, "composition", "Carrier Resin- PE Virgin Grade, Additive(%)- 5"))
    # The claim's own words ("oxo") don't contradict it; text alone has no fact
    assert rule_conflicts(c, [c], lst, pp, {"text"}) == []
    out = rule_conflicts(c, [c], lst, pp, {"text", "photos"})
    assert len(out) == 1 and out[0].photo_index == 3 and out[0].rule_id == "R09"
    assert out[0].box_2d == [100, 100, 200, 400]


def test_plastic_free_conflicts_with_nylon_in_a_clause():
    lst = listing(
        title="Bamboo Toothbrush",
        body="Our compostable bamboo toothbrush has a biodegradable bamboo handle, BPA-free nylon bristles and a coating.",
    )
    pf = claim("plastic-free alternative", id_="C2", location="photo:5")
    handle = claim("biodegradable bamboo handle", id_="C1")
    facts = [t for _, t, _, _ in fact_lines(lst, None, [pf, handle])]
    assert any("nylon" in f for f in facts)
    assert not any("biodegradable bamboo handle" in f for f in facts)
    out = rule_conflicts(pf, [pf, handle], lst, None, {"text"})
    assert len(out) == 1 and "nylon" in out[0].quote
    # Not before the text has been searched
    assert rule_conflicts(pf, [pf, handle], lst, None, set()) == []


def _model_answer(monkeypatch, explanation):
    out = CheckConsistencyOut(
        conflicts=[
            LLMConflict(
                claim_id="C1",
                conflicting_quote="COMPOSITION: Glassine paper",
                where="photo:3",
                explanation=explanation,
            )
        ]
    )
    res = llm.LLMResult(data=out, tokens_in=1, tokens_out=1, cached=False, model="m", ms=1, key="k")
    monkeypatch.setattr(llm, "call", lambda *a, **k: res)


def test_a_model_conflict_that_rests_on_general_knowledge_is_dropped(monkeypatch):
    lst = listing(title="Seat cover", body="Made from biodegradable paper substances")
    c = claim("biodegradable paper substances")
    pp = photo_print((3, "composition", "COMPOSITION: Glassine paper"))
    _model_answer(monkeypatch, "Glassine paper is typically coated and not biodegradable.")
    assert model_conflicts(lst, pp, [c], [], None) == []
    # The same conflict, worded from the listing's own facts, is kept
    _model_answer(monkeypatch, "The photo prints glassine paper, not the stated material.")
    kept = model_conflicts(lst, pp, [c], [], None)
    assert len(kept) == 1 and kept[0].photo_index == 3
