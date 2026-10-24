"""check_consistency (TRD §7): conflicts between claims and the listing's own facts.

Two layers: rule contradiction signals from data/rules.json, decided in code, and a model pass
for conflicts no rule names (numbers, materials, scope). Model conflicts must quote the listing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from praman import llm
from praman.models import CheckConsistencyOut, Claim, Listing, PhotoPrint
from praman.rules import Rule, load_rules, normalise, term_in
from praman.safety import careful
from praman.tools.claims import find_span
from praman.tools.text import sentences


@dataclass
class Conflict:
    claim_id: str
    quote: str  # the conflicting words
    where: str  # "description" | "photo:3" | …
    explanation: str
    rule_id: str | None = None
    photo_index: int | None = None
    box_2d: list[int] | None = None
    other_claim_id: str | None = None


def _signal(rule: Rule, text: str) -> str | None:
    for s in rule.contradiction_signals:
        if term_in(s, text):
            return s
    return None


# Claims that a product is free of plastic, and materials that are plastics. Checked in code.
PLASTIC_FREE_TERMS = ["plastic-free", "plastic free", "zero plastic", "0% plastic", "no plastic"]
PLASTIC_MATERIALS = [
    "nylon", "polyester", "polyethylene", "polypropylene", "pvc", "acrylic", "ldpe", "hdpe",
    "pe virgin", "polymer", "bioplastic", "pla", "pbat",
]  # fmt: skip
PLASTIC_FREE_NOTE = (
    "The listing names a plastic material, which conflicts with a plastic-free claim."
)


def fact_lines(
    listing: Listing, photo_print: PhotoPrint | None, claims: list[Claim]
) -> list[tuple[str, str, int | None, list[int] | None]]:
    """Statements of fact: description clauses that carry no claim, and photo print that isn't a
    printed claim. Titles and tags are names and labels, not facts, so they're left out."""
    quotes = [c.normalised for c in claims]
    out: list[tuple[str, str, int | None, list[int] | None]] = []
    for loc, s in sentences(listing):
        if loc != "description":
            continue
        for clause in re.split(r",\s+|;\s+|\s+[-–—]\s+", s):
            clause = clause.strip(" .")
            nc = normalise(clause)
            if len(nc) < 4 or any(q and (q in nc or nc in q) for q in quotes):
                continue
            out.append((loc, clause, None, None))
    if photo_print:
        for idx, it in photo_print.all_items():
            if it.kind != "claim":
                out.append((f"photo:{idx}", it.text, idx, it.box_2d))
    return out


def _plastic_free_conflicts(
    claim: Claim, facts: list[tuple[str, str, int | None, list[int] | None]]
) -> list[Conflict]:
    if not any(term_in(t, claim.quote) for t in PLASTIC_FREE_TERMS):
        return []
    out = []
    for loc, text, pidx, box in facts:
        if any(term_in(m, text) for m in PLASTIC_MATERIALS):
            out.append(
                Conflict(
                    claim_id=claim.id,
                    quote=text,
                    where=loc,
                    explanation=PLASTIC_FREE_NOTE,
                    rule_id="R02",
                    photo_index=pidx,
                    box_2d=box,
                )
            )
            break  # one conflicting fact is enough
    return out


