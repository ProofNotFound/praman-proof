"""Write the URL keys that let the app recognise a demo listing's URL without a backend.

Usage: uv run scripts/export_demo_urls.py

For each listing in data/recordings/index.json, writes its anonymised store domain
("brand-e.example") and SHA-256 hashes of the real store domain and the product handle, so
recording mode can open the case when someone pastes the real URL, while no brand domain is
shipped in frontend/public/. Output: data/recordings/urls.json, copied to
frontend/public/demo/urls.json.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def sha(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


def main() -> int:
    from praman.anonymise import brand_letter
    from praman.config import RECORDINGS_DIR, ROOT, SEED_PATH

    index = json.loads((RECORDINGS_DIR / "index.json").read_text())
    ids = list(dict.fromkeys(e["listing_id"] for e in index))
    seed = {r["id"]: r for r in csv.DictReader(SEED_PATH.open())}
    out = []
    for lid in ids:
        row = seed[lid]
        letter = brand_letter(lid)
        assert letter, lid
        out.append(
            {
                "listing_id": lid,
                "store": f"brand-{letter.lower()}.example",
                "store_sha256": sha(row["store"].removeprefix("www.")),
                "handle_sha256": sha(row["handle"]),
            }
        )
    text = json.dumps(out, indent=1) + "\n"
    for path in (RECORDINGS_DIR / "urls.json", ROOT / "frontend" / "public" / "demo" / "urls.json"):
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)} ({len(out)} listings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
