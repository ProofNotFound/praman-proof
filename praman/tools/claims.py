"""extract_claims (TRD §7): list environmental claims with exact quotes, type, scope and location."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from praman import llm
from praman.models import Claim, ExtractClaimsOut, Listing, LLMClaim, PhotoPrint
from praman.rules import load_rules, matched_terms, normalise
from praman.safety import has_banned

MAX_PHOTO_CLAIMS = 3


def _squash(text: str) -> tuple[str, list[int]]:
    """Lowercase, collapse whitespace; return the text and a map back to original offsets."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space or not out:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            idx.append(i)
            prev_space = False
    return "".join(out), idx


def find_span(quote: str, text: str, min_score: float = 90.0) -> str | None:
    """The exact substring of `text` that best matches `quote`, or None."""
    if not quote.strip() or not text.strip():
        return None
    q, _ = _squash(quote.strip())
    t, idx = _squash(text)
    pos = t.find(q)
    if pos >= 0:
        end = pos + len(q)
    else:
        al = fuzz.partial_ratio_alignment(q, t)
        if al is None or al.score < min_score or al.dest_end <= al.dest_start:
            return None
        pos, end = al.dest_start, al.dest_end
    return text[idx[pos] : idx[end - 1] + 1].strip(" ,;:")


def locate(quote: str, location: str, listing: Listing, photo_print: PhotoPrint | None):
    """Return (exact quote, location) checked against the listing, or None if it isn't there."""
    places: list[tuple[str, str]] = [("title", listing.title), ("description", listing.body_text)]
    places += [("tag", t) for t in listing.tags]
    places += [(f"photo:{p.index}", p.alt) for p in listing.photos if p.alt]
    if photo_print:
        places += [(f"photo:{i}", it.text) for i, it in photo_print.all_items()]
    # Prefer the location the model named
    places.sort(key=lambda p: 0 if p[0] == location or location.startswith(p[0]) else 1)
    for loc, text in places:
        span = find_span(quote, text)
        if span:
            return span, loc
    return None


def _alt_section(listing: Listing) -> str:
    """Photo alt text: shoppers using screen readers and search engines see it."""
    alts = []
    seen: set[str] = set()
    for p in listing.photos:
        alt = p.alt.strip()
        if alt and normalise(alt) not in seen and normalise(alt) != normalise(listing.title):
            seen.add(normalise(alt))
            alts.append(f"[photo {p.index}] {alt}")
    if not alts:
        return ""
    return "\nPhoto descriptions (alt text):\n" + "\n".join(alts) + "\n"


def _photo_section(listing: Listing, photo_print: PhotoPrint | None) -> tuple[str, str]:
    section = _alt_section(listing)
    if photo_print and photo_print.all_items():
        lines = "\n".join(f"[photo {i}] {it.text}" for i, it in photo_print.all_items())
        section += f'\nText printed on the product photos:\n"""\n{lines}\n"""\n'
    if not section:
        return "", ""
    return section, ', or "photo:N" for a photo description or text printed on photo N'


MAX_CLAIMS = 8
MAX_NOT_CLAIMS = 4


def _dedupe(items: list[LLMClaim]) -> list[LLMClaim]:
    """Drop a claim already contained in a longer claim with the same trigger terms
    ("Zero waste" inside "Zero waste oral care"), then cap the list (model budget, TRD §8.1)."""
    keep: list[LLMClaim] = []
    for c in items:
        nc = normalise(c.quote)
        tc = _terms(c.quote)
        covered = any(
            o is not c
            and o.is_claim == c.is_claim
            and nc in normalise(o.quote)
            and len(normalise(o.quote)) > len(nc)
            and tc <= _terms(o.quote)
            for o in items
        )
        if not covered:
            keep.append(c)
    # Over the cap, keep claims that carry a trigger term first, specific before vague
    ranked = sorted(
        (c for c in keep if c.is_claim),
        key=lambda c: (0 if _terms(c.quote) else 1, 0 if c.type == "specific" else 1),
    )
    real = {id(c) for c in ranked[:MAX_CLAIMS]}
    not_claims = {id(c) for c in [c for c in keep if not c.is_claim][:MAX_NOT_CLAIMS]}
    return [c for c in keep if id(c) in real or id(c) in not_claims]


