"""Judge candidate evidence for one claim: the model reads, code decides certificate scope."""

from __future__ import annotations

import re
from dataclasses import dataclass

from praman import llm
from praman.models import Claim, EvidenceJudgement, JudgeEvidenceOut, Listing
from praman.rules import get_rule, primary_rules
from praman.safety import careful

# Certificate scope is decided in code (CLAUDE.md rule 4). Longest names first.
# (needle, name, scope, environmental): non-environmental approvals (safety, food, cruelty-free)
# are never proof for an environmental claim, not even partial proof.
CERT_SCOPES: list[tuple[str, str, str, bool]] = [
    ("certified b corporation", "B Corp", "company", True),
    ("b corporation", "B Corp", "company", True),
    ("b corp", "B Corp", "company", True),
    ("is/iso 17088", "IS/ISO 17088", "material", True),
    ("iso 17088", "ISO 17088", "material", True),
    ("en 13432", "EN 13432", "material", True),
    ("astm d6400", "ASTM D6400", "material", True),
    ("astm d6868", "ASTM D6868", "material", True),
    ("as 4736", "AS 4736", "material", True),
    ("as 5810", "AS 5810", "material", True),
    ("nf t51-800", "NF T51-800", "material", True),
    ("ok compost", "TÜV OK compost", "product", True),
    ("seedling", "Seedling", "product", True),
    ("bpi", "BPI", "product", True),
    ("cpcb", "CPCB", "product", True),
    ("ecocert", "Ecocert", "ingredient", True),
    ("cosmos", "COSMOS", "ingredient", True),
    ("usda organic", "USDA Organic", "ingredient", True),
    ("fair for life", "Fair for Life", "company", True),
    ("fsc", "FSC", "material", True),
    ("gots", "GOTS", "material", True),
    ("iso 14001", "ISO 14001", "company", True),
    ("plastic neutral", "Plastic neutral badge", "other", True),
    ("cradle to cradle", "Cradle to Cradle", "product", True),
    ("green seal", "Green Seal", "product", True),
    ("oeko-tex", "OEKO-TEX", "other", False),
    ("ifra", "IFRA", "other", False),
    ("peta", "PETA", "other", False),
    ("leaping bunny", "Leaping Bunny", "other", False),
    ("animal test-free", "Animal test-free mark", "other", False),
    ("fssai", "FSSAI", "other", False),
    ("fda", "FDA", "other", False),
    ("iso 9001", "ISO 9001", "company", False),
]
NOT_PRODUCT_SCOPES = {"company", "ingredient", "other"}
SCOPE_WORDS = {
    "company": "the company",
    "ingredient": "an ingredient",
    "material": "a material",
    "product": "a product",
    "other": "something else",
    "unknown": "an unknown scope",
}


def known_certifier(text: str) -> tuple[str, str, bool] | None:
    """(certifier, scope, environmental) when the text names a certifier we know, else None."""
    low = text.lower()
    for needle, name, scope, env in CERT_SCOPES:
        if re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", low):
            return name, scope, env
    return None


def scope_words(scope: str | None) -> str:
    return SCOPE_WORDS.get(scope or "unknown", "something else")


@dataclass
class Candidate:
    text: str
    source: str  # "text" | "photo" | "link"
    location: str  # "description" | "photo:7" | URL
    hint: str  # kind suggested by the regex that found it
    photo_index: int | None = None
    box_2d: list[int] | None = None


@dataclass
class Judged:
    cand: Candidate
    covers: str
    kind: str
    certifier: str | None
    cert_scope: str | None
    note: str


def _rules_text(rule_ids: list[str]) -> str:
    lines = []
    for rule in primary_rules(rule_ids):
        needs = "; ".join(
            " or ".join(r.kinds()) + (f" ({r.desc})" if r.desc else "")
            for r in rule.required_evidence
        )
        lines.append(f"- {rule.id} {rule.name}: needs {needs or 'nothing'}")
    for rid in rule_ids:
        if rid in ("R04", "R10"):
            lines.append(f"- {rid} {get_rule(rid).name}")
    return "\n".join(lines) or "- (none)"


def _apply_code_scope(j: Judged) -> Judged:
    """Known certifiers get their scope from code; out-of-scope certificates can't be 'yes'."""
    known = known_certifier(j.cand.text) or (known_certifier(j.certifier) if j.certifier else None)
    if known:
        name, scope, env = known
        j.certifier, j.cert_scope = name, scope
        if not env:
            if j.covers in ("yes", "partly"):
                j.covers = "no"
                j.note = f"{name} is about safety or ethics, not this environmental claim."
            return j
        if j.kind in ("none", "qualifier"):
            j.kind = "certification"
    if j.cert_scope in NOT_PRODUCT_SCOPES and j.covers == "yes":
        j.covers = "partly"
    if j.cert_scope in NOT_PRODUCT_SCOPES and j.covers == "no" and j.kind == "certification":
        j.covers = "partly"  # TRD §9 row 5: an off-scope certificate counts as partial proof
    return j


def code_judge(cand: Candidate) -> Judged | None:
    """Fallback when the model budget is spent: only clear-cut certificate mentions count."""
    known = known_certifier(cand.text)
    if not known or not known[2]:
        return None
    name, scope, _ = known
    note = (
        f"{name} covers {scope_words(scope)}, not this claim."
        if scope in NOT_PRODUCT_SCOPES
        else f"Names {name}; not checked against this product (model budget used up)."
    )
    return Judged(cand, "partly", "certification", name, scope, note)


def judge(
    claim: Claim,
    rule_ids: list[str],
    cands: list[Candidate],
    listing: Listing,
    meter: llm.Meter | None,
    use_model: bool = True,
) -> list[Judged]:
    if not cands:
        return []
    if not use_model:
        return [j for c in cands if (j := code_judge(c))]
    numbered = "\n".join(f"{i + 1}. [{c.location}] {c.text}" for i, c in enumerate(cands))
    res = llm.call(
        "judge_evidence",
        JudgeEvidenceOut,
        variables={
            "claim_id": claim.id,
            "claim_type": claim.type,
            "claim_scope": claim.scope,
            "claim_quote": claim.quote,
            "title": listing.title,
            "rules": _rules_text(rule_ids),
            "candidates": numbered,
        },
        listing_id=listing.id,
        meter=meter,
    )
    out: list[Judged] = []
    seen: set[int] = set()
    for jd in res.data.judgements:
        jd: EvidenceJudgement
        i = jd.candidate - 1
        if i < 0 or i >= len(cands) or i in seen:
            continue
        seen.add(i)
        out.append(
            _apply_code_scope(
                Judged(
                    cands[i],
                    jd.covers_claim,
                    jd.kind,
                    jd.certifier,
                    jd.cert_scope,
                    careful(jd.note),
                )
            )
        )
    return out
