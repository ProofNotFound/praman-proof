"""read_photos (TRD §7.1): read printed claims, marks, codes and composition from listing photos."""

from __future__ import annotations

import re

from PIL import Image, ImageFilter

from praman import llm
from praman.config import ROOT, get_settings
from praman.models import Listing, PhotoItem, PhotoPrint, PhotoReading, ReadPhotosOut

BOXBACK_WORDS = ("back", "label", "box", "pack", "ingredient", "detail", "info")


def _named_boxback(url: str) -> bool:
    name = url.rsplit("/", 1)[-1].split("?")[0].lower()
    tokens = set(re.split(r"[^a-z]+", name))
    return bool(tokens & set(BOXBACK_WORDS))


def text_score(local_path: str | None) -> float:
    """Share of strong edges in a small greyscale copy: text-heavy photos score higher."""
    if not local_path:
        return 0.0
    try:
        im = Image.open(ROOT / local_path).convert("L")
    except OSError:
        return 0.0
    im.thumbnail((512, 512))
    edges = im.filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    strong = sum(hist[81:])
    return strong / max(1, sum(hist))


def choose_photos(listing: Listing, max_photos: int | None = None) -> list[int]:
    """Pick up to max_photos indices, likely box backs and labels first.

    Order: photos whose URL or alt text names a back/label/box; then the last 3 photos (stores put
    the pack shots last); then the most text-heavy of the rest. Ties keep listing order.
    """
    max_photos = max_photos or get_settings().praman_max_photos
    photos = [p for p in listing.photos if p.local_path or p.url]
    if len(photos) <= max_photos:
        return sorted((p.index for p in photos), reverse=True)
    chosen: list[int] = []

    def add(i: int) -> None:
        if i not in chosen and len(chosen) < max_photos:
            chosen.append(i)

    # File names like "..._Back.jpg" are a strong hint, but only when they single photos out
    named = [p.index for p in photos if _named_boxback(p.url)]
    if len(named) <= len(photos) // 2:
        for i in named:
            add(i)
    for p in sorted(photos, key=lambda p: -p.index)[:3]:
        add(p.index)
    rest = sorted(
        (p for p in photos if p.index not in chosen),
        key=lambda p: (
            -(p.text_score if p.text_score is not None else text_score(p.local_path)),
            p.index,
        ),
    )
    for p in rest:
        add(p.index)
    return chosen


def read_photos(
    listing: Listing, meter: llm.Meter | None = None, max_photos: int | None = None
) -> PhotoPrint:
    indices = choose_photos(listing, max_photos)
    by_index = {p.index: p for p in listing.photos}
    images = [
        llm.image_ref(listing.id, i, by_index[i].url, by_index[i].local_path) for i in indices
    ]
    if not images:
        return PhotoPrint(photos=[], photo_indices_read=[])
    res = llm.call(
        "read_photos",
        ReadPhotosOut,
        variables={"n_photos": len(images), "title": listing.title},
        images=images,
        listing_id=listing.id,
        meter=meter,
    )
    readings: dict[int, PhotoReading] = {}
    for ph in res.data.photos:
        if ph.photo not in by_index:
            continue
        items = []
        for it in ph.items:
            text = it.text.strip()
            if not text:
                continue
            box = it.box_2d if it.box_2d and len(it.box_2d) == 4 else None
            if box:
                box = [max(0, min(1000, int(v))) for v in box]
                if box[0] >= box[2] or box[1] >= box[3]:
                    box = None
            is_claim = it.kind == "claim"
            items.append(
                PhotoItem(
                    text=text,
                    kind=it.kind,
                    box_2d=box,
                    claim_type=it.claim_type if is_claim else None,
                    scope=it.scope if is_claim else None,
                )
            )
        r = readings.setdefault(ph.photo, PhotoReading(index=ph.photo))
        r.items.extend(items)
        r.qr_present = r.qr_present or ph.qr_present
    ordered = [readings.get(i, PhotoReading(index=i)) for i in indices]
    return PhotoPrint(photos=ordered, photo_indices_read=indices)
