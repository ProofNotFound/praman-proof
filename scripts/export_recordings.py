"""Run the demo listings in agent and baseline mode and export what the demo and tests need.

Usage: uv run scripts/export_recordings.py [L14 L06 ...] [--llm replay|offline] [--no-photos]

Writes (TRD §15.4):
- data/recordings/<id>.<mode>.json   one recording per run (anonymised events)
- data/recordings/index.json         [{listing_id, mode, title, file, claim_count, synthetic}]
- data/recordings/photos/<id>/<n>.jpg  photos with brand text blurred, long edge ≤ 1600 px
- tests/fixtures/replay/<id>.json    the model answers these runs used, for offline tests and CI
F5 copies data/recordings/ into frontend/public/demo/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEMO = ["L14", "L06", "L08", "L21"]
MODES = ["agent", "baseline"]
PHOTO_URL = "demo/photos/{listing_id}/{n}.jpg"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help=f"Listing IDs (default: {' '.join(DEMO)})")
    ap.add_argument("--llm", default="replay", choices=["replay", "offline"])
    ap.add_argument("--no-photos", action="store_true")
    ap.add_argument(
        "--photos-only",
        action="store_true",
        help="Re-mask the photos from the existing recordings; don't run anything",
    )
    args = ap.parse_args()
    os.environ["PRAMAN_LLM_MODE"] = args.llm
    os.environ["PRAMAN_ANONYMISE"] = "1"  # recordings are always anonymised

    from praman import llm
    from praman.agent import run_listing
    from praman.anonymise import find_brand_marks, has_brand, masked_photo_bytes, ocr_marks
    from praman.config import RECORDINGS_DIR, ROOT
    from praman.recording import build_recording, final_claims, photo_items
    from praman.tools.fetch import load_cached

    ids = args.ids or DEMO
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = RECORDINGS_DIR / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    index = [e for e in index if e["listing_id"] not in ids]
    failed = []
    for lid in ids:
        listing = load_cached(lid)
        items_by_photo: dict[int, list[dict]] = {}
        if args.photos_only:
            rec_path = RECORDINGS_DIR / f"{lid}.agent.json"
            items_by_photo = photo_items(json.loads(rec_path.read_text())["events"])
        for mode in [] if args.photos_only else MODES:
            ctx = run_listing(listing, mode)
            rec = build_recording(ctx.run_id, photo_url=PHOTO_URL)
            assert rec is not None
            if ctx.failed:
                failed.append(f"{lid}.{mode}")
                print(f"{lid}.{mode}: FAILED ({rec['events'][-1]['data'].get('message')})")
                continue
            text = json.dumps(rec, ensure_ascii=False)
            if has_brand(text):
                failed.append(f"{lid}.{mode} (brand name left in recording)")
            name = f"{lid}.{mode}.json"
            (RECORDINGS_DIR / name).write_text(json.dumps(rec, ensure_ascii=False, indent=1))
            claims = final_claims(rec["events"])
            index.append(
                {
                    "listing_id": lid,
                    "mode": mode,
                    "title": rec["title"],
                    "file": name,
                    "claim_count": sum(1 for c in claims if c["is_claim"]),
                    "synthetic": False,
                }
            )
            for idx, items in photo_items(rec["events"]).items():
                items_by_photo.setdefault(idx, []).extend(items)
            fin = rec["events"][-1]["data"]
            print(
                f"{lid}.{mode}: {len(rec['events'])} events, counts {fin.get('counts')}, "
                f"{fin.get('llm_calls')} model calls ({fin.get('cached_calls')} cached)"
            )
        if not args.no_photos:
            marks = find_brand_marks(listing)
            ocr = ocr_marks(listing)  # local OCR: contact data and brand text the model skipped
            out_dir = RECORDINGS_DIR / "photos" / lid
            out_dir.mkdir(parents=True, exist_ok=True)
            for p in listing.photos:
                data = masked_photo_bytes(listing, p.index, items_by_photo.get(p.index, []), 1600)
                if data:
                    (out_dir / f"{p.index}.jpg").write_bytes(data)
            n_marks = sum(len(v) for v in marks.values())
            n_ocr = sum(len(v) for v in ocr.values())
            print(
                f"   photos: {len(listing.photos)} written, {n_marks} brand marks and "
                f"{n_ocr} OCR lines blurred"
            )
        if args.photos_only:
            continue
        path = llm.export_replay(lid)
        print(f"   replay fixture: {path.relative_to(ROOT)} ({len(llm.used_keys(lid))} answers)")
    if args.photos_only:
        return 0  # recordings and index.json are untouched
    order = {lid: i for i, lid in enumerate(DEMO)}
    index.sort(
        key=lambda e: (order.get(e["listing_id"], 99), e["listing_id"], MODES.index(e["mode"]))
    )
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
