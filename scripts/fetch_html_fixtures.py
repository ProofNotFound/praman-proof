"""Save anonymised product-page HTML of seed listings as test fixtures (W2).

Usage: uv run scripts/fetch_html_fixtures.py L15 L09

Fetches each listing's product page once (robots.txt, ≤ 1 request per second per domain), keeps
the JSON-LD blocks and the markup, drops other scripts, styles, SVG and comments, masks brands,
store domains, emails and phone numbers (praman.anonymise), and writes
tests/fixtures/html/<id>.html. Refuses to write a file that still names a brand.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "html"


def slim(html: str) -> str:
    """Drop what the parser never reads: non-JSON-LD scripts, styles, SVG, comments, link tags."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(
        r"<script(?![^>]*application/ld\+json)[^>]*>.*?</script>", "", html, flags=re.S | re.I
    )
    for tag in ("style", "svg", "noscript", "template"):
        html = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", html, flags=re.S | re.I)
    html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)
    html = re.sub(r'\s(?:style|class|data-[\w-]+)="[^"]*"', "", html)
    # Long digit runs (phone numbers, but also GTINs and image versions) become a short number,
    # so masking can't break the JSON-LD with "[number hidden]"
    html = re.sub(r"(?<![\w/])\d(?:[\s-]?\d){9,}(?![\w/])", "1234", html)
    html = re.sub(r"(?<=[=v])\d{9,}", "1234", html)
    return re.sub(r"\n\s*\n+", "\n", html)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    args = ap.parse_args()
    from praman.anonymise import has_brand, mask_text
    from praman.config import SEED_PATH
    from praman.tools.fetch import PoliteClient

    rows = {r["id"]: r for r in csv.DictReader(SEED_PATH.open())}
    OUT.mkdir(parents=True, exist_ok=True)
    client = PoliteClient()
    failed = 0
    try:
        for lid in args.ids:
            _, html = client.get_page(rows[lid]["url"])
            text = mask_text(slim(html))
            if has_brand(text):
                print(f"{lid}: a brand name is still in the page; not written")
                failed += 1
                continue
            path = OUT / f"{lid}.html"
            path.write_text(text)
            print(
                f"{lid}: {len(html) // 1024} KB fetched, {len(text) // 1024} KB written to {path}"
            )
    finally:
        client.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
