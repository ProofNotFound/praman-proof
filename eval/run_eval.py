"""Evaluation (TRD §17): agent vs text-only baseline against hand labels.

Usage: uv run eval/run_eval.py [--labels eval/labels.csv] [--llm replay|offline|live] [--holdout]

Checks the labels (eval/check_labels.py), runs every labelled dev listing in both modes, aligns
predicted claims to labelled claims (same listing, normalised quote similarity ≥ 0.8), and writes
eval/results.md, eval/results.json (served by GET /api/eval) and eval_results rows. Dev and
holdout are reported separately, each with agreement, a confusion matrix per mode, false Backed
and model calls, time and cost per listing. Holdout listings run only with --holdout (once, for
the final numbers). Without eval/labels.csv it writes "Pending labels". `--labels
eval/labels_template.csv` is a dry run written to eval/results_template.* (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

LABELS = ROOT / "eval" / "labels.csv"
TEMPLATE = ROOT / "eval" / "labels_template.csv"
RESULTS_MD = ROOT / "eval" / "results.md"
RESULTS_JSON = ROOT / "eval" / "results.json"
MODES = ("agent", "baseline")
SPLITS = ("dev", "holdout")
NOT_FOUND = "Not found"
VERDICTS = ["Backed", "Partly backed", "Not backed", "Contradicted", "Needs review", "Not a claim"]
BACKING = {"Backed", "Partly backed"}


def similarity(a: str, b: str) -> float:
    """fuzz.ratio on normalised quotes; a quote contained in the other (≥ 40% of its length)
    counts as 80, so a label that joins two phrases still finds its claim."""
    from rapidfuzz import fuzz

    from praman.rules import normalise

    na, nb = normalise(a).strip(" .!"), normalise(b).strip(" .!")
    score = fuzz.ratio(na, nb)
    short, long_ = sorted((na, nb), key=len)
    if short and short in long_ and len(short) >= 0.4 * len(long_):
        score = max(score, 80.0)
    return float(score)


def align(label: dict, claims: list) -> tuple[object | None, float]:
    """Best predicted claim for one labelled claim, or None below 80."""
    best, best_key = None, (0.0, 0)
    for c in claims:
        if label["location"].strip() == "n/a" or c.derived_from:
            # Required-label rows match the derived label check with the same rule
            rules = set(label["rule_ids"].split(";"))
            if not (
                label["location"].strip() == "n/a" and c.derived_from and rules & set(c.rule_ids)
            ):
                continue
            score = 100.0
        else:
            score = similarity(label["claim_quote"], c.quote)
        key = (score, len(c.quote))
        if key > best_key:
            best, best_key = c, key
    return (best, best_key[0]) if best_key[0] >= 80 else (None, best_key[0])


def run_stats(ctx, seconds: float) -> dict:
    return {
        "model_calls": ctx.meter.calls,
        "cost_inr": round(ctx.meter.cost_inr(), 2),
        "seconds": round(seconds, 1),
        "failed": bool(ctx.failed),
    }


def listings_to_run(labels: list[dict], include_holdout: bool) -> tuple[list[str], list[str]]:
    """(listings to run, holdout listings held back). Holdout listings run only with --holdout:
    prompts are never tuned on them (PRD §9), so they're run once, for the final numbers."""
    order = list(dict.fromkeys(r["listing_id"] for r in labels))
    holdout = [
        lid
        for lid in order
        if any(r["listing_id"] == lid and r["split"] == "holdout" for r in labels)
    ]
    run = [lid for lid in order if include_holdout or lid not in holdout]
    return run, ([] if include_holdout else holdout)


