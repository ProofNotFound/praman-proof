from datetime import UTC, datetime

from praman.models import Listing, Photo
from praman.tools.photos import choose_photos


def _listing(n: int, names: list[str] | None = None) -> Listing:
    names = names or [f"{i}.jpg" for i in range(1, n + 1)]
    return Listing(
        id="T",
        source="cache",
        title="t",
        body_text="",
        fetched_at=datetime.now(UTC),
        photos=[Photo(index=i + 1, url=f"https://cdn.example/{names[i]}") for i in range(n)],
    )


def test_small_listings_read_every_photo_last_first():
    assert choose_photos(_listing(3), 5) == [3, 2, 1]


def test_large_listings_take_last_three_first():
    chosen = choose_photos(_listing(9), 5)
    assert chosen[:3] == [9, 8, 7]
    assert len(chosen) == 5


def test_named_back_photo_comes_first():
    names = [f"{i}.jpg" for i in range(1, 12)]
    names[3] = "Product_Back.jpg"
    chosen = choose_photos(_listing(11, names), 5)
    assert chosen[0] == 4
