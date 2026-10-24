"""Small builders for synthetic listings, claims and evidence (no real brands)."""

from __future__ import annotations

from datetime import UTC, datetime

from praman.models import Claim, Evidence, Listing, Photo, PhotoItem, PhotoPrint, PhotoReading
from praman.rules import normalise


def listing(
    title: str = "Test product",
    body: str = "",
    tags: list[str] | None = None,
    product_type: str = "",
    n_photos: int = 0,
    links: list[str] | None = None,
) -> Listing:
    return Listing(
        id="T1",
        source="cache",
        url="https://shop.example/products/test",
        store="shop.example",
        title=title,
        body_text=body,
        tags=tags or [],
        photos=[
            Photo(index=i + 1, url=f"https://cdn.example/{i + 1}.jpg") for i in range(n_photos)
        ],
        fetched_at=datetime.now(UTC),
        product_type=product_type,
        links=links or [],
    )


def claim(
    quote: str,
    type_: str = "specific",
    scope: str = "product",
    id_: str = "C1",
    is_claim: bool = True,
    rule_ids: list[str] | None = None,
    location: str = "description",
) -> Claim:
    return Claim(
        id=id_,
        quote=quote,
        normalised=normalise(quote),
        type=type_,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        location=location,
        is_claim=is_claim,
        not_claim_reason=None if is_claim else "Course subject",
        rule_ids=rule_ids or [],
    )


_n = 0


def ev(claim_id: str = "C1", **kw) -> Evidence:
    global _n
    _n += 1
    base = {
        "id": f"E{_n}",
        "claim_id": claim_id,
        "source": "text",
        "detail": "x",
        "covers_claim": "yes",
    }
    base.update(kw)
    return Evidence(**base)


def photo_print(*items: tuple[int, str, str]) -> PhotoPrint:
    """photo_print((7, "code", "CPCB-UPC-II/…"), (3, "composition", "…"))"""
    by: dict[int, PhotoReading] = {}
    for idx, kind, text in items:
        by.setdefault(idx, PhotoReading(index=idx)).items.append(
            PhotoItem(text=text, kind=kind, box_2d=[100, 100, 200, 400])  # type: ignore[arg-type]
        )
    return PhotoPrint(photos=list(by.values()), photo_indices_read=list(by))
