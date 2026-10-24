"""search_text (TRD §7): regex finds candidate proof in the page text; the judge rules on it."""

from __future__ import annotations

import re

from praman.models import Claim, Listing
from praman.rules import get_rule, primary_rules
from praman.tools.cpcb import CODE_RE
from praman.tools.judge import CERT_SCOPES, Candidate

MAX_CANDIDATES = 8

KIND_PATTERNS: dict[str, list[str]] = {
    "certification": [
        r"certif(ied|icate|ication)",
        r"accredit",
        r"approved by",
        r"\bmark(ed)?\b",
    ]
    + [r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])" for n, _, _, env in CERT_SCOPES if env],
    "scientific_evidence": [
        r"\btest(ed|s|ing)?\b",
        r"\blab(oratory)?\b",
        r"\bstandards?\b",
        r"\b(is|iso|en|astm)\s?[/\d]",
        r"\bas per\b",
        r"\bstudy\b",
    ],
    "registry_match": [CODE_RE.pattern, r"\bcpcb\b", r"manufactured by", r"registration"],
    "disclosure_link": [r"https?://", r"www\.", r"\bqr\b", r"\bscan\b", r"view our", r"learn more"],
    "comparison_data": [
        r"\d+\s?%",
        r"\d+\s?x\b",
        r"compared",
        r"\bthan\b",
        r"per ton",
        r"\bvs\.?\b",
    ],
    "plan": [r"\bby 20\d\d\b", r"roadmap", r"\btarget", r"\bmilestone"],
}


def sentences(listing: Listing) -> list[tuple[str, str]]:
    """(location, sentence) pairs from the title and description."""
    out = [("title", listing.title)]
    for line in listing.body_text.splitlines():
        line = line.strip(" •\t")
        if not line:
            continue
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line):
            if len(s.strip()) > 2:
                out.append(("description", s.strip()))
    return out


def label_patterns(rule_ids: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for rule in primary_rules(rule_ids):
        for req in rule.required_evidence:
            if req.kind == "label_text" and req.pattern:
                out.append((rule.id, re.compile(req.pattern, re.I)))
    return out


def wanted_kinds(rule_ids: list[str]) -> set[str]:
    kinds: set[str] = set()
    for rule in primary_rules(rule_ids):
        for req in rule.required_evidence:
            kinds.update(req.kinds())
    if "R10" in rule_ids:
        kinds.add("certification")
    return kinds


def text_candidates(claim: Claim, rule_ids: list[str], listing: Listing) -> list[Candidate]:
    """Sentences that might hold proof of a kind the claim's rules need."""
    kinds = wanted_kinds(rule_ids)
    labels = label_patterns(rule_ids)
    cands: list[Candidate] = []
    seen: set[str] = set()

    def add(text: str, loc: str, hint: str) -> None:
        key = text.lower()
        if key not in seen and len(cands) < MAX_CANDIDATES:
            seen.add(key)
            cands.append(Candidate(text=text, source="text", location=loc, hint=hint))

    for loc, s in sentences(listing):
        low = s.lower()
        for _, pat in labels:
            if pat.search(s):
                add(s, loc, "label_text")
        for kind in (
            "certification",
            "scientific_evidence",
            "registry_match",
            "disclosure_link",
            "plan",
        ):
            if kind in kinds and any(re.search(p, low) for p in KIND_PATTERNS[kind]):
                add(s, loc, kind)
        if (
            "comparison_data" in kinds
            and claim.type == "comparative"
            and any(re.search(p, low) for p in KIND_PATTERNS["comparison_data"])
        ):
            add(s, loc, "comparison_data")
        # A qualifier for a vague claim usually sits in the claim's own sentence
        if (
            "qualifier" in kinds
            and claim.normalised[:40] in re.sub(r"\s+", " ", low)
            and len(s) > len(claim.quote) + 15
        ):
            add(s, loc, "qualifier")
    for url in listing.links:
        if "disclosure_link" in kinds or "certification" in kinds:
            add(f"Link on the page: {url}", "description", "disclosure_link")
    return cands


def label_found(rule_ids: list[str], texts: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """(rule_id, location, text) for every required label pattern found in the given texts."""
    hits = []
    for rid, pat in label_patterns(rule_ids):
        for loc, t in texts:
            if pat.search(t):
                hits.append((rid, loc, t))
    return hits


def label_rule_ids(rule_ids: list[str]) -> list[str]:
    return [
        r.id
        for r in primary_rules(rule_ids)
        if any(q.kind == "label_text" for q in r.required_evidence)
    ]


def label_desc(rule_id: str) -> str:
    for req in get_rule(rule_id).required_evidence:
        if req.kind == "label_text":
            return req.desc
    return ""
