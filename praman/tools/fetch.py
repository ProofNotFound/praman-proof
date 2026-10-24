"""fetch_listing and fetch_linked_page (TRD §7, §14). Read-only, polite, same-site only."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from PIL import Image
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from praman import guard
from praman.config import IMAGES_DIR, LISTINGS_DIR, ROOT, USER_AGENT
from praman.models import Listing, Photo

log = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_PAGE_CHARS = 20_000
HTML_TYPES = ("text/html", "application/xhtml+xml")


class FetchError(RuntimeError):
    """A fetch that was refused (robots, other domain) or failed."""


class PoliteClient:
    """httpx client with a robots.txt check and ≤ 1 request per second per domain."""

    def __init__(self, timeout_s: float = 15.0, min_gap_s: float = 1.0) -> None:
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            event_hooks={"request": [guard.request_hook]},
        )
        self.min_gap_s = min_gap_s
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _wait(self, host: str) -> None:
        with self._lock:
            gap = time.monotonic() - self._last.get(host, 0.0)
            if gap < self.min_gap_s:
                time.sleep(self.min_gap_s - gap)
            self._last[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        host = parts.netloc
        if host not in self._robots:
            robots_url = f"{parts.scheme}://{host}/robots.txt"
            self._wait(host)
            try:
                r = self.client.get(robots_url)
                if r.status_code >= 400:
                    self._robots[host] = None  # no robots.txt: everything allowed
                else:
                    rp = RobotFileParser()
                    rp.parse(r.text.splitlines())
                    self._robots[host] = rp
            except httpx.HTTPError as e:
                log.warning("robots.txt unavailable for %s: %s", host, e)
                self._robots[host] = None
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> httpx.Response:
        if not self.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        self._wait(urlparse(url).netloc)
        r = self.client.get(url)
        r.raise_for_status()
        return r

    def get_page(
        self, url: str, max_bytes: int = MAX_PAGE_BYTES, types: tuple[str, ...] = HTML_TYPES
    ) -> tuple[str, str]:
        """(final URL, text) of a page, refusing other content types and bodies over max_bytes."""
        if not self.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        self._wait(urlparse(url).netloc)
        with self.client.stream("GET", url) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            if types and ctype not in types:
                raise FetchError(
                    f"That address isn't a web page (it serves {ctype or 'an unknown type'})."
                )
            declared = r.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise FetchError("That page is larger than 5 MB, so Praman didn't read it.")
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise FetchError("That page is larger than 5 MB, so Praman didn't read it.")
                chunks.append(chunk)
            body = b"".join(chunks)
            return str(r.url), body.decode(r.encoding or "utf-8", errors="replace")

    def close(self) -> None:
        self.client.close()


# ---------------------------------------------------------------------------
# HTML → text


def html_to_text(html: str) -> str:
    """Strip HTML, keep paragraph and list breaks, collapse whitespace."""
    if not html:
        return ""
    tree = HTMLParser(html)
    for tag in ("script", "style", "noscript", "svg"):
        for node in tree.css(tag):
            node.decompose()
    for node in tree.css("br"):
        node.replace_with("\n")
    for tag in ("p", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "ul", "ol"):
        for node in tree.css(tag):
            node.insert_after("\n")
    for node in tree.css("li"):
        node.insert_before("• ")
    text = tree.body.text(separator="") if tree.body else tree.text(separator="")
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def extract_links(html: str, base_url: str) -> list[str]:
    """Absolute same-site links from an HTML fragment, in order, de-duplicated."""
    if not html:
        return []
    tree = HTMLParser(html)
    seen: list[str] = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absu = urljoin(base_url, href)
        if same_site(absu, base_url) and absu not in seen:
            seen.append(absu)
    return seen


def registered_domain(host: str) -> str:
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    # Good enough for the seed stores (.com, .in, .co, .co.in)
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_site(url: str, base_url: str) -> bool:
    a, b = urlparse(url), urlparse(base_url)
    if a.scheme not in ("http", "https"):
        return False
    return registered_domain(a.netloc) == registered_domain(b.netloc)


# ---------------------------------------------------------------------------
# Shopify


def shopify_json_url(url: str) -> str:
    parts = urlparse(url)
    path = parts.path.rstrip("/")
    if path.endswith(".json"):
        return f"{parts.scheme}://{parts.netloc}{path}"
    m = re.search(r"/products/([^/?#]+)", path)
    if not m:
        raise FetchError("Not a Shopify product URL (expected /products/<handle>)")
    return f"{parts.scheme}://{parts.netloc}/products/{m.group(1)}.json"


def parse_shopify(product: dict, listing_id: str, url: str) -> Listing:
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    photos = []
    for i, img in enumerate(
        sorted(product.get("images") or [], key=lambda x: x.get("position", 0))
    ):
        photos.append(
            Photo(
                index=i + 1,
                url=img.get("src", ""),
                alt=img.get("alt") or "",
                width=img.get("width"),
                height=img.get("height"),
            )
        )
    body_html = product.get("body_html") or ""
    return Listing(
        id=listing_id,
        source="shopify_json",
        url=url,
        store=urlparse(url).netloc.lower().removeprefix("www."),
        title=(product.get("title") or "").strip(),
        body_text=html_to_text(body_html),
        tags=tags,
        photos=photos,
        fetched_at=datetime.now(UTC),
        product_type=product.get("product_type") or "",
        vendor=product.get("vendor") or "",
        links=extract_links(body_html, url),
    )


def listing_id_for_url(url: str) -> str:
    return "U" + hashlib.sha256(url.encode()).hexdigest()[:8]


def save_image(content: bytes, dest: Path) -> tuple[int, int]:
    """Save as JPEG at original resolution; returns (width, height)."""
    img = Image.open(io.BytesIO(content))
    img.load()
    w, h = img.size
    dest.parent.mkdir(parents=True, exist_ok=True)
    if img.format == "JPEG":
        dest.write_bytes(content)
    else:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        img.save(dest, "JPEG", quality=92)
    return w, h


def download_photos(listing: Listing, client: PoliteClient) -> list[str]:
    """Download every photo to data/cache/images/<id>/<n>.jpg. Returns failure messages."""
    from praman.tools.photos import text_score

    failures = []
    for p in listing.photos:
        dest = IMAGES_DIR / listing.id / f"{p.index}.jpg"
        if not dest.exists():
            try:
                r = client.get(p.url)
                if len(r.content) > MAX_IMAGE_BYTES:
                    failures.append(f"photo {p.index}: larger than 8 MB, skipped")
                    continue
                p.width, p.height = save_image(r.content, dest)
            except Exception as e:  # noqa: BLE001 - log and keep going
                failures.append(f"photo {p.index}: {e}")
                continue
        p.local_path = str(dest.relative_to(ROOT))
        p.text_score = round(text_score(p.local_path), 5)
        try:
            from praman.tools.qr import decode_image

            p.qr = decode_image(dest)  # stored with the listing: runs don't need the image (W4)
        except Exception as e:  # noqa: BLE001 - a photo OpenCV can't read has no QR code
            log.warning("QR scan failed for photo %s: %s", p.index, e)
            p.qr = []
    return failures


def rescore_cached(listing_id: str) -> bool:
    """Add missing photo text scores to a cached listing. Returns True if the file changed."""
    path = cache_path(listing_id)
    doc = json.loads(path.read_text())
    changed = False
    from praman.tools.photos import text_score

    for p in doc["listing"]["photos"]:
        local = IMAGES_DIR / listing_id / f"{p['index']}.jpg"
        if p.get("text_score") is None and local.exists():
            p["text_score"] = round(text_score(str(local.relative_to(ROOT))), 5)
            changed = True
    if changed:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    return changed


def fetch_shopify(url: str, listing_id: str, client: PoliteClient) -> tuple[Listing, dict]:
    r = client.get(shopify_json_url(url))
    data = r.json()
    product = data.get("product", data)
    if not isinstance(product, dict) or not product.get("title"):
        raise FetchError("Not a Shopify product")
    return parse_shopify(product, listing_id, url), product


def fetch_html_listing(url: str, listing_id: str, client: PoliteClient) -> Listing:
    """Any product page: JSON-LD Product, else OpenGraph tags plus the main readable text."""
    from praman.tools.page import PageError, parse_product_html

    final_url, html = client.get_page(url)
    if not same_site(final_url, url):
        raise FetchError("That page redirects to another site, so Praman didn't follow it.")
    try:
        return parse_product_html(html, url, listing_id)
    except PageError as e:
        raise FetchError(str(e)) from e


# ---------------------------------------------------------------------------
# Tool: fetch_listing


def cache_path(listing_id: str) -> Path:
    return LISTINGS_DIR / f"{listing_id}.json"


def save_cached(listing: Listing, raw: dict | None = None) -> Path:
    path = cache_path(listing.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"listing": json.loads(listing.model_dump_json()), "raw": raw}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    return path


def load_cached(listing_id: str) -> Listing:
    path = cache_path(listing_id)
    if not path.exists():
        raise FetchError(f"Listing {listing_id} isn't in the cache (run scripts/fetch_cache.py)")
    doc = json.loads(path.read_text())
    listing = Listing.model_validate(doc["listing"])
    listing.source = "cache"
    for p in listing.photos:
        local = IMAGES_DIR / listing.id / f"{p.index}.jpg"
        p.local_path = str(local.relative_to(ROOT)) if local.exists() else None
    return listing


def fetch_listing(
    listing_id: str | None = None,
    url: str | None = None,
    pasted_text: str | None = None,
    pasted_title: str = "Pasted listing",
) -> Listing:
    """Load a cached listing, fetch a product URL live, or wrap pasted text.

    A URL is tried as Shopify (/products/<handle>.json) first, then as any product page:
    schema.org Product JSON-LD, else OpenGraph tags plus the main readable text (W2).
    """
    if listing_id:
        return load_cached(listing_id)
    if url:
        lid = listing_id_for_url(url)
        if cache_path(lid).exists():
            return load_cached(lid)
        client = PoliteClient()
        raw: dict | None = None
        try:
            try:
                # Shopify stores answer /products/<handle>.json with the whole product
                listing, raw = fetch_shopify(url, lid, client)
            except (FetchError, httpx.HTTPError, ValueError) as e:
                if isinstance(e, FetchError) and "robots.txt" in str(e):
                    raise
                listing = fetch_html_listing(url, lid, client)
            download_photos(listing, client)
        finally:
            client.close()
        if not any(p.local_path for p in listing.photos) and len(listing.body_text) < 40:
            raise FetchError("Couldn't read this page: it has no product text or photos.")
        from praman.anonymise import register_listing

        register_listing(listing)  # the store keeps one anonymised letter from now on
        save_cached(listing, raw)
        return listing
    if pasted_text:
        lid = "P" + hashlib.sha256(pasted_text.encode()).hexdigest()[:8]
        return Listing(
            id=lid,
            source="pasted",
            title=pasted_title,
            body_text=pasted_text.strip(),
            fetched_at=datetime.now(UTC),
        )
    raise FetchError("Give a listing ID, a product URL or pasted text")


# ---------------------------------------------------------------------------
# Tool: fetch_linked_page

CERT_NAMES = [
    "CPCB",
    "IS/ISO 17088",
    "ISO 17088",
    "EN 13432",
    "ASTM D6400",
    "ASTM D6868",
    "BPI",
    "TUV",
    "TÜV",
    "OK compost",
    "Seedling",
    "AS 4736",
    "AS 5810",
    "NF T51-800",
    "Ecocert",
    "COSMOS",
    "B Corp",
    "FSC",
    "GOTS",
    "OEKO-TEX",
    "USDA",
    "IFRA",
    "PETA",
    "Leaping Bunny",
    "FSSAI",
    "Green Seal",
    "Cradle to Cradle",
    "ISO 14001",
    "ISO 9001",
]


def find_cert_names(text: str) -> list[str]:
    found = []
    low = text.lower()
    for name in CERT_NAMES:
        if re.search(r"(?<![a-z])" + re.escape(name.lower()) + r"(?![a-z])", low):
            found.append(name)
    return found


def fetch_linked_page(url: str, listing: Listing, client: PoliteClient | None = None) -> dict:
    """Fetch a same-site page linked from the listing; returns text and certificate names found.

    Pages are cached in data/cache/pages/ so replay and offline modes work without the network.
    """
    if not listing.url or not same_site(url, listing.url):
        raise FetchError("Only links on the listing's own site are followed")
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    cached = ROOT / "data" / "cache" / "pages" / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    from praman.config import get_settings

    if get_settings().praman_llm_mode == "offline":
        raise FetchError("Linked page not in the cache (offline mode)")
    own = client is None
    client = client or PoliteClient()
    try:
        r = client.get(url)
    finally:
        if own:
            client.close()
    text = html_to_text(r.text)[:MAX_PAGE_CHARS]
    doc = {"url": url, "text": text, "certificates": find_cert_names(text)}
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    return doc
