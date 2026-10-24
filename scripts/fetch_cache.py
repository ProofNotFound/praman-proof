"""Download every seed listing (Shopify JSON) and its photos into data/cache.

Usage: uv run scripts/fetch_cache.py [L14 L06 ...] [--force]
Respects robots.txt and keeps ≤ 1 request per second per domain. Failures are logged and skipped.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praman.config import IMAGES_DIR, SEED_PATH  # noqa: E402
from praman.tools.fetch import (  # noqa: E402
    PoliteClient,
    cache_path,
    download_photos,
    fetch_shopify,
    rescore_cached,
    save_cached,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="Listing IDs (default: all seed rows)")
    ap.add_argument("--force", action="store_true", help="Re-fetch listings already cached")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = list(csv.DictReader(SEED_PATH.open()))
    if args.ids:
        rows = [r for r in rows if r["id"] in set(args.ids)]

    client = PoliteClient()
    ok, failed = 0, []
    try:
        for row in rows:
            lid, url = row["id"], row["url"]
            if cache_path(lid).exists() and not args.force:
                photos_dir = IMAGES_DIR / lid
                note = ", photo scores added" if rescore_cached(lid) else ""
                print(f"{lid}: cached ({len(list(photos_dir.glob('*.jpg')))} photos{note})")
                ok += 1
                continue
            try:
                listing, raw = fetch_shopify(url, lid, client)
            except Exception as e:  # noqa: BLE001
                print(f"{lid}: FAILED listing: {e}")
                failed.append(lid)
                continue
            photo_failures = download_photos(listing, client)
            save_cached(listing, raw)
            got = sum(1 for p in listing.photos if p.local_path)
            print(f"{lid}: {listing.title[:60]!r}, {got}/{len(listing.photos)} photos")
            for f in photo_failures:
                print(f"   {f}")
            ok += 1
    finally:
        client.close()
    print(f"\n{ok} cached, {len(failed)} failed {failed if failed else ''}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
