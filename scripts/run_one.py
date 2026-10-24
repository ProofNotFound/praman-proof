"""Run one listing and print claims, rules, every step and the verdicts.

Usage: uv run scripts/run_one.py L14 [--mode agent|baseline] [--llm live|replay|offline] [--raw]
       uv run scripts/run_one.py https://<store>/products/<handle> --llm live
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

COLOURS = {
    "Backed": "\033[32m",
    "Partly backed": "\033[33m",
    "Not backed": "\033[90m",
    "Contradicted": "\033[31m",
    "Needs review": "\033[34m",
    "Not a claim": "\033[37m",
}
RESET = "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="Listing ID (e.g. L14) or a Shopify product URL")
    ap.add_argument("--mode", default="agent", choices=["agent", "baseline"])
    ap.add_argument("--llm", choices=["live", "replay", "offline"], help="Override PRAMAN_LLM_MODE")
    ap.add_argument("--raw", action="store_true", help="Show brand names (no anonymising)")
    ap.add_argument("--quiet", action="store_true", help="Only print verdicts")
    args = ap.parse_args()
    if args.llm:
        os.environ["PRAMAN_LLM_MODE"] = args.llm
    if args.raw:
        os.environ["PRAMAN_ANONYMISE"] = "0"
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    from praman.agent import run_listing
    from praman.config import get_settings
    from praman.tools.fetch import fetch_listing

    s = get_settings()
    if args.target.startswith("http"):
        listing = fetch_listing(url=args.target)
    else:
        listing = fetch_listing(listing_id=args.target)

    def show(event: dict) -> None:
        if args.quiet:
            return
        t, d = event["type"], event["data"]
        stamp = f"{event['t_ms'] / 1000:6.1f}s"
        if t == "run_started":
            print(f"{stamp} run {d['run_id']} · {d['mode']} · llm {d['llm_mode']}")
        elif t == "listing":
            print(f"{stamp} listing {d['id']}: {d['title']} ({len(d['photos'])} photos)")
        elif t == "claims":
            print(f"{stamp} claims:")
            for c in d["claims"]:
                flag = "" if c["is_claim"] else f"  [not a claim: {c.get('not_claim_reason')}]"
                print(
                    f"         {c['id']} [{c['type']}/{c['scope']}/{c['location']}] "
                    f'"{c["quote"]}" → {", ".join(c["rule_ids"])}{flag}'
                )
        elif t == "step":
            tool = d["tool"] or "-"
            line = f"{stamp} #{d['n']:<3}{d['phase'].upper():8}{(d['claim_id'] or ''):4} {tool:18}"
            wrapped = textwrap.fill(d["summary"], width=150, subsequent_indent=" " * 48)
            print(f"{line} {wrapped}" + (f"  ({d['ms']} ms)" if d["ms"] > 200 else ""))
        elif t == "photo_read":
            for p in d["photos"]:
                for it in p["items"]:
                    print(
                        f"         photo {p['index']} [{it['kind']}] {it['text'][:110]!r} box={it['box_2d']}"
                    )
        elif t == "registry_lookup":
            m = d["match"]
            hit = f"S.No. {m['s_no']} {m['name']} ({m['state']})" if m else "no match"
            print(
                f"{stamp} registry: {d['query']!r} → {hit} score {d['score']} ({d['rows_scanned']} rows)"
            )
        elif t == "evidence":
            print(
                f"{stamp} evidence {d['id']} → {d['claim_id']} [{d['source']}] {d['covers_claim']}: {d['detail'][:120]}"
            )
        elif t == "error":
            print(f"{stamp} ERROR: {d['message']}")
        elif t == "run_finished":
            print(
                f"{stamp} finished: {d['llm_calls']} model calls ({d.get('cached_calls', 0)} cached), "
                f"{d['tokens_in']}+{d['tokens_out']} tokens, ₹{d['est_cost_inr']:.2f}"
            )

    ctx = run_listing(listing, args.mode, on_event=show)
    print(f"\nVerdicts ({args.mode}, llm {s.praman_llm_mode}):")
    for c in ctx.claims:
        v = ctx.verdicts.get(c.id)
        if not v:
            print(f"  {c.id} (no verdict)")
            continue
        col = COLOURS.get(v.label.value, "")
        print(
            f'  {c.id} {col}{v.label.value:14}{RESET} "{c.quote[:70]}"  [{", ".join(v.rule_ids)}] {v.evidence_ids}'
        )
        print(textwrap.indent(textwrap.fill(v.reason, 130), "        "))
        if v.rewrite:
            print(textwrap.indent(textwrap.fill("Rewrite: " + v.rewrite, 130), "        "))
    return 1 if ctx.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
