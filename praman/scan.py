"""Store scan (W3): rank a store's products by how much their green claims need checking.

Code only, zero model calls. For each product page it finds the claim terms of a rule pack
(the green-claims pack, data/rules.json, by default; any pack in data/rule_packs/ works the same
way, e.g. food labels) (vague terms under CCPA 5(a), specific terms such as compostable, biodegradable, plastic-free,
recyclable) and the proof signals a page can show (CPCB codes, named standards, certificate or
registration numbers, certifier names, certificate links), and scores what's left unproven.
It is triage, not a verdict: a high score means "check this page first", never that a claim is
unsupported.

Products come from Shopify's /products.json (at most 100) or, for other stores, product URLs in
sitemap.xml (at most 50), fetched with the same polite client as everything else.
"""

from __future__ import annotations

import html
import json
import logging
import re
import secrets
import threading
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from praman import anonymise, db
from praman.config import CACHE_DIR, get_settings
from praman.models import Listing
from praman.rules import (
    Rule,
    load_pack,
    load_rules,
    matched_terms,
    normalise,
    pack_names,
    plastic_context,
    term_in,
)
from praman.seeds import seed_for_url
from praman.tools.cpcb import find_codes
from praman.tools.fetch import FetchError, PoliteClient, html_to_text, same_site

log = logging.getLogger(__name__)

LABEL = "Triage, not a verdict"
MAX_SHOPIFY = 100
MAX_SITEMAP = 50
SCANS_CACHE = CACHE_DIR / "scans"
XML_TYPES = ("application/xml", "text/xml", "application/rss+xml", "text/plain")
PRODUCT_PATH_RE = re.compile(r"/(products?|p|item|shop)/[^/]+", re.I)

# Trigger terms that read as claims in a sentence but are everyday words in shop copy
# ("only ₹299", "free of charge", "will be delivered"); the agent still sees them in context.
TRIAGE_SKIP = {"only ", "first ", "free of", "free-of", "will be"}
WEAK_VAGUE = {"natural", "pure", "clean", "green", "conscious"}  # often not a claim at all
REGISTRY_RULES = {"R07", "R09"}  # compostable / biodegradable plastic: CPCB registration

STANDARDS = [
    "IS/ISO 17088", "ISO 17088", "EN 13432", "ASTM D6400", "ASTM D6868", "AS 4736", "AS 5810",
    "NF T51-800", "ISO 14021", "ISO 14024",
]  # fmt: skip
# Environmental certifiers; names that are also ordinary words need "certif…" nearby
CERTIFIERS = ["BPI", "TÜV", "TUV", "OK compost", "Ecocert", "FSC", "GOTS", "USDA Organic",
              "Jaivik Bharat", "India Organic", "NPOP", "PGS-India"]  # fmt: skip
CERTIFIERS_IN_CONTEXT = ["COSMOS", "Seedling", "Green Seal", "Cradle to Cradle", "CPCB"]
COMPANY_MARKS = ["B Corp", "ISO 14001"]
CERT_NO_RE = re.compile(
    r"\b(?:certificate|certification|registration|licen[cs]e|reg)\.?\s*(?:no|number|#)\.?\s*"
    r"[:\-]?\s*([A-Z0-9][A-Z0-9/\-.]{3,})",
    re.I,
)
CERT_LINK_RE = re.compile(r"certif|lab-?report|test-?report|/compliance", re.I)


class TriageTerm(BaseModel):
    term: str
    kind: Literal["vague", "specific", "comparative", "future"]
    rule_ids: list[str]
    weight: int
    snippet: str


class ProofSignal(BaseModel):
    kind: Literal[
        "cpcb_code", "standard", "certificate_number", "certifier", "company_mark",
        "certificate_link",
    ]  # fmt: skip
    text: str
    weight: int


class TriageRow(BaseModel):
    product: int  # position in the store's list (0-based); "Check this product" refers to it
    rank: int = 0
    title: str
    url: str
    score: int
    band: Literal["high", "medium", "low", "none"]
    terms: list[TriageTerm] = []
    proof: list[ProofSignal] = []
    reasons: list[str] = []
    listing_id: str | None = None  # a seed listing (it has a case file)
    error: str | None = None


class Scan(BaseModel):
    id: str
    status: Literal["running", "finished", "error"]
    store: str
    store_url: str
    source: Literal["shopify", "sitemap"] | None = None
    total: int = 0
    done: int = 0
    started_at: str
    finished_at: str | None = None
    message: str | None = None
    label: str = LABEL
    model_calls: int = 0
    pack: str = "green_claims"  # the rule pack the pages were triaged with
    rows: list[TriageRow] = []


# ---------------------------------------------------------------------------
# Triage: plain code over the page text


