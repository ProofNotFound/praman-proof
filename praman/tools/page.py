"""Product pages that aren't Shopify (W2): schema.org Product JSON-LD first, then OpenGraph tags
plus the page's main readable text. Pure functions over an HTML string, so tests run offline.

No JavaScript is run: a page that builds its content in the browser yields a clear
"Couldn't read this page" error instead of an empty listing.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from praman.models import Listing, Photo

MAX_PHOTOS = 10
MAX_TEXT_CHARS = 20_000
MIN_TEXT_CHARS = 200  # less readable text than this, with no product data, means a JS-built page
MIN_IMAGE_EDGE = 300  # gallery images smaller than this (when sizes are given) are icons or badges
DROP_TAGS = ("script", "style", "noscript", "svg", "template", "iframe", "nav", "header", "footer")
SKIP_IMAGE_WORDS = ("logo", "icon", "sprite", "favicon", "placeholder", "loader", "payment", "flag")
PRODUCT_PATH_RE = re.compile(r"/(products?|p|item|shop)/", re.I)

JS_SHELL_MESSAGE = (
    "Couldn't read this page: its content is built by JavaScript in the browser, which Praman "
    "doesn't run. Try the product's own page on the store."
)
NO_PRODUCT_MESSAGE = (
    "Couldn't read this page as a product: it has no product details (name, description or "
    "photos). Paste the URL of a single product's page."
)


class PageError(ValueError):
    """The page can't be turned into a listing; the message is shown to the user as is."""


# ---------------------------------------------------------------------------
# JSON-LD


def _ld_blocks(tree: HTMLParser) -> list[Any]:
    out = []
    for node in tree.css('script[type="application/ld+json"]'):
        raw = (node.text() or "").strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            # Themes sometimes leave trailing commas or raw newlines inside strings
            try:
                out.append(json.loads(re.sub(r",\s*([}\]])", r"\1", raw), strict=False))
            except json.JSONDecodeError:
                continue
    return out


def _is_product(obj: dict) -> bool:
    t = obj.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.lower() in ("product", "productgroup") for x in types)


def find_ld_product(tree: HTMLParser) -> dict | None:
    """The first schema.org Product in any JSON-LD block (top level, lists or @graph)."""
    stack = list(_ld_blocks(tree))
    while stack:
        obj = stack.pop(0)
        if isinstance(obj, list):
            stack[:0] = obj
        elif isinstance(obj, dict):
            if _is_product(obj):
                return obj
            if isinstance(obj.get("@graph"), list):
                stack[:0] = obj["@graph"]
    return None


def _text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or value.get("@value") or "")
    if isinstance(value, list) and value:
        return _text_of(value[0])
    return ""


