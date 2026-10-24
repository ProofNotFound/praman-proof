"""check_material: when no certificate backs a claim, check whether the material named on the
product (its composition line or "made from …" text) has the claimed property, with a Groq
browser-search model call. Code decides when the check applies; plastics never qualify, because
the Plastic Waste Management Rules ask for a CPCB certificate whatever the material.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

from praman import llm
from praman.models import Claim, Listing, MaterialCheckOut, PhotoPrint
from praman.safety import careful
from praman.tools.text import sentences

# (property as searched, pattern in the claim or page)
# Tag-style claims ("Feature_Compostable") count too: the underscore is a word character, so the
# patterns use letter look-arounds instead of \b.
_L = r"(?<![A-Za-z])"
_R = r"(?![A-Za-z])"
PROPERTIES: list[tuple[str, re.Pattern[str]]] = [
    ("compostable", re.compile(_L + r"compostable" + _R, re.I)),
    ("biodegradable", re.compile(_L + r"bio-?\s?degradable" + _R, re.I)),
    ("recyclable", re.compile(_L + r"recyclable" + _R, re.I)),
    (
        "plastic-free",
        re.compile(
            _L + r"plastic[- _]?free" + _R + r"|" + _L + r"(?:0|zero)\s?%?\s?plastic" + _R, re.I
        ),
    ),
]
MATERIAL_RE = re.compile(
    r"\b(?:made\s+(?:from|of|with|using)|composition|materials?\s*[:\-]|ingredients?\s*[:\-]"
    r"|consists?\s+of|(?:paper|plant|wood|bamboo|fib(?:re|er)|starch|cotton|jute|pulp|leaf)[- ]based)\b",
    re.I,
)
# Any of these in the material lines means the product is (partly) plastic: CPCB rules apply
PLASTIC_RE = re.compile(
    r"\b(?:(?i:plastics?|bio-?plastics?|poly\w+|nylon|resin|acrylic|silicone|vinyl|foam"
    r"|non-?\s?woven|laminat\w*|microfib(?:re|er)s?|synthetic|spandex|elastane|lycra)"
    r"|PLA|PBAT|PBS|PHA|PET|PETE|PP|PE|HDPE|LDPE|PVC|EVA|PS)\b"
)
PLASTIC_FREE_RE = re.compile(
    r"\b(?:plastic[- ]?free|no\s+plastics?|(?:0|zero)\s?%?\s?plastic)\b", re.I
)
# "30% wheat straw": a blend whose other part isn't named
BLEND_RE = re.compile(r"\b(?:[1-9]\d?(?:\.\d+)?)\s?%")
PLASTIC_RULES = {"R07", "R09"}  # compostable / biodegradable plastic: registry only
NOT_MATERIAL_RULES = {"R05", "R06"}  # comparisons and future promises aren't about a material
MAX_LINES = 8


@dataclass
class MaterialLine:
    text: str
    where: str  # "description", "title" or "photo 3"
    photo_index: int | None = None
    box_2d: list[int] | None = None

    def numbered(self, n: int) -> str:
        return f"{n}. [{self.where}] {self.text}"


def claim_properties(claim: Claim, listing: Listing, claims: list[Claim]) -> list[str]:
    """The properties a claim relies on. A vague claim ("eco friendly") borrows the ones the page
    states elsewhere ("made from biodegradable paper")."""
    found = [name for name, pat in PROPERTIES if pat.search(claim.quote)]
    if found or claim.type != "vague":
        return found[:2]
    text = " ".join([listing.full_text()] + [c.quote for c in claims if c.is_claim])
    return [name for name, pat in PROPERTIES if pat.search(text)][:2]


def material_lines(listing: Listing, photo_print: PhotoPrint | None) -> list[MaterialLine]:
    """Composition print on the photos first (the pack's own words), then 'made from …' text."""
    out: list[MaterialLine] = []
    seen: set[str] = set()
    for idx, it in photo_print.all_items() if photo_print else []:
        key = it.text.strip().lower()
        if it.kind == "composition" and key not in seen:
            seen.add(key)
            out.append(MaterialLine(it.text.strip(), f"photo {idx}", idx, it.box_2d))
    for loc, s in sentences(listing):
        if MATERIAL_RE.search(s) and s.strip().lower() not in seen:
            seen.add(s.strip().lower())
            out.append(MaterialLine(s.strip(), loc))
    return out[:MAX_LINES]


def is_plastic(lines: list[MaterialLine]) -> bool:
    return any(PLASTIC_RE.search(PLASTIC_FREE_RE.sub(" ", ln.text)) for ln in lines)


def is_blend(lines: list[MaterialLine]) -> bool:
    return any(BLEND_RE.search(PLASTIC_FREE_RE.sub(" ", ln.text)) for ln in lines)


def applies(
    claim: Claim,
    rule_ids: list[str],
    lines: list[MaterialLine],
    props: list[str],
    claims: Sequence[Claim] = (),
) -> str:
    """'' when the check applies, else the reason it doesn't (for tests and the trace)."""
    if not claim.is_claim or claim.derived_from:
        return "not a product claim"
    if claim.type not in ("vague", "specific"):
        return "comparisons and future promises aren't about a material"
    if claim.scope not in ("product", "part"):
        return "the claim isn't about what the product itself is made of"
    if set(rule_ids) & (PLASTIC_RULES | NOT_MATERIAL_RULES):
        return "plastic or comparison rules apply"
    # A page whose claims fall under the plastic rules (e.g. starch-based compostable bags) sells
    # compostable plastic, whatever its material lines say: only the CPCB certificate counts
    if any(set(c.rule_ids) & PLASTIC_RULES for c in claims if c.is_claim):
        return "the page's claims fall under the plastic rules, which need a CPCB certificate"
    if not props:
        return "no material property claimed"
    if not lines:
        return "the listing doesn't name a material"
    if is_plastic(lines):
        return "the material includes plastic, which needs a CPCB certificate"
    if is_blend(lines):
        return "the material is a blend whose other part isn't named"
    return ""


def source_domains(out: MaterialCheckOut, limit: int = 3) -> list[str]:
    """Readable names for the sources: the site's domain (a search tool's links can be redirects
    whose title is the domain)."""
    names: list[str] = []
    for src in out.sources:
        host = urlparse(src.url).netloc
        name = (host if host and "vertexaisearch" not in host else src.title).strip()
        name = name.removeprefix("www.")
        if name and name not in names:
            names.append(name)
    return names[:limit]


def check_material(
    lines: list[MaterialLine],
    prop: str,
    listing: Listing,
    meter: llm.Meter | None = None,
) -> MaterialCheckOut:
    res = llm.call(
        "check_material",
        MaterialCheckOut,
        variables={
            "property": prop,
            "title": listing.title,
            "lines": "\n".join(ln.numbered(i) for i, ln in enumerate(lines, start=1)),
        },
        listing_id=listing.id,
        meter=meter,
    )
    out = res.data
    out.summary = careful(out.summary)
    out.caveat = careful(out.caveat) if out.caveat else None
    return out


def covers(out: MaterialCheckOut) -> str:
    """Code decides what the answer is worth: 'yes' needs at least one grounded source."""
    if out.answer == "yes":
        return "yes" if out.sources else "partly"
    return "partly" if out.answer == "partly" else "no"