def extract_claims(
    listing: Listing,
    photo_print: PhotoPrint | None = None,
    meter: llm.Meter | None = None,
) -> tuple[list[Claim], list[str]]:
    """Claims in listing order, plus notes about quotes that couldn't be found (dropped)."""
    section, hint = _photo_section(listing, photo_print)
    res = llm.call(
        "extract_claims",
        ExtractClaimsOut,
        variables={
            "title": listing.title,
            "body": listing.body_text or "(empty)",
            "tags": ", ".join(listing.tags) or "(none)",
            "photo_section": section,
            "photo_location_hint": hint,
        },
        listing_id=listing.id,
        meter=meter,
    )
    claims: list[Claim] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for c in _dedupe(res.data.claims):
        found = locate(c.quote, c.location, listing, photo_print)
        if not found:
            dropped.append(c.quote)
            continue
        quote, loc = found
        key = normalise(quote)
        if key in seen:
            continue
        if not c.is_claim and has_banned(quote):
            continue  # not a claim anyway; keeps careful-language checks simple
        seen.add(key)
        claims.append(
            Claim(
                id=f"C{len(claims) + 1}",
                quote=quote,
                normalised=key,
                type=c.type,
                scope=c.scope,
                location=loc,
                is_claim=c.is_claim,
                not_claim_reason=None
                if c.is_claim
                else (c.not_claim_reason or "Not an environmental claim about this product"),
            )
        )
    return claims, dropped


def _terms(text: str) -> set[str]:
    out: set[str] = set()
    for rule in load_rules().values():
        out.update(normalise(t) for t in matched_terms(rule, text))
    return out


def claims_from_photos(
    photo_print: PhotoPrint, existing: list[Claim], listing: Listing
) -> list[Claim]:
    """New claims printed only on photos (kind "claim") that carry a green trigger term.

    Skips anything already covered: same text, or no trigger term beyond those of an existing
    claim. At most MAX_PHOTO_CLAIMS, specific claims first.
    """
    known_terms = [_terms(c.quote) for c in existing if c.is_claim]
    known_text = [c.normalised for c in existing]
    picked: list[tuple[int, int, str, str, str]] = []
    for photo_idx, it in photo_print.all_items():
        if it.kind != "claim":
            continue
        text = re.sub(r"\s+", " ", it.text).strip()
        if text.endswith(":"):
            continue  # a heading such as "GREEN CREDS:", not a claim
        terms = _terms(text)
        if not terms:
            continue
        norm = normalise(text)
        if any(fuzz.ratio(norm, k) >= 85 for k in known_text):
            continue
        if any(terms <= kt for kt in known_terms):
            continue
        ctype = it.claim_type or ("specific" if _is_specific(terms) else "vague")
        known_terms.append(terms)
        known_text.append(norm)
        picked.append(
            (0 if ctype == "specific" else 1, photo_idx, text, ctype, it.scope or "product")
        )
    picked.sort(key=lambda p: p[0])
    out: list[Claim] = []
    for _, photo_idx, text, ctype, scope in picked[:MAX_PHOTO_CLAIMS]:
        out.append(
            Claim(
                id=f"C{len(existing) + len(out) + 1}",
                quote=text,
                normalised=normalise(text),
                type=ctype,  # type: ignore[arg-type]
                scope=scope,  # type: ignore[arg-type]
                location=f"photo:{photo_idx}",
            )
        )
    return out


def _is_specific(terms: set[str]) -> bool:
    r02 = {normalise(t) for t in load_rules()["R02"].triggers.terms}
    return bool(terms & r02)
