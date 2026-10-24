"""Go/no-go: can the vision model read the CPCB codes and composition lines on two box photos?

Usage: uv run scripts/photo_probe.py [--mode live|replay|offline]
Sends L14 photo 7 and L06 photo 3 through the read_photos prompt and prints PASS/FAIL per check.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="live", choices=["live", "replay", "offline"])
    args = ap.parse_args()
    os.environ["PRAMAN_LLM_MODE"] = args.mode

    from praman import llm
    from praman.config import get_settings
    from praman.tools.fetch import load_cached
    from praman.tools.photos import read_photos

    s = get_settings()
    print(f"model={s.praman_model} mode={s.praman_llm_mode}")
    checks = [
        ("L14", 7, ["GREEN DOT BIOPAK", "SUNSHIELD"]),
        ("L06", 3, ["PE Virgin Grade"]),
    ]
    all_ok = True
    for lid, idx, needles in checks:
        listing = load_cached(lid)
        listing.photos = [p for p in listing.photos if p.index == idx]
        meter = llm.Meter()
        pp = read_photos(listing, meter=meter, max_photos=1)
        items = pp.all_items()
        text = "\n".join(it.text for _, it in items)
        print(
            f"\n{lid} photo {idx}: {len(items)} items, {meter.tokens_in} tokens in, "
            f"{meter.tokens_out} out, {meter.ms} ms"
        )
        for _, it in items:
            print(f"   [{it.kind:11}] {it.text}  box={it.box_2d}")
        for n in needles:
            ok = n.lower() in text.lower()
            all_ok &= ok
            print(f"{'PASS' if ok else 'FAIL'}: contains {n!r}")
        boxed = sum(1 for _, it in items if it.box_2d)
        ok = boxed > 0
        print(f"{'PASS' if ok else 'FAIL'}: boxes returned for {boxed}/{len(items)} items")
    print("\nOVERALL:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
