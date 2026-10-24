"""W2: product pages that aren't Shopify, from hand-written and anonymised real HTML (offline)."""

import json

import httpx
import pytest

from praman.anonymise import has_brand, mask_text
from praman.tools import fetch
from praman.tools.fetch import FetchError, load_cached
from praman.tools.page import (
    JS_SHELL_MESSAGE,
    NO_PRODUCT_MESSAGE,
    PageError,
    parse_product_html,
)


def html(fixtures_dir, name):
    return (fixtures_dir / "html" / name).read_text()


def test_json_ld_product(fixtures_dir):
    lst = parse_product_html(
        html(fixtures_dir, "jsonld.html"), "https://shop.example/products/cutlery", "U1"
    )
    assert lst.source == "json_ld"
    assert lst.title == "Bamboo Cutlery Set"
    assert "• 100% biodegradable bamboo" in lst.body_text and "<li>" not in lst.body_text
    assert lst.vendor == "Leafline"
    urls = [p.url for p in lst.photos]
    assert urls[0] == "https://shop.example/images/cutlery-1.jpg"  # relative URL made absolute
    assert "https://cdn.shop.example/images/cutlery-2.jpg" in urls
    assert not any("badge-icon" in u for u in urls)  # 64 px badge is not a product photo
    assert len(urls) == len({u.split("?")[0].rsplit("/", 1)[-1] for u in urls})  # no duplicates
    assert lst.links == ["https://shop.example/pages/certificates"]  # same site, main content only
    assert lst.store == "shop.example"


def test_opengraph_and_readable_text(fixtures_dir):
    lst = parse_product_html(
        html(fixtures_dir, "og_only.html"), "https://shop.example/products/doormat", "U2"
    )
    assert lst.source == "html"
    assert lst.title == "Natural Coir Doormat"
    assert "fully biodegradable" in lst.body_text
    for chrome in ("Sale!", "Newsletter", "Home and living"):  # header, footer, nav dropped
        assert chrome not in lst.body_text
    urls = [p.url for p in lst.photos]
    assert urls[:2] == [
        "https://cdn.shop.example/img/doormat-front.jpg",
        "https://cdn.shop.example/img/doormat-back.jpg",
    ]
    assert "https://shop.example/img/doormat-side.jpg" in urls
    assert not any("logo" in u or u.startswith("data:") for u in urls)
    assert len(urls) <= 10
    assert lst.vendor == "Leafline"


def test_page_without_a_product_says_so(fixtures_dir):
    with pytest.raises(PageError) as e:
        parse_product_html(
            html(fixtures_dir, "no_product.html"), "https://shop.example/pages/our-story", "U3"
        )
    assert str(e.value) == NO_PRODUCT_MESSAGE


def test_javascript_shell_says_it_cant_be_read(fixtures_dir):
    with pytest.raises(PageError) as e:
        parse_product_html(html(fixtures_dir, "js_shell.html"), "https://shop.example/p/1", "U4")
    assert str(e.value) == JS_SHELL_MESSAGE
    assert str(e.value).startswith("Couldn't read this page")


@pytest.mark.parametrize("lid", ["L15", "L09"])
def test_seed_pages_parse_like_their_shopify_json(fixtures_dir, lid):
    page = html(fixtures_dir, f"{lid}.html")
    assert not has_brand(page)
    lst = parse_product_html(page, f"https://brand-x.example/products/{lid.lower()}", lid)
    cached = load_cached(lid)
    assert lst.source == "json_ld"
    assert lst.title == mask_text(cached.title)
    first = mask_text(cached.body_text).split("\n")[0][:60]
    assert first in lst.body_text
    assert 1 <= len(lst.photos) <= 10


# ---------------------------------------------------------------------------
# fetch_listing over a fake network (httpx.MockTransport): Shopify first, then the page


def _fake_client(monkeypatch, tmp_path, routes):
    def handler(request: httpx.Request) -> httpx.Response:
        for path, resp in routes.items():
            if request.url.path == path:
                return resp() if callable(resp) else resp
        return httpx.Response(404)

    class FakeClient(fetch.PoliteClient):
        def __init__(self, *a, **k):
            super().__init__(min_gap_s=0)
            self.client = httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(fetch, "PoliteClient", FakeClient)
    monkeypatch.setattr(fetch, "LISTINGS_DIR", tmp_path)
    monkeypatch.setattr(fetch, "download_photos", lambda listing, client: [])


def _page(body: str, ctype: str = "text/html; charset=utf-8", **headers) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": ctype, **headers})


def test_fetch_listing_falls_back_from_shopify_to_json_ld(monkeypatch, tmp_path, fixtures_dir):
    _fake_client(
        monkeypatch, tmp_path, {"/products/cutlery": _page(html(fixtures_dir, "jsonld.html"))}
    )
    lst = fetch.fetch_listing(url="https://shop.example/products/cutlery")
    assert lst.source == "json_ld" and lst.title == "Bamboo Cutlery Set"
    saved = json.loads((tmp_path / f"{lst.id}.json").read_text())
    assert saved["listing"]["source"] == "json_ld"


def test_fetch_listing_uses_shopify_json_when_there(monkeypatch, tmp_path, fixtures_dir):
    product = json.loads((fixtures_dir / "shopify_product.json").read_text())
    _fake_client(
        monkeypatch,
        tmp_path,
        {"/products/bags.json": httpx.Response(200, json=product)},
    )
    lst = fetch.fetch_listing(url="https://shop.example/products/bags")
    assert lst.source == "shopify_json"


def test_fetch_listing_refuses_other_content_and_big_pages(monkeypatch, tmp_path):
    _fake_client(
        monkeypatch,
        tmp_path,
        {
            "/products/manual": _page("%PDF-1.4", ctype="application/pdf"),
            "/products/huge": _page("<html></html>", **{"content-length": str(6 * 1024 * 1024)}),
            "/products/stream": lambda: _page("<p>" + "x" * (5 * 1024 * 1024 + 10) + "</p>"),
        },
    )
    with pytest.raises(FetchError, match="isn't a web page"):
        fetch.fetch_listing(url="https://shop.example/products/manual")
    with pytest.raises(FetchError, match="larger than 5 MB"):
        fetch.fetch_listing(url="https://shop.example/products/huge")
    with pytest.raises(FetchError, match="larger than 5 MB"):
        fetch.fetch_listing(url="https://shop.example/products/stream")


def test_fetch_listing_reports_a_javascript_page(monkeypatch, tmp_path, fixtures_dir):
    _fake_client(monkeypatch, tmp_path, {"/app/item": _page(html(fixtures_dir, "js_shell.html"))})
    with pytest.raises(FetchError, match="Couldn't read this page"):
        fetch.fetch_listing(url="https://shop.example/app/item")
