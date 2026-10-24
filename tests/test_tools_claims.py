from helpers import claim, listing, photo_print

from praman.models import LLMClaim
from praman.tools.claims import _dedupe, claims_from_photos, find_span, locate


def test_find_span_returns_exact_listing_words():
    text = "Made from Sugarcane and cornstarch\n100% compostable garbage bags\nLeak proof"
    assert find_span("100% Compostable Garbage Bags", text) == "100% compostable garbage bags"
    assert find_span("100% compostable  garbage\nbags", text) == "100% compostable garbage bags"
    assert find_span("biodegradable within 90 days", text) is None


def test_locate_prefers_named_location_and_checks_alt_text():
    lst = listing(title="Bamboo Toothbrush", body="Zero waste oral care.", n_photos=5)
    lst.photos[4].alt = "Bamboo toothbrush plastic-free alternative"
    assert locate("Zero waste oral care", "description", lst, None) == (
        "Zero waste oral care",
        "description",
    )
    assert locate("plastic-free alternative", "photo:5", lst, None) == (
        "plastic-free alternative",
        "photo:5",
    )
    assert locate("made of recycled ocean plastic", "description", lst, None) is None


def _llm(quote, is_claim=True, type_="specific"):
    return LLMClaim(
        quote=quote, type=type_, scope="product", location="description", is_claim=is_claim
    )


def test_dedupe_drops_contained_claims_and_caps():
    items = [_llm("Zero waste"), _llm("Zero waste oral care"), _llm("eco-friendly", type_="vague")]
    kept = [c.quote for c in _dedupe(items)]
    assert kept == ["Zero waste oral care", "eco-friendly"]
    many = [_llm(f"claim number {i}") for i in range(12)] + [_llm("plastic free handle")]
    kept = [c.quote for c in _dedupe(many)]
    assert len(kept) == 8 and "plastic free handle" in kept  # trigger-term claims win the cap


def test_claims_from_photos_adds_only_new_green_claims():
    lst = listing(title="Compostable Garbage Bags")
    existing = [claim("100% compostable garbage bags")]
    pp = photo_print(
        (7, "claim", "100% ecofriendly, 0% plastic."),
        (7, "claim", "GREEN CREDS:"),
        (6, "claim", "100% compostable"),
        (5, "claim", "Leak proof and strong"),
    )
    new = claims_from_photos(pp, existing, lst)
    assert [(c.id, c.quote, c.location) for c in new] == [
        ("C2", "100% ecofriendly, 0% plastic.", "photo:7")
    ]


def test_cert_links_skip_other_product_pages():
    from praman.agent import cert_links

    lst = listing(
        links=[
            "https://shop.example/products/compostable-brush",
            "https://shop.example/pages/certificates",
            "https://shop.example/collections/compostable",
        ]
    )
    assert cert_links(lst) == ["https://shop.example/pages/certificates"]