def summarise(rows: list[dict], stats: dict[tuple[str, str], dict], lids: list[str]) -> dict:
    """Metrics for one split: agreement, confusion matrix, false Backed, cost/time/calls."""
    modes = {}
    for mode in MODES:
        matched = [r for r in rows if r[mode]["label"]]
        agree = [r for r in matched if r[mode]["label"] == r["expected"]]
        by_verdict = {
            v: {
                "expected": sum(1 for r in rows if r["expected"] == v),
                "predicted": sum(1 for r in matched if r[mode]["label"] == v),
                "agree": sum(1 for r in agree if r["expected"] == v),
            }
            for v in VERDICTS
        }
        confusion: dict[str, dict[str, int]] = {}
        for r in rows:
            got = r[mode]["label"] or NOT_FOUND
            confusion.setdefault(r["expected"], {})
            confusion[r["expected"]][got] = confusion[r["expected"]].get(got, 0) + 1
        per = [{"listing_id": lid, **stats[(lid, mode)]} for lid in lids]
        n = max(1, len(per))
        modes[mode] = {
            "n_labelled": len(rows),
            "matched": len(matched),
            "agree": len(agree),
            "agreement": round(len(agree) / len(matched), 3) if matched else None,
            "agreement_all": round(len(agree) / len(rows), 3) if rows else None,
            "false_backed": sum(
                1 for r in matched if r[mode]["label"] == "Backed" and r["expected"] != "Backed"
            ),
            "missed": len(rows) - len(matched),
            "model_calls": sum(p["model_calls"] for p in per),
            "cost_inr": round(sum(p["cost_inr"] for p in per), 2),
            "seconds": round(sum(p["seconds"] for p in per), 1),
            "per_listing_avg": {
                "model_calls": round(sum(p["model_calls"] for p in per) / n, 1),
                "cost_inr": round(sum(p["cost_inr"] for p in per) / n, 2),
                "seconds": round(sum(p["seconds"] for p in per) / n, 1),
            },
            "by_verdict": by_verdict,
            "confusion": confusion,
        }
    per_listing = [
        {"listing_id": lid, **{mode: stats[(lid, mode)] for mode in MODES}} for lid in lids
    ]
    only_agent = [
        {
            "listing_id": r["listing_id"],
            "claim_ref": r["claim_ref"],
            "quote": r["quote"],
            "label": r["agent"]["label"],
            "sources": [s for s in r["agent"]["sources"] if s in ("photo", "registry", "link")],
            "run_id": r["agent"]["run_id"],
        }
        for r in rows
        if r["agent"]["label"] in BACKING
        and r["baseline"]["label"] not in BACKING
        and set(r["agent"]["sources"]) & {"photo", "registry", "link"}
    ]
    disagreements = [
        {
            "listing_id": r["listing_id"],
            "claim_ref": r["claim_ref"],
            "quote": r["quote"],
            "expected": r["expected"],
            "agent": r["agent"]["label"],
            "baseline": r["baseline"]["label"],
            "agent_run_id": r["agent"]["run_id"],
            "baseline_run_id": r["baseline"]["run_id"],
        }
        for r in rows
        if r["agent"]["label"] != r["expected"] or r["baseline"]["label"] != r["expected"]
    ]
    return {
        "status": "done",
        "listings": lids,
        "modes": modes,
        "per_listing": per_listing,
        "proof_only_agent": only_agent,
        "disagreements": disagreements,
        "rows": rows,
    }


