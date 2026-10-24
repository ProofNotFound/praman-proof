"""decode_qr (W4): read QR codes printed on a listing's photos with OpenCV, no model call.

Codes are decoded once, when a photo is downloaded, and kept in the cached listing (Photo.qr), so
runs and tests don't depend on the gitignored image files. A listing cached before W4 has no QR
data; the tool then decodes local files if they exist, but the planner only offers decode_qr
when the cached listing says a photo carries a QR code.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from praman.config import ROOT
from praman.models import Listing, QrCode

log = logging.getLogger(__name__)

URL_RE = re.compile(r"^https?://", re.I)


def _box(points, width: int, height: int) -> list[int] | None:
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except (TypeError, IndexError, ValueError):
        return None
    box = [
        int(max(0, min(ys)) / height * 1000),
        int(max(0, min(xs)) / width * 1000),
        int(min(height, max(ys)) / height * 1000),
        int(min(width, max(xs)) / width * 1000),
    ]
    return box if box[0] < box[2] and box[1] < box[3] else None


def decode_image(path: str | Path) -> list[QrCode]:
    """Every QR code OpenCV can read in an image (several per photo), with its box."""
    import cv2

    img = cv2.imread(str(path))
    if img is None:
        return []
    h, w = img.shape[:2]
    detector = cv2.QRCodeDetector()
    out: list[QrCode] = []
    for scale in (1.0, 2.0):  # small codes on big pack shots read better upscaled
        view = img if scale == 1.0 else cv2.resize(img, None, fx=scale, fy=scale)
        try:
            ok, texts, points, _ = detector.detectAndDecodeMulti(view)
        except cv2.error:
            ok, texts, points = False, (), None
        if ok and points is not None:
            for text, pts in zip(texts, points, strict=False):
                text = (text or "").strip()
                if text and all(text != q.data for q in out):
                    box = _box([(x / scale, y / scale) for x, y in pts], w, h)
                    out.append(QrCode(data=text, box_2d=box))
        if out:
            break
    return out


def listing_codes(listing: Listing, decode_missing: bool = True) -> dict[int, list[QrCode]]:
    """QR codes per photo index: stored ones, else (optionally) decoded from local files."""
    out: dict[int, list[QrCode]] = {}
    for p in listing.photos:
        codes = p.qr
        if codes is None and decode_missing and p.local_path and (ROOT / p.local_path).exists():
            codes = decode_image(ROOT / p.local_path)
        if codes:
            out[p.index] = codes
    return out


def has_stored_codes(listing: Listing) -> bool:
    """Did the download-time scan find a QR code? (The planner's only signal: deterministic.)"""
    return any(p.qr for p in listing.photos)


def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))
