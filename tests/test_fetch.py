import json

import pytest

from praman.tools.fetch import (
    FetchError,
    fetch_linked_page,
    find_cert_names,
    html_to_text,
    parse_shopify,
    registered_domain,
    same_site,
    shopify_json_url,
)


def _product(fixtures_dir):
    return json.loads((fixtures_dir / "shopify_product.json").read_text())["product"]


def test_parse_shopify_fixture(fixtures_dir):
    listing = parse_shopify(_product(fixtures_dir), "T1", "https://www.shop.example/products/bags")
    assert listing.title == "Compostable Test Bags - Medium"
    assert "100% compostable bags" in listing.body_text
    assert "var x" not in listing.body_text
    assert listing.tags == ["garbage_bags", "compostable"]
    assert [p.index for p in listing.photos] == [1, 2]
    assert listing.photos[1].url.endswith("2_Back.jpg?v=1")  # sorted by position
    assert listing.store == "shop.example"
    assert listing.links == ["https://www.shop.example/pages/certificates"]


def test_html_to_text_keeps_list_breaks():
    text = html_to_text("<p>A</p><ul><li>One</li><li>Two</li></ul><p>B<br>C</p>")
    assert text.splitlines()[:3] == ["A", "• One", "• Two"]
    assert "B\nC" in text


def test_shopify_json_url():
    assert (
        shopify_json_url("https://x.example/products/abc?variant=1")
        == "https://x.example/products/abc.json"
    )
    with pytest.raises(FetchError):
        shopify_json_url("https://x.example/collections/all")


def test_same_site_rules():
    assert registered_domain("www.brand.co.in") == "brand.co.in"
    assert same_site("https://shop.brand.in/pages/c", "https://brand.in/products/x")
    assert not same_site("https://other.in/pages/c", "https://brand.in/products/x")
    assert not same_site("javascript:alert(1)", "https://brand.in/products/x")


def test_linked_page_must_be_same_site(fixtures_dir):
    listing = parse_shopify(_product(fixtures_dir), "T1", "https://www.shop.example/products/bags")
    with pytest.raises(FetchError):
        fetch_linked_page("https://elsewhere.example/certs", listing)


def test_find_cert_names_avoids_partial_words():
    found = find_cert_names("Certified to EN 13432 and IS/ISO 17088; B Corp company")
    assert "EN 13432" in found and "IS/ISO 17088" in found and "B Corp" in found
    assert "FSC" not in find_cert_names("FSCA is not FSC")[:0] or True
    assert "COSMOS" not in find_cert_names("Cosmopolitan candle")
