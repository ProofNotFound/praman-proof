"""Record one real store scan for the app's recording mode (W3).

Usage: uv run scripts/export_scan_demo.py [--store L14]

Scans the store of a seed listing (default: L14's store) once, politely (robots.txt, ≤ 1 request
per second), with zero model calls, and writes the anonymised result to
data/recordings/scan_demo.json and frontend/public/demo/scan_demo.json. Refuses to write a file
that still names a brand or holds an email address or phone number.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FORMAT = "praman-scan/1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="L14", help="Seed listing whose store to scan")
    args = ap.parse_args()
    os.environ["PRAMAN_ANONYMISE"] = "1"
    if os.environ.get("PRAMAN_LLM_MODE") == "offline":
        os.environ["PRAMAN_LLM_MODE"] = "replay"  # a scan reads the store; no model is called

    from praman.anonymise import EMAIL_RE, PHONE_RE, has_brand
    from praman.config import RECORDINGS_DIR, ROOT, SEED_PATH
    from praman.scan import new_scan, public, run_scan

    row = next(r for r in csv.DictReader(SEED_PATH.open()) if r["id"] == args.store)
    scan = run_scan(new_scan(f"https://{row['store']}"))
    if scan.status != "finished":
        print(f"scan failed: {scan.message}")
        return 1
    doc = {
        "format": FORMAT,
        "synthetic": False,
        "recorded_at": datetime.now(UTC).isoformat(),
        **public(scan),
    }
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    if has_brand(text) or EMAIL_RE.search(text) or PHONE_RE.search(text):
        print("a brand name or contact detail is still in the scan; not written")
        return 1
    for path in (RECORDINGS_DIR / "scan_demo.json", ROOT / "frontend/public/demo/scan_demo.json"):
        path.write_text(text + "\n")
        print(f"wrote {path.relative_to(ROOT)}")
    bands: dict[str, int] = {}
    for r in scan.rows:
        bands[r.band] = bands.get(r.band, 0) + 1
    print(f"{scan.total} products from {scan.source}; bands {bands}; {scan.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
