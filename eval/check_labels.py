"""Check eval/labels.csv before an evaluation (W5). Runs no agent and calls no model.

Usage: uv run eval/check_labels.py [--labels eval/labels.csv]

Checks the columns, that every verdict is spelt exactly as Praman writes it, that every listing
id is a seed listing, that each row has a split (dev or holdout), and the claim fields (type,
scope, location, rule IDs, covers_claim). Prints one line per problem with its row number, then a
summary per split. Exit code 0 when the file is clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "eval" / "labels.csv"
SEED = ROOT / "data" / "listings_seed.csv"
RULES = ROOT / "data" / "rules.json"

COLUMNS = [
    "listing_id",
    "split",
    "claim_ref",
    "claim_quote",
    "claim_type",
    "scope",
    "location",
    "rule_ids",
    "expected_verdict",
]
OPTIONAL_COLUMNS = ["evidence_source", "evidence_detail", "covers_claim", "labeller", "notes"]
VERDICTS = ["Backed", "Partly backed", "Not backed", "Contradicted", "Needs review", "Not a claim"]
SPLITS = ["dev", "holdout"]
CLAIM_TYPES = ["vague", "specific", "comparative", "future"]
SCOPES = ["product", "part", "packaging", "process", "disposal", "delivery", "brand", "unclear"]
COVERS = ["yes", "partly", "no", "contradicts", "n/a", ""]
LOCATION_RE = re.compile(r"^(title|description|tag|n/a|photo:\d+)$")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_split(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.rows:
            s = out.setdefault(r.get("split", "").strip() or "?", {"listings": 0, "claims": 0})
            s["claims"] += 1
        for split in out:
            out[split]["listings"] = len(
                {r["listing_id"] for r in self.rows if (r.get("split") or "?").strip() == split}
            )
        return out


def _suggest(value: str, choices: list[str]) -> str:
    near = difflib.get_close_matches(value, choices, n=1, cutoff=0.6)
    if not near:
        near = [c for c in choices if c.lower() == value.lower()]
    return f' (did you mean "{near[0]}"?)' if near else f" (one of: {', '.join(choices)})"


def check(path: Path, seed_path: Path = SEED, rules_path: Path = RULES) -> Report:
    rep = Report()
    if not path.exists():
        rep.errors.append(f"{path}: file not found (copy eval/labels_template.csv and fill it in)")
        return rep
    seed_ids = {r["id"] for r in csv.DictReader(seed_path.open())}
    rule_ids = {r["id"] for r in json.loads(rules_path.read_text())["rules"]}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in COLUMNS if c not in header]
        if missing:
            rep.errors.append(f"header: missing column(s) {', '.join(missing)}")
        unknown = [c for c in header if c and c not in COLUMNS + OPTIONAL_COLUMNS]
        if unknown:
            rep.errors.append(f"header: unknown column(s) {', '.join(unknown)}")
        if missing:
            return rep
        seen_refs: dict[str, int] = {}
        listing_split: dict[str, tuple[str, int]] = {}
        for n, raw in enumerate(reader, start=2):  # row 1 is the header
            row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
            if not any(row.values()):
                continue
            rep.rows.append(row)

            def err(msg: str, n: int = n) -> None:
                rep.errors.append(f"row {n}: {msg}")

            lid = row["listing_id"]
            if lid not in seed_ids:
                err(f'listing_id "{lid}" isn\'t in data/listings_seed.csv')
            split = row["split"]
            if not split:
                err("split is empty (dev or holdout)")
            elif split not in SPLITS:
                err(f'split "{split}" is not allowed' + _suggest(split, SPLITS))
            elif lid in listing_split and listing_split[lid][0] != split:
                err(
                    f'listing {lid} is "{split}" here but "{listing_split[lid][0]}" in row '
                    f"{listing_split[lid][1]}; a listing belongs to one split"
                )
            else:
                listing_split.setdefault(lid, (split, n))
            ref = row["claim_ref"]
            if not ref:
                err("claim_ref is empty")
            elif ref in seen_refs:
                err(f'claim_ref "{ref}" repeats row {seen_refs[ref]}')
            else:
                seen_refs[ref] = n
            if not row["claim_quote"]:
                err("claim_quote is empty")
            verdict = row["expected_verdict"]
            if verdict not in VERDICTS:
                err(f'expected_verdict "{verdict}" is not a verdict' + _suggest(verdict, VERDICTS))
            if row["claim_type"] not in CLAIM_TYPES:
                err(f'claim_type "{row["claim_type"]}"' + _suggest(row["claim_type"], CLAIM_TYPES))
            if row["scope"] not in SCOPES:
                err(f'scope "{row["scope"]}"' + _suggest(row["scope"], SCOPES))
            if not LOCATION_RE.match(row["location"]):
                err(f'location "{row["location"]}" (title, description, tag, photo:N or n/a)')
            rules = [r.strip() for r in row["rule_ids"].split(";") if r.strip()]
            bad_rules = [r for r in rules if r not in rule_ids]
            if bad_rules:
                err(f"unknown rule ID(s) {', '.join(bad_rules)}")
            if verdict != "Not a claim" and not rules:
                err("rule_ids is empty (every claim but Not a claim cites a rule)")
            covers = row.get("covers_claim", "")
            if covers not in COVERS:
                err(f'covers_claim "{covers}"' + _suggest(covers, COVERS[:-1]))
    if not rep.rows and not rep.errors:
        rep.errors.append(f"{path}: no label rows")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=LABELS)
    args = ap.parse_args(argv)
    rep = check(args.labels)
    for e in rep.errors:
        print(f"ERROR {e}")
    for split, s in sorted(rep.by_split().items()):
        print(f"{split}: {s['listings']} listings, {s['claims']} labelled claims")
    print("OK: labels are valid." if rep.ok else f"{len(rep.errors)} problem(s) found.")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