def _snippet(text: str, term: str, limit: int = 110) -> str:
    for line in re.split(r"(?<=[.!?])\s+|\n", text):
        if term_in(term, line):
            line = " ".join(line.split())
            if len(line) <= limit:
                return line
            i = normalise(line).find(term.strip().lower())
            start = max(0, min(i - limit // 3, len(line) - limit))
            cut = line[start : start + limit].strip()
            return ("…" if start else "") + cut + ("…" if start + limit < len(line) else "")
    return term


def claim_terms(listing: Listing, rules: dict[str, Rule] | None = None) -> list[TriageTerm]:
    """Claim terms from the rules found in the title, description and tags, one per term."""
    text = listing.full_text()
    plastic = plastic_context(listing)
    found: dict[str, TriageTerm] = {}
    for rule in (rules or load_rules()).values():
        t = rule.triggers
        if not t.terms or t.cross_cutting or t.classifier or rule.id == "R10":
            continue
        if t.requires_plastic_context and not plastic:
            continue
        kind = t.claim_types[0]
        for term in matched_terms(rule, text):
            if term in TRIAGE_SKIP:
                continue
            if term == "by 20" and not re.search(r"(?<![a-z0-9])by 20\d\d", normalise(text)):
                continue
            canon = re.sub(r"[\s\-]", "", term.strip().lower())
            if rule.id in REGISTRY_RULES:
                weight = 4
            elif kind == "specific":
                weight = 3
            elif kind == "vague" and canon in WEAK_VAGUE:
                weight = 1
            else:
                weight = 2
            hit = found.get(canon)
            if hit:
                hit.rule_ids = list(dict.fromkeys(hit.rule_ids + [rule.id]))
                hit.weight = max(hit.weight, weight)
                continue
            found[canon] = TriageTerm(
                term=term.strip(),
                kind=kind,  # type: ignore[arg-type]
                rule_ids=[rule.id],
                weight=weight,
                snippet=_snippet(text, term),
            )
    return sorted(found.values(), key=lambda x: (-x.weight, x.term))


def _near_certif(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 40) : end + 40].lower()
    return "certif" in window


def proof_signals(listing: Listing) -> list[ProofSignal]:
    """What on the page could be proof: codes, standards, numbers, certifiers, links."""
    text = listing.full_text()
    out: list[ProofSignal] = []
    for code in find_codes(text):
        out.append(ProofSignal(kind="cpcb_code", text=code, weight=3))
    named = [s for s in STANDARDS if re.search(re.escape(s), text, re.I)]
    for s in named:
        if s == "ISO 17088" and "IS/ISO 17088" in named:
            continue
        out.append(ProofSignal(kind="standard", text=s, weight=3))
    for m in CERT_NO_RE.finditer(text):
        if any(m.group(1) in p.text for p in out):
            continue  # a CPCB code already counted
        out.append(ProofSignal(kind="certificate_number", text=m.group(0).strip(), weight=3))
    for name in CERTIFIERS + CERTIFIERS_IN_CONTEXT:
        for m in re.finditer(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", text, re.I):
            if name in CERTIFIERS_IN_CONTEXT and not _near_certif(text, m.start(), m.end()):
                continue
            if name == "CPCB" and any(p.kind == "cpcb_code" for p in out):
                break
            out.append(ProofSignal(kind="certifier", text=name, weight=2))
            break
    for name in COMPANY_MARKS:
        if re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", text, re.I):
            out.append(ProofSignal(kind="company_mark", text=name, weight=1))
    for link in listing.links:
        if CERT_LINK_RE.search(urlparse(link).path):
            out.append(ProofSignal(kind="certificate_link", text=urlparse(link).path, weight=1))
            break
    return out


PROOF_WORDS = {
    "cpcb_code": "prints CPCB code",
    "standard": "names the standard",
    "certificate_number": "gives a certificate or registration number:",
    "certifier": "names the certifier",
    "company_mark": "shows a company-level mark",
    "certificate_link": "links to a certificates page",
}
KIND_WORDS = {
    "vague": "vague",
    "specific": "specific",
    "comparative": "comparison",
    "future": "future promise",
}


def band_for(score: int, has_terms: bool) -> Literal["high", "medium", "low", "none"]:
    if not has_terms:
        return "none"
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def triage(listing: Listing, product: int = 0, pack: str = "green_claims") -> TriageRow:
    """Score one product page: claim terms add weight, proof signals take it away (floor 0)."""
    rules = load_pack(pack)[1]
    terms = claim_terms(listing, rules)
    proof = proof_signals(listing) if terms else []
    need = sum(t.weight for t in terms)
    score = max(0, need - sum(p.weight for p in proof))
    reasons = []
    for t in terms[:4]:
        rid = next((r for r in t.rule_ids if r in REGISTRY_RULES), t.rule_ids[0])
        reasons.append(f"“{t.term}” ({KIND_WORDS[t.kind]}) · {rid}: {rules[rid].name}")
    if len(terms) > 4:
        reasons.append(f"+{len(terms) - 4} more claim terms")
    for p in proof:
        reasons.append(f"Proof signal: {PROOF_WORDS[p.kind]} {p.text} (−{p.weight})")
    if not terms:
        reasons.append("No claim terms from the rules in the title, description or tags.")
    return TriageRow(
        product=product,
        title=listing.title,
        url=listing.url or "",
        score=score,
        band=band_for(score, bool(terms)),
        terms=terms,
        proof=proof,
        reasons=reasons,
        listing_id=seed_for_url(listing.url) if listing.url else None,
    )


def rank(rows: list[TriageRow]) -> list[TriageRow]:
    ordered = sorted(
        rows,
        key=lambda r: (
            r.error is not None,
            -r.score,
            -max((t.weight for t in r.terms), default=0),
            r.title.lower(),
        ),
    )
    for i, r in enumerate(ordered, start=1):
        r.rank = i
    return ordered


# ---------------------------------------------------------------------------
# Finding a store's products


def shopify_listing(product: dict, base: str) -> Listing:
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    body_html = product.get("body_html") or ""
    from praman.tools.fetch import extract_links

    url = f"{base}/products/{product.get('handle', '')}"
    return Listing(
        id="scan",
        source="shopify_json",
        url=url,
        store=urlparse(base).netloc.lower().removeprefix("www."),
        title=(product.get("title") or "").strip(),
        body_text=html_to_text(body_html),
        tags=tags,
        fetched_at=datetime.now(UTC),
        product_type=product.get("product_type") or "",
        vendor=product.get("vendor") or "",
        links=extract_links(body_html, url),
    )


def _cache_file(host: str):
    return SCANS_CACHE / f"{host}.products.json"


def shopify_products(client: PoliteClient, base: str, offline: bool) -> list[dict] | None:
    """Up to 100 products from /products.json, or None when the store doesn't answer it."""
    host = urlparse(base).netloc.lower().removeprefix("www.")
    cached = _cache_file(host)
    if offline:
        return json.loads(cached.read_text())[:MAX_SHOPIFY] if cached.exists() else None
    try:
        r = client.get(f"{base}/products.json?limit={MAX_SHOPIFY}")
        data = r.json()
    except (FetchError, httpx.HTTPError, ValueError):
        return None
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list) or not products:
        return None
    products = [p for p in products if isinstance(p, dict) and p.get("handle")][:MAX_SHOPIFY]
    SCANS_CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(products, ensure_ascii=False))
    return products