def _ld_images(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        u = value.get("url") or value.get("contentUrl")
        return [u] if isinstance(u, str) else []
    if isinstance(value, list):
        return [u for v in value for u in _ld_images(v)]
    return []


# ---------------------------------------------------------------------------
# OpenGraph, readable text and gallery images


def _meta(tree: HTMLParser, key: str) -> list[str]:
    out = []
    for node in tree.css(f'meta[property="{key}"], meta[name="{key}"]'):
        c = (node.attributes.get("content") or "").strip()
        if c:
            out.append(c)
    return out


def _main_region(tree: HTMLParser):
    for sel in ("main", "article", '[role="main"]', "#main", "#content"):
        node = tree.css_first(sel)
        if node is not None and len(node.text(strip=True) or "") > 80:
            return node
    return tree.body


def readable(html: str) -> tuple[str, str]:
    """(text, region html) of the main content, without nav, header, footer and scripts."""
    from praman.tools.fetch import html_to_text

    tree = HTMLParser(html)
    for tag in DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    region = _main_region(tree)
    region_html = region.html if region is not None else ""
    return html_to_text(region_html or "")[:MAX_TEXT_CHARS], region_html or ""


def _int(v: str | None) -> int | None:
    m = re.match(r"\s*(\d+)", v or "")
    return int(m.group(1)) if m else None


def gallery_images(region_html: str, base_url: str) -> list[tuple[str, str]]:
    """(url, alt) of large images in the main content: no icons, logos or tiny badges."""
    out: list[tuple[str, str]] = []
    if not region_html:
        return out
    for img in HTMLParser(region_html).css("img"):
        a = img.attributes
        src = a.get("data-src") or a.get("src") or ""
        if not src and a.get("srcset"):
            src = (a.get("srcset") or "").split(",")[-1].strip().split(" ")[0]
        if not src or src.startswith("data:") or src.lower().split("?")[0].endswith(".svg"):
            continue
        w, h = _int(a.get("width")), _int(a.get("height"))
        if (w is not None and w < MIN_IMAGE_EDGE) or (h is not None and h < MIN_IMAGE_EDGE):
            continue
        name = urlparse(src).path.rsplit("/", 1)[-1].lower()
        if any(word in name for word in SKIP_IMAGE_WORDS):
            continue
        out.append((urljoin(base_url, src), (a.get("alt") or "").strip()))
    return out


def _dedupe(images: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out = []
    for url, alt in images:
        parts = urlparse(url)
        # One photo whatever the scheme, host (store or CDN) or size parameters
        key = parts.path.removesuffix("/").lower()
        if parts.scheme in ("http", "https") and key not in seen:
            seen.add(key)
            out.append((url, alt))
    return out[:MAX_PHOTOS]


# ---------------------------------------------------------------------------
# Entry point


def parse_product_html(html: str, url: str, listing_id: str) -> Listing:
    """A Listing from a product page's HTML: JSON-LD Product if present, else OpenGraph tags plus
    the main readable text. Raises PageError with a message for the user when it can't."""
    from praman.tools.fetch import extract_links, html_to_text

    tree = HTMLParser(html)
    text, region_html = readable(html)
    product = find_ld_product(tree)
    og_title = (_meta(tree, "og:title") or [""])[0]
    og_desc = (_meta(tree, "og:description") or _meta(tree, "description") or [""])[0]
    og_images = [(urljoin(url, u), "") for u in _meta(tree, "og:image")]
    site = (_meta(tree, "og:site_name") or [""])[0]
    page_title = (tree.css_first("title").text(strip=True) if tree.css_first("title") else "") or ""
    store = urlparse(url).netloc.lower().removeprefix("www.")
    links = extract_links(region_html, url)[:50]

    if product:
        title = _text_of(product.get("name")).strip() or og_title or page_title
        desc = _text_of(product.get("description")).strip()
        body = html_to_text(desc) if "<" in desc else desc.strip()
        if len(body) < 80:  # no description in the markup: the page text is the description
            body = text or og_desc
        images = [(urljoin(url, u), "") for u in _ld_images(product.get("image"))]
        images += og_images + gallery_images(region_html, url)
        return Listing(
            id=listing_id,
            source="json_ld",
            url=url,
            store=store,
            title=title,
            body_text=body.strip(),
            photos=_photos(_dedupe(images)),
            fetched_at=datetime.now(UTC),
            vendor=_text_of(product.get("brand")).strip() or site,
            product_type=_text_of(product.get("category")).strip(),
            links=links,
        )

    og_type = (_meta(tree, "og:type") or [""])[0].lower()
    product_signal = (
        og_type.startswith("product")
        or bool(_meta(tree, "product:price:amount"))
        or bool(tree.css_first('[itemtype*="schema.org/Product"]'))
        or bool(PRODUCT_PATH_RE.search(urlparse(url).path))
    )
    if len(text) < MIN_TEXT_CHARS and not og_desc:
        raise PageError(JS_SHELL_MESSAGE)
    if not product_signal or not (og_title or page_title):
        raise PageError(NO_PRODUCT_MESSAGE)
    body = text if len(text) >= MIN_TEXT_CHARS else "\n\n".join(p for p in (og_desc, text) if p)
    images = og_images + gallery_images(region_html, url)
    return Listing(
        id=listing_id,
        source="html",
        url=url,
        store=store,
        title=(og_title or page_title).strip(),
        body_text=body.strip(),
        photos=_photos(_dedupe(images)),
        fetched_at=datetime.now(UTC),
        vendor=site,
        links=links,
    )


def _photos(images: list[tuple[str, str]]) -> list[Photo]:
    return [Photo(index=i + 1, url=u, alt=alt) for i, (u, alt) in enumerate(images)]
