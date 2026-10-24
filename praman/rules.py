"""Load data/rules.json and match rules to claims (TRD §6). Plain code, no model."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from praman.config import RULE_PACKS_DIR, RULES_PATH
from praman.models import Claim, Listing, PhotoPrint

CROSS_CUTTING = {"R03", "R04", "R10"}
# When no trigger term matches, the claim type still decides which basic rule applies.
TYPE_FALLBACK = {"vague": "R01", "specific": "R02", "comparative": "R05", "future": "R06"}

PLASTIC_NOUNS = [
    "bag", "bags", "carry bag", "garbage bag", "bin liner", "liner", "liners", "film", "wrap",
    "cling", "cutlery", "pouch", "pouches", "sachet", "sachets",
]  # fmt: skip
PLASTIC_MATERIALS = [
    "polymer", "pla", "pbat", "pbs", "pe", "ldpe", "hdpe", "lldpe", "pp", "polyethylene",
    "polypropylene", "bioplastic", "bio-plastic", "resin", "carrier resin", "master batch",
]  # fmt: skip


class Triggers(BaseModel):
    terms: list[str] = []
    claim_types: list[str] = []
    requires_plastic_context: bool = False
    cross_cutting: bool = False
    classifier: str | None = None


class RequiredEvidence(BaseModel):
    kind: str
    desc: str = ""
    alternatives: list[str] = []
    registry: str | None = None
    pattern: str | None = None

    def kinds(self) -> list[str]:
        return [self.kind, *self.alternatives]


class Rule(BaseModel):
    id: str
    name: str
    source: str
    clause: str
    summary: str
    triggers: Triggers
    required_evidence: list[RequiredEvidence] = []
    contradiction_signals: list[str] = []
    contradiction_note: str | None = None
    contradiction_target: str = "anchor"  # "anchor": signals in facts contradict this claim
    decides_in_code: bool = False
    citation_url: str | None = None
    source_title: str | None = None

    @property
    def clause_text(self) -> str:
        """The clause, or a plain placeholder while the official clause number is still TODO."""
        return "clause to be confirmed" if self.clause.strip().upper() == "TODO" else self.clause

    def chip(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "clause": self.clause_text,
            "source": self.source_title or self.source,
        }


@lru_cache(maxsize=1)
def load_rules() -> dict[str, Rule]:
    return _parse_rules(json.loads(RULES_PATH.read_text()))


# ---------------------------------------------------------------------------
# Rule packs: one JSON file per rulebook, read by the same loader. The agent runs the green-claims
# pack (data/rules.json); other packs in data/rule_packs/ load and match the same way.

GREEN_PACK = {
    "name": "green_claims",
    "title": "Green claims",
    "domain": "Environmental claims on consumer products",
    "status": "active",
    "status_note": "Runs in the agent today: every case in this app.",
}


def _pack_files() -> dict[str, Path]:
    files = {"green_claims": RULES_PATH}
    for p in sorted(RULE_PACKS_DIR.glob("*.json")):
        files.setdefault(p.stem, p)
    return files


def pack_names() -> list[str]:
    return list(_pack_files())


@lru_cache(maxsize=8)
def load_pack(name: str) -> tuple[dict, dict[str, Rule]]:
    """A pack's description and its rules, validated with the same Rule model."""
    path = _pack_files().get(name)
    if path is None:
        raise KeyError(name)
    doc = json.loads(path.read_text())
    meta = GREEN_PACK if name == "green_claims" else doc.get("pack", {"name": name, "title": name})
    rules = load_rules() if name == "green_claims" else _parse_rules(doc)
    return {**meta, "version": doc.get("version"), "as_of": doc.get("as_of")}, rules


def list_packs() -> list[dict]:
    """Every rule pack with its rules (trigger terms included, so a page can try them)."""
    out = []
    for name in _pack_files():
        meta, rules = load_pack(name)
        out.append(
            {
                **meta,
                "sources": sorted({r.source_title or r.source for r in rules.values()}),
                "rules": [
                    {
                        **r.chip(),
                        "terms": r.triggers.terms,
                        "evidence": [e.desc for e in r.required_evidence],
                    }
                    for r in rules.values()
                ],
            }
        )
    return out


