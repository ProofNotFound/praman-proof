"""Hand-check labels one claim at a time (a person decides; this only records it).

Usage: uv run eval/hand_check.py --name Savya [--split holdout] [--n 20] [--labels eval/labels.csv]

For each label not yet hand-checked it shows the claim, where it sits on the cached page, the
evidence note and the current verdict. Keys: Enter keeps the verdict, 1-6 change it, s skips,
q quits. Each decision is written straight back to the labels file, with the labeller set to
"<name> (hand-checked)", so stopping half-way loses nothing. Runs no agent and calls no model.
The evaluation reports how many labels a person checked.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval" / "labels.csv"
LISTINGS = ROOT / "data" / "cache" / "listings"
VERDICTS = ["Backed", "Partly backed", "Not backed", "Contradicted", "Needs review", "Not a claim"]
MARK = "(hand-checked)"


def hand_checked(labeller: str) -> bool:
    return MARK in (labeller or "")


def to_check(rows: list[dict], split: str, n: int) -> list[int]:
    """Row indexes still to check: holdout first (it has no human labels yet), then dev."""
    order = {"holdout": 0, "dev": 1}
    idx = [
        i
        for i, r in enumerate(rows)
        if not hand_checked(r.get("labeller", "")) and split in ("all", r["split"])
    ]
    idx.sort(key=lambda i: (order.get(rows[i]["split"], 9), i))
    return idx[:n]


def decide(row: dict, name: str, verdict: str | None, note: str = "") -> dict:
    """The row after a person's decision: a new verdict (or the same), signed by them."""
    out = dict(row)
    if verdict and verdict != row["expected_verdict"]:
        was = row["expected_verdict"]
        out["expected_verdict"] = verdict
        change = f"Hand-check: {was} → {verdict}" + (f" ({note})" if note else "")
        out["notes"] = f"{row.get('notes', '')} {change}".strip()
    out["labeller"] = f"{name.strip()} {MARK}"
    return out


def source_line(listing_id: str, quote: str) -> str:
    """The line of the cached page that holds the quote, so the checker sees it in context."""
    path = LISTINGS / f"{listing_id}.json"
    if not path.exists():
        return "(page not cached)"
    doc = json.loads(path.read_text())
    lines = [doc.get("title", ""), *doc.get("body_text", "").splitlines(), *doc.get("tags", [])]
    q = quote.lower().strip(" .!")
    for ln in lines:
        if q and q in ln.lower():
            return ln.strip()
    return "(not in the page text; it may be on a photo)"


def write(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Write the whole file to a temp file, then swap it in."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True, help="Your name, written on each checked row")
    ap.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    ap.add_argument("--n", type=int, default=20, help="How many rows this session")
    ap.add_argument("--labels", type=Path, default=LABELS)
    args = ap.parse_args(argv)

    with args.labels.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for col in ("labeller", "notes"):
        if col not in fields:
            fields.append(col)

    todo = to_check(rows, args.split, args.n)
    if not todo:
        print("Nothing left to check.")
        return 0
    keys = "  ".join(f"{i + 1} {v}" for i, v in enumerate(VERDICTS))
    done = 0
    for k, i in enumerate(todo, 1):
        r = rows[i]
        print(f"\n[{k}/{len(todo)}] {r['claim_ref']} · {r['split']} · {r['location']}")
        print(f"  Claim:    “{r['claim_quote']}”")
        print(f"  On page:  {source_line(r['listing_id'], r['claim_quote'])}")
        print(f"  Evidence: {r.get('evidence_detail') or '(none noted)'}")
        print(f"  Label:    {r['expected_verdict']}   (by {r.get('labeller') or 'unknown'})")
        print(f"  Enter keep · {keys} · s skip · q quit")
        ans = input("  > ").strip().lower()
        if ans == "q":
            break
        if ans == "s":
            continue
        verdict = None
        note = ""
        if ans.isdigit() and 1 <= int(ans) <= len(VERDICTS):
            verdict = VERDICTS[int(ans) - 1]
            if verdict != r["expected_verdict"]:
                note = input("  Why (optional): ").strip()
        elif ans:
            print("  Not a choice; skipped.")
            continue
        rows[i] = decide(r, args.name, verdict, note)
        write(args.labels, fields, rows)
        done += 1
    total = sum(hand_checked(r.get("labeller", "")) for r in rows)
    print(f"\nChecked {done} this session; {total} of {len(rows)} labels are hand-checked.")
    print("Next: uv run eval/check_labels.py, then uv run eval/run_eval.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
