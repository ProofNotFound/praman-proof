"""The seed listings (data/listings_seed.csv) and which of them a URL names."""

from __future__ import annotations

import csv
import re
from urllib.parse import urlparse

from praman import anonymise
from praman.config import SEED_PATH

ANON_HOST_RE = re.compile(r"brand-([a-z]+)\.example")
HANDLE_RE = re.compile(r"/products/([^/?#]+?)(?:\.json)?/?$")


def seed_rows() -> list[dict[str, str]]:
    return list(csv.DictReader(SEED_PATH.open()))


def url_handle(url: str) -> tuple[str, str | None]:
    """(host without www, product handle or None) of a URL; a bare domain gets https://."""
    parts = urlparse(url if "://" in url else "https://" + url)
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    m = HANDLE_RE.search(parts.path)
    return host, (m.group(1).lower() if m else None)


def seed_for_url(url: str) -> str | None:
    """The seed listing a URL names: its real store URL, or the anonymised domain the app shows
    ("brand-d.example/products/<handle>"). None when it names no single seed listing."""
    host, handle = url_handle(url)
    rows = seed_rows()
    if am := ANON_HOST_RE.fullmatch(host):
        letter = am.group(1).upper()
        cands = [r for r in rows if anonymise.brand_letter(r["id"]) == letter]
    else:
        cands = [r for r in rows if r["store"].strip().lower().removeprefix("www.") == host]
    if handle:
        cands = [r for r in cands if r["handle"].strip().lower() == handle]
    return cands[0]["id"] if len(cands) == 1 else None