def _parse_rules(doc: dict) -> dict[str, Rule]:
    sources = doc.get("sources", {})
    out: dict[str, Rule] = {}
    for raw in doc["rules"]:
        rule = Rule.model_validate(raw)
        src = sources.get(rule.source, {})
        url = src.get("official_url")
        rule.citation_url = url if url and not url.startswith("TODO") else None
        rule.source_title = src.get("short") or src.get("title")
        out[rule.id] = rule
    return out


def get_rule(rule_id: str) -> Rule:
    return load_rules()[rule_id]


def normalise(text: str) -> str:
    s = text.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def term_pattern(term: str) -> re.Pattern[str]:
    """Match a trigger term on word edges; 'first ' keeps its trailing space, 'by 20' matches 2030."""
    core = term.strip().lower()
    lead = r"(?<![a-z0-9])"
    if term.endswith(" "):
        tail = r"(?=\s)"
    elif core[-1].isalpha():
        tail = r"(?![a-z])"
    else:
        tail = ""
    return re.compile(lead + re.escape(core) + tail)


def term_in(term: str, text: str) -> bool:
    return bool(term_pattern(term).search(normalise(text)))


def matched_terms(rule: Rule, text: str) -> list[str]:
    norm = normalise(text) + " "
    return [t for t in rule.triggers.terms if term_pattern(t).search(norm)]


def _has_word(words: list[str], text: str) -> bool:
    norm = normalise(text)
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z])", norm) for w in words)


def plastic_context(listing: Listing, photo_print: PhotoPrint | None = None) -> bool:
    """Is the product or its packaging plastic-like (bags, film, cutlery, liners, pouches)?

    Looks at the title, product type and tags for plastic-like products, and at composition lines
    (description and photos) for plastic materials. Phrases like "plastic-free" don't count.
    """
    head = " ".join([listing.title, listing.product_type, " ".join(listing.tags)])
    if _has_word(PLASTIC_NOUNS, head):
        return True
    comp_lines = [
        ln
        for ln in listing.body_text.splitlines()
        if re.search(r"made (from|of|with)|material|resin", ln, re.I)
    ]
    if photo_print:
        comp_lines += [it.text for _, it in photo_print.all_items() if it.kind == "composition"]
    return _has_word(PLASTIC_MATERIALS, "\n".join(comp_lines))


def match_rules(claim: Claim, listing: Listing, photo_print: PhotoPrint | None = None) -> list[str]:
    """Rule IDs for a claim (TRD §6.3), primary rules first, then cross-cutting ones."""
    if not claim.is_claim:
        return ["R11"]
    rules = load_rules()
    plastic = plastic_context(listing, photo_print)
    ids: list[str] = []
    for rule in rules.values():
        t = rule.triggers
        if t.cross_cutting or t.classifier or not t.terms:
            continue
        if claim.type not in t.claim_types:
            continue
        if t.requires_plastic_context and not plastic:
            continue
        if matched_terms(rule, claim.quote):
            ids.append(rule.id)
    if not any(i not in CROSS_CUTTING for i in ids):
        ids.insert(0, TYPE_FALLBACK[claim.type])
    if claim.scope == "unclear" and claim.type in rules["R04"].triggers.claim_types:
        ids.append("R04")
    if claim.type in rules["R10"].triggers.claim_types and matched_terms(rules["R10"], claim.quote):
        ids.append("R10")
    return list(dict.fromkeys(ids))


def primary_rules(rule_ids: list[str]) -> list[Rule]:
    rules = load_rules()
    return [rules[r] for r in rule_ids if r in rules and r not in CROSS_CUTTING and r != "R11"]


def required_kinds(rule_ids: list[str]) -> list[list[str]]:
    """Each requirement as a list of acceptable kinds (the first is the main one)."""
    out = []
    for rule in primary_rules(rule_ids):
        for req in rule.required_evidence:
            out.append(req.kinds())
    return out


def rule_lookup(rule_id: str) -> dict:
    """Tool: rule summary, clause and citation for one rule ID."""
    rule = get_rule(rule_id)
    return {
        "id": rule.id,
        "name": rule.name,
        "summary": rule.summary,
        "clause": rule.clause_text,
        "source": rule.source_title or rule.source,
        "citation_url": rule.citation_url,
    }