def pending(reason: str) -> dict:
    return {"status": "pending", "reason": reason, "generated_at": datetime.now(UTC).isoformat()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=None, help="default: eval/labels.csv")
    ap.add_argument("--llm", default="replay", choices=["live", "replay", "offline"])
    ap.add_argument(
        "--holdout",
        action="store_true",
        help="Also run the blind holdout listings. Do this once, for the final numbers.",
    )
    ap.add_argument("--out-dir", type=Path, default=ROOT / "eval")
    args = ap.parse_args(argv)
    os.environ["PRAMAN_LLM_MODE"] = args.llm

    from check_labels import check
    from hand_check import hand_checked

    labels_path = args.labels or LABELS
    using_template = labels_path.resolve() == TEMPLATE.resolve()
    # The template is a dry run: written next to the real results, never served as them
    stem = "results_template" if using_template else "results"
    out_md, out_json = args.out_dir / f"{stem}.md", args.out_dir / f"{stem}.json"
    if not labels_path.exists():
        result = pending("eval/labels.csv doesn't exist yet.")
        out_json.write_text(json.dumps(result, indent=1))
        out_md.write_text(to_markdown(result))
        print("Pending labels: eval/labels.csv doesn't exist yet. Wrote pending results.")
        return 0
    report = check(labels_path)
    if not report.ok:
        for e in report.errors:
            print(f"ERROR {e}")
        print("Fix the labels first (uv run eval/check_labels.py).")
        return 1

    from praman import db
    from praman.agent import run_listing
    from praman.tools.fetch import load_cached

    labels = report.rows
    run_ids, held_back = listings_to_run(labels, args.holdout)
    if held_back:
        print(f"Holdout listings not run (use --holdout once, at the end): {', '.join(held_back)}")
    # "T" keeps the date and time apart, so the anonymiser can't read them as a phone number
    eval_id = f"eval-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}"

    runs: dict[tuple[str, str], object] = {}
    stats: dict[tuple[str, str], dict] = {}
    for lid in run_ids:
        listing = load_cached(lid)
        for mode in MODES:
            t0 = time.monotonic()
            ctx = run_listing(listing, mode)
            runs[(lid, mode)] = ctx
            stats[(lid, mode)] = run_stats(ctx, time.monotonic() - t0)
            state = "FAILED" if ctx.failed else "ok"
            print(f"{lid}.{mode}: {state}, {ctx.meter.calls} model calls, {ctx.counts()}")

    rows = []
    for lab in labels:
        if lab["listing_id"] not in run_ids:
            continue
        row = {
            "listing_id": lab["listing_id"],
            "split": lab["split"],
            "claim_ref": lab["claim_ref"],
            "quote": lab["claim_quote"],
            "expected": lab["expected_verdict"],
        }
        for mode in MODES:
            ctx = runs[(lab["listing_id"], mode)]
            claim, score = align(lab, ctx.claims)  # type: ignore[attr-defined]
            v = ctx.verdicts.get(claim.id) if claim else None  # type: ignore[attr-defined]
            sources = []
            if v:
                ev = {e.id: e for e in ctx.evidence}  # type: ignore[attr-defined]
                sources = sorted({ev[i].source for i in v.evidence_ids if i in ev})
            row[mode] = {
                "claim_id": claim.id if claim else None,
                "quote": claim.quote if claim else None,
                "score": round(score, 1),
                "label": v.label.value if v else None,
                "sources": sources,
                "run_id": ctx.run_id,  # type: ignore[attr-defined]
            }
            db.execute(
                "INSERT INTO eval_results (eval_id, listing_id, claim_ref, mode, predicted, expected, "
                "match) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    eval_id,
                    lab["listing_id"],
                    lab["claim_ref"],
                    mode,
                    row[mode]["label"],
                    lab["expected_verdict"],
                    int(row[mode]["label"] == lab["expected_verdict"]),
                ),
            )
        rows.append(row)

    splits: dict[str, dict] = {}
    for split in SPLITS:
        lab_rows = [r for r in labels if r["split"] == split]
        if not lab_rows:
            continue
        lids = list(dict.fromkeys(r["listing_id"] for r in lab_rows))
        if not all(lid in run_ids for lid in lids):
            splits[split] = {
                "status": "not_run",
                "listings": lids,
                "n_labelled": len(lab_rows),
            }
            continue
        splits[split] = summarise([r for r in rows if r["split"] == split], stats, lids)
    for split, lab_rows in ((sp, [r for r in labels if r["split"] == sp]) for sp in splits):
        splits[split]["hand_checked"] = sum(hand_checked(r.get("labeller", "")) for r in lab_rows)

    result = {
        "status": "done",
        "eval_id": eval_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "llm_mode": args.llm,
        "labels_file": (
            str(labels_path.resolve().relative_to(ROOT))
            if labels_path.resolve().is_relative_to(ROOT)
            else labels_path.name
        ),
        "labels_note": (
            "Template labels only (a handful of claims from the kickoff pack): a dry run, not "
            "the evaluation."
            if using_template
            else None
        ),
        "splits": splits,
    }
    from praman.anonymise import mask

    result = mask(result)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    out_md.write_text(to_markdown(result))
    print(f"\nWrote {out_md} and {out_json}")
    for split, s in splits.items():
        if s.get("status") == "not_run":
            print(f"  {split}: not run ({len(s['listings'])} listings)")
            continue
        for mode in MODES:
            m = s["modes"][mode]
            print(
                f"  {split} {mode:8}: agreement {m['agree']}/{m['matched']} matched "
                f"({m['missed']} missed), false Backed {m['false_backed']}"
            )
    return 0


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def to_markdown(r: dict) -> str:
    if r.get("status") != "done":
        return (
            "# Evaluation: agent vs text-only baseline\n\n"
            "**Pending labels.** "
            + r.get("reason", "")
            + " Write the claim labels (`eval/labels_template.csv` shows the columns), check them "
            "with `uv run eval/check_labels.py`, then run `uv run eval/run_eval.py`.\n"
        )
    out = [
        "# Evaluation: agent vs text-only baseline",
        "",
        f"Run {r['eval_id']} on {r['generated_at'][:16].replace('T', ' ')} UTC, model answers: "
        f"{r['llm_mode']}. Labels: `{r['labels_file']}`.",
        "",
    ]
    if r.get("labels_note"):
        out += [f"> **{r['labels_note']}**", ""]
    checked = [
        f"{split} {s['hand_checked']} of {s.get('n_labelled') or s['modes']['agent']['n_labelled']}"
        for split, s in r["splits"].items()
        if "hand_checked" in s
    ]
    if checked:
        out += [f"Labels checked by a person (`eval/hand_check.py`): {', '.join(checked)}.", ""]
    for split, s in r["splits"].items():
        if s.get("status") == "not_run":
            out += [
                f"## {split.capitalize()} set: not run yet",
                "",
                f"{len(s['listings'])} listings, {s['n_labelled']} labelled claims. Holdout "
                "listings run once, at the end: `uv run eval/run_eval.py --holdout`.",
                "",
            ]
            continue
        a, b = s["modes"]["agent"], s["modes"]["baseline"]
        pa, pb = a["per_listing_avg"], b["per_listing_avg"]
        out += [
            f"## {split.capitalize()} set ({len(s['listings'])} listings, {a['n_labelled']} labelled claims)",
            "",
            "| Metric | Agent | Text-only |",
            "|---|---|---|",
            f"| Verdict agreement (matched claims) | {a['agree']}/{a['matched']} ({_pct(a['agreement'])}) "
            f"| {b['agree']}/{b['matched']} ({_pct(b['agreement'])}) |",
            f"| Agreement over all labelled claims | {_pct(a['agreement_all'])} | {_pct(b['agreement_all'])} |",
            f"| False Backed (target 0) | {a['false_backed']} | {b['false_backed']} |",
            f"| Labelled claims not found | {a['missed']} | {b['missed']} |",
            f"| Model calls (per listing) | {a['model_calls']} ({pa['model_calls']}) | {b['model_calls']} ({pb['model_calls']}) |",
            f"| Estimated cost ₹ (per listing) | {a['cost_inr']:.2f} ({pa['cost_inr']:.2f}) | {b['cost_inr']:.2f} ({pb['cost_inr']:.2f}) |",
            f"| Time s (per listing; replayed runs are near 0) | {a['seconds']} ({pa['seconds']}) | {b['seconds']} ({pb['seconds']}) |",
            "",
        ]
        for mode, name in (("agent", "Agent"), ("baseline", "Text-only")):
            conf = s["modes"][mode]["confusion"]
            cols = [v for v in VERDICTS + [NOT_FOUND] if any(v in row for row in conf.values())]
            out += [
                f"**Confusion matrix · {name}** (rows: our label; columns: {name.lower()} verdict)",
                "",
                "| Label \\ verdict | " + " | ".join(cols) + " |",
                "|---" * (len(cols) + 1) + "|",
            ]
            for exp in [v for v in VERDICTS if v in conf]:
                out.append(
                    f"| {exp} | " + " | ".join(str(conf[exp].get(c, 0) or "·") for c in cols) + " |"
                )
            out.append("")
        out += [
            "**Per listing**",
            "",
            "| Listing | Agent calls | Agent s | Agent ₹ | Text-only calls | Text-only s | Text-only ₹ |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in s["per_listing"]:
            ag, bl = p["agent"], p["baseline"]
            out.append(
                f"| {p['listing_id']} | {ag['model_calls']} | {ag['seconds']} | {ag['cost_inr']:.2f} "
                f"| {bl['model_calls']} | {bl['seconds']} | {bl['cost_inr']:.2f} |"
            )
        out += ["", f"**Proof only the agent found:** {len(s['proof_only_agent'])}", ""]
        for p in s["proof_only_agent"]:
            out.append(
                f"- {p['claim_ref']} “{p['quote']}”: {p['label']} via {', '.join(p['sources'])} "
                f"(run `{p['run_id']}`)"
            )
        out += ["", "**Claims where a mode differs from the label**", ""]
        if not s["disagreements"]:
            out.append("None.")
        else:
            out += ["| Claim | Label | Agent | Text-only | Runs |", "|---|---|---|---|---|"]
            for d in s["disagreements"]:
                out.append(
                    f"| {d['claim_ref']} “{d['quote']}” | {d['expected']} | {d['agent'] or 'not found'} "
                    f"| {d['baseline'] or 'not found'} | `{d['agent_run_id']}`, `{d['baseline_run_id']}` |"
                )
        out.append("")
    if "holdout" not in r["splits"]:
        out += ["## Holdout set", "", "No holdout labels yet.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