def rule_conflicts(
    claim: Claim,
    claims: list[Claim],
    listing: Listing,
    photo_print: PhotoPrint | None,
    sources: set[str],
) -> list[Conflict]:
    """Code-decided conflicts for one claim, using only the sources searched so far."""
    if not claim.is_claim:
        return []
    facts = [
        f
        for f in fact_lines(listing, photo_print, claims)
        if ("photos" in sources if f[0].startswith("photo") else "text" in sources)
    ]
    out: list[Conflict] = _plastic_free_conflicts(claim, facts)
    for rule in load_rules().values():
        if not rule.contradiction_signals:
            continue
        if rule.contradiction_target == "signal_claim":
            # This claim says something the rule rules out for another claim's product
            anchors = [
                c for c in claims if c.is_claim and c.id != claim.id and rule.id in c.rule_ids
            ]
            sig = _signal(rule, claim.quote)
            if anchors and sig:
                a = anchors[0]
                out.append(
                    Conflict(
                        claim_id=claim.id,
                        quote=a.quote,
                        where=a.location,
                        explanation=rule.contradiction_note
                        or f'"{sig}" conflicts with {rule.name.lower()}.',
                        rule_id=rule.id,
                        other_claim_id=a.id,
                    )
                )
        elif rule.id in claim.rule_ids:
            # Facts on the listing rule out this claim
            for loc, text, pidx, box in facts:
                if _signal(rule, text):
                    out.append(
                        Conflict(
                            claim_id=claim.id,
                            quote=text,
                            where=loc,
                            explanation=rule.contradiction_note
                            or f"Conflicts with {rule.name.lower()}.",
                            rule_id=rule.id,
                            photo_index=pidx,
                            box_2d=box,
                        )
                    )
    return out


def _photo_lines(photo_print: PhotoPrint | None) -> str:
    if not photo_print or not photo_print.all_items():
        return "(no photos read)"
    return "\n".join(f"[photo {i}] {it.text}" for i, it in photo_print.all_items())


def _locate_quote(quote: str, listing: Listing, photo_print: PhotoPrint | None):
    places = [("title", listing.title, None, None), ("description", listing.body_text, None, None)]
    places += [("tag", t, None, None) for t in listing.tags]
    if photo_print:
        places += [(f"photo:{i}", it.text, i, it.box_2d) for i, it in photo_print.all_items()]
    for loc, text, pidx, box in places:
        span = find_span(quote, text)
        if span:
            return span, loc, pidx, box
    return None


# A conflict must come from the listing's own words. An explanation that leans on how a material
# "typically" or "usually" behaves is the model's general knowledge, not evidence, so it's dropped.
OUTSIDE_KNOWLEDGE = re.compile(
    r"\b(typically|usually|generally|commonly|often|normally|tends? to|in general)\b", re.I
)


def model_conflicts(
    listing: Listing,
    photo_print: PhotoPrint | None,
    claims: list[Claim],
    known: list[Conflict],
    meter: llm.Meter | None,
) -> list[Conflict]:
    real = [c for c in claims if c.is_claim and not c.derived_from]
    if not real:
        return []
    claim_lines = "\n".join(
        f'{c.id} ({c.type}, {c.scope}, {c.location}): "{c.quote}"' for c in real
    )
    known_lines = (
        "\n".join(f'{k.claim_id}: "{k.quote}" ({k.rule_id})' for k in known) if known else "(none)"
    )
    res = llm.call(
        "check_consistency",
        CheckConsistencyOut,
        variables={
            "title": listing.title,
            "body": listing.body_text or "(empty)",
            "tags": ", ".join(listing.tags) or "(none)",
            "photo_print": _photo_lines(photo_print),
            "claims": claim_lines,
            "known": known_lines,
        },
        listing_id=listing.id,
        meter=meter,
    )
    ids = {c.id: c for c in real}
    out: list[Conflict] = []
    for cf in res.data.conflicts:
        claim = ids.get(cf.claim_id)
        if not claim:
            continue
        found = _locate_quote(cf.conflicting_quote, listing, photo_print)
        if not found:
            continue  # evidence or nothing: the conflict must quote the listing
        span, loc, pidx, box = found
        if normalise(span) == claim.normalised or normalise(span) in claim.normalised:
            continue  # a claim can't conflict with itself
        if OUTSIDE_KNOWLEDGE.search(cf.explanation):
            continue  # evidence or nothing: general knowledge about a material isn't evidence
        if any(
            k.claim_id == claim.id and normalise(k.quote) == normalise(span) for k in known + out
        ):
            continue
        out.append(
            Conflict(
                claim_id=claim.id,
                quote=span,
                where=loc,
                explanation=careful(cf.explanation),
                photo_index=pidx,
                box_2d=box,
            )
        )
    return out