def _locs(xml: str) -> list[str]:
    return [html.unescape(x.strip()) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml, re.S)]


def sitemap_product_urls(client: PoliteClient, base: str) -> list[str]:
    """Product page URLs (same site) from robots.txt's Sitemap lines or /sitemap.xml."""
    client.allowed(base + "/")  # loads robots.txt once
    rp = client._robots.get(urlparse(base).netloc)
    maps = list((rp.site_maps() if rp else None) or []) or [f"{base}/sitemap.xml"]
    maps = [m for m in maps if same_site(m, base)][:3]
    urls: list[str] = []
    seen_maps: set[str] = set()
    while maps and len(seen_maps) < 6:
        m = maps.pop(0)
        if m in seen_maps:
            continue
        seen_maps.add(m)
        try:
            _, xml = client.get_page(m, types=XML_TYPES)
        except (FetchError, httpx.HTTPError):
            continue
        locs = _locs(xml)
        if "<sitemapindex" in xml:
            children = [u for u in locs if same_site(u, base)]
            children.sort(key=lambda u: "product" not in u.lower())  # product sitemaps first
            maps = children[:3] + maps
            continue
        for u in locs:
            if same_site(u, base) and PRODUCT_PATH_RE.search(urlparse(u).path) and u not in urls:
                urls.append(u)
        if len(urls) >= MAX_SITEMAP:
            break
    return urls[:MAX_SITEMAP]


# ---------------------------------------------------------------------------
# Storage and the background job


def _save(scan: Scan) -> None:
    db.execute(
        "INSERT OR REPLACE INTO scans (id, store, store_url, status, source, total, done, "
        "started_at, finished_at, message, rows_json, pack) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            scan.id,
            scan.store,
            scan.store_url,
            scan.status,
            scan.source,
            scan.total,
            scan.done,
            scan.started_at,
            scan.finished_at,
            scan.message,
            json.dumps([r.model_dump() for r in scan.rows], ensure_ascii=False),
            scan.pack,
        ),
    )


