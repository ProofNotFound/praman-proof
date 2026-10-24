import csv

from PIL import Image

from praman.anonymise import brand_letter, has_brand, mask, mask_photo, mask_text
from praman.config import SEED_PATH


def test_every_seed_brand_alias_and_store_is_masked():
    for row in csv.DictReader(SEED_PATH.open()):
        names = [row["brand"]] + [a for a in row["brand_aliases"].split(";") if a.strip()]
        for n in names:
            assert n.lower() not in mask_text(f"Made by {n} in India").lower(), n
        assert row["store"] not in mask_text(f"https://www.{row['store']}/products/x")


def test_masking_is_consistent_and_keeps_other_words():
    assert brand_letter("L14") == brand_letter("L13")
    assert brand_letter("L14") != brand_letter("L06")
    a = mask_text("Marketed by Kwick Living (I) Pvt. Ltd.")
    b = mask_text("BECO compostable bags")
    assert a.startswith("Marketed by Brand ") and b.endswith("compostable bags")
    assert a.split()[3] == b.split()[1]  # alias and brand share a letter
    assert mask_text("become eco-friendly") == "become eco-friendly"
    assert mask_text("PeeSafeIndia") != "PeeSafeIndia"
    assert mask_text("Greendot Biopak Pvt Ltd") == "Greendot Biopak Pvt Ltd"  # registry makers stay


def test_mask_walks_nested_data():
    out = mask({"title": "Pee Safe bags", "items": [{"text": "visit barenecessities.in"}], "n": 3})
    assert out["n"] == 3 and not has_brand(out["title"]) and "example" in out["items"][0]["text"]


def test_mask_photo_blurs_only_brand_boxes(tmp_path):
    p = tmp_path / "p.jpg"
    img = Image.new("RGB", (200, 200), "white")
    for x in range(0, 200, 4):
        for y in range(0, 100):
            img.putpixel((x, y), (0, 0, 0))
    img.save(p)
    out = tmp_path / "o.jpg"
    out.write_bytes(
        mask_photo(
            p,
            [
                {"text": "BECO", "box_2d": [0, 0, 400, 1000]},
                {"text": "CPCB code", "box_2d": [600, 0, 900, 1000]},
            ],
        )
    )
    masked = Image.open(out).convert("L")
    # Stripes in the brand box are smoothed; the rest of the image keeps its edges
    assert 30 < masked.getpixel((2, 40)) < 230
    assert masked.getpixel((100, 150)) > 240


def test_event_text_hides_emails_and_phone_numbers():
    from praman.anonymise import mask_text

    out = mask_text("Write to care@shop.example or call +91 98765 43210")
    assert out == "Write to [email hidden] or call [number hidden]"
    assert mask_text("CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443, Gujarat 382213") == (
        "CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443, Gujarat 382213"
    )


def test_photo_items_with_contact_data_or_brand_letters_are_blurred():
    from praman.anonymise import brand_item, names_brand

    for text in (
        "shop@beco.co.in",
        "www.letsbeco.com",
        "Call 9326673496",
        "BareNecessitiesZeroWaste",
    ):
        assert brand_item(text), text
    for text in ("Composts in 180 days.", "CPCB: CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443"):
        assert not brand_item(text), text
    # OCR fuzziness tolerates misreads but a short fragment can't match a long brand name
    assert names_brand("Bare Necesities Zero", fuzzy=True)
    assert not names_brand("T", fuzzy=True)


def test_new_stores_get_the_next_free_letter_and_keep_it(monkeypatch):
    from praman import anonymise

    seed_letters = {e[0] for e in anonymise._seed()[0]}
    first = anonymise.register("www.greenleaf-store.example", ["Leafline Naturals"])
    second = anonymise.register("shop.otherbrand.co.in", ["Otherbrand"])
    assert first not in seed_letters and second not in seed_letters and first != second
    assert anonymise.letter_label(len(seed_letters)) == first  # the next one after the seed
    # Same store, or the same brand on another domain: same letter
    assert anonymise.register("greenleaf-store.example") == first
    assert anonymise.register("leafline.example", ["Leafline Naturals"]) == first
    # A new process reads the letters back from SQLite
    monkeypatch.setattr(anonymise, "_version", anonymise._version + 100)
    anonymise._table_cache.clear()
    assert anonymise.register("greenleaf-store.example") == first
    text = mask_text("Leafline Naturals ships from https://www.greenleaf-store.example/products/x")
    assert text == f"Brand {first} ships from https://brand-{first.lower()}.example/products/x"
    assert has_brand("Otherbrand bags")


def test_seed_stores_keep_their_seed_letter_and_generic_names_stay():
    from praman import anonymise

    assert anonymise.register("www.letsbeco.com", ["Beco"]) == brand_letter("L14")
    letter = anonymise.register("green.example", ["Green", "Eco"])
    assert letter is not None
    assert (
        mask_text("Green bags from green.example")
        == f"Green bags from brand-{letter.lower()}.example"
    )
    assert anonymise.letter_label(0) == "A" and anonymise.letter_label(26) == "AA"


def test_the_short_brand_in_a_title_is_hidden_for_a_new_store():
    from datetime import UTC, datetime

    from praman import anonymise
    from praman.models import Listing

    def listing(title, vendor, store):
        return Listing(
            id="Utest",
            source="shopify_json",
            store=store,
            title=title,
            vendor=vendor,
            body_text="",
            fetched_at=datetime.now(UTC),
        )

    # "Plum Color Affair" at plumgoodness.com, vendor "Plum Goodness": "Plum" alone must go too
    lst = listing("Plum Color Affair Nail Polish Remover", "Plum Goodness", "plumgoodness.com")
    letter = anonymise.register_listing(lst)
    assert mask_text(lst.title) == f"Brand {letter} Color Affair Nail Polish Remover"
    assert mask_text("by Plum Goodness") == f"by Brand {letter}"
    # A material word that starts the domain is not a brand
    bamboo = listing("Bamboo Soap Dish", "Bamboo Products", "bambooproducts.in")
    anonymise.register_listing(bamboo)
    assert mask_text("Bamboo Soap Dish") == "Bamboo Soap Dish"
    assert anonymise.listing_brand_names(bamboo) == ["Bamboo Products", "Bamboo"]