def get_scan(scan_id: str) -> Scan | None:
    row = db.query_one("SELECT * FROM scans WHERE id = ?", (scan_id,))
    if not row:
        return None
    rows = [TriageRow.model_validate(r) for r in json.loads(row["rows_json"] or "[]")]
    return Scan(
        id=row["id"],
        status=row["status"],
        store=row["store"],
        store_url=row["store_url"],
        source=row["source"],
        total=row["total"] or 0,
        done=row["done"] or 0,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        message=row["message"],
        pack=row.get("pack") or "green_claims",
        rows=rows,
    )


def store_base(url: str) -> str:
    """https://host of a store URL (any path is ignored); http(s) only."""
    url = url.strip()
    parts = urlparse(url if "://" in url else "https://" + url)
    if parts.scheme not in ("http", "https") or "." not in parts.netloc:
        raise ValueError("Enter a store address that starts with http:// or https://.")
    return f"{parts.scheme}://{parts.netloc.lower()}"


def new_scan(store_url: str, pack: str = "green_claims") -> Scan:
    base = store_base(store_url)
    if pack not in pack_names():
        raise ValueError(f"There is no rule pack called {pack!r}.")
    scan = Scan(
        pack=pack,
        id="S" + secrets.token_hex(4),
        status="running",
        store=urlparse(base).netloc.removeprefix("www."),
        store_url=base,
        started_at=datetime.now(UTC).isoformat(),
    )
    anonymise.register(scan.store)
    _save(scan)
    return scan


_lock = threading.Lock()


def run_scan(scan: Scan, client: PoliteClient | None = None) -> Scan:
    """Find the store's products, triage each, rank them. Never raises: errors end the scan
    with a plain message."""
    own = client is None
    client = client or PoliteClient()
    offline = get_settings().praman_llm_mode == "offline"
    rows: list[TriageRow] = []
    try:
        products = shopify_products(client, scan.store_url, offline)
        if products is not None:
            scan.source, scan.total = "shopify", len(products)
            _save(scan)
            for i, p in enumerate(products):
                lst = shopify_listing(p, scan.store_url)
                if lst.vendor:
                    anonymise.register(scan.store, [lst.vendor])
                rows.append(triage(lst, i, scan.pack))
                scan.done = i + 1
            scan.rows = rank(rows)
        elif offline:
            raise FetchError(
                "Store scans need the network, and this server is in offline mode. "
                "Start it in replay or live mode."
            )
        else:
            urls = sitemap_product_urls(client, scan.store_url)
            if not urls:
                raise FetchError(
                    "Couldn't find this store's products: it has no /products.json and no "
                    "product pages in its sitemap."
                )
            scan.source, scan.total = "sitemap", len(urls)
            _save(scan)
            from praman.tools.page import PageError, parse_product_html

            for i, u in enumerate(urls):
                try:
                    _, page = client.get_page(u)
                    lst = parse_product_html(page, u, "scan")
                    if lst.vendor:
                        anonymise.register(scan.store, [lst.vendor])
                    rows.append(triage(lst, i, scan.pack))
                except (FetchError, PageError, httpx.HTTPError) as e:
                    rows.append(
                        TriageRow(
                            product=i,
                            title=urlparse(u).path.rsplit("/", 1)[-1] or u,
                            url=u,
                            score=0,
                            band="none",
                            reasons=["Couldn't read this page, so it wasn't triaged."],
                            error=str(e)[:200],
                        )
                    )
                scan.done = i + 1
                if scan.done % 5 == 0:
                    scan.rows = rank(list(rows))
                    _save(scan)
            scan.rows = rank(rows)
        scan.status = "finished"
        n = sum(1 for r in scan.rows if r.band in ("high", "medium"))
        scan.message = f"{scan.total} products triaged; {n} to check first or soon. {LABEL}."
    except FetchError as e:
        scan.status, scan.message = "error", str(e)
    except Exception as e:  # noqa: BLE001 - the scan ends with a message, never a crash
        log.exception("scan %s failed", scan.id)
        scan.status, scan.message = (
            "error",
            f"The scan stopped on an internal error ({type(e).__name__}).",
        )
    finally:
        if own:
            client.close()
    scan.finished_at = datetime.now(UTC).isoformat()
    with _lock:
        _save(scan)
    return scan


def public(scan: Scan) -> dict:
    """The scan as the API returns it: ranked rows, anonymised when the mode is on."""
    data = scan.model_dump()
    data["rows"] = sorted(data["rows"], key=lambda r: r["rank"] or 10**6)
    return anonymise.maybe_mask(data)
