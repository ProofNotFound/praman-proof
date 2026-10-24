"""decide_verdict: the TRD §9 decision table and its two guards, in plain code."""

from __future__ import annotations

from dataclasses import dataclass, field

from praman.config import CPCB_LIST_DATE_TEXT
from praman.models import Claim, Evidence, Verdict, VerdictLabel
from praman.rules import get_rule, primary_rules
from praman.tools.judge import scope_words

SOURCE_NAMES = {
    "text": "page text",
    "photos": "product photos",
    "registry": "CPCB registry",
    "link": "linked pages",
    "qr": "QR codes on the pack",
    "consistency": "consistency check",
    "material": "public sources on the material",
}
GOOD_CERT_SCOPES = {"product", "material"}
# Evidence kinds that substantiate a claim (a Backed verdict needs at least one, as 'yes')
PROOF_KINDS = {
    "certification",
    "scientific_evidence",
    "registry_match",
    "comparison_data",
    "plan",
    "material_check",
}
OFF_SCOPE = {"company", "ingredient", "other"}
# A material check can't stand in for these: plastics need the CPCB certificate (PWM Rules), and
# comparisons and future promises aren't about what the product is made of
NO_MATERIAL_FALLBACK = {"R05", "R06", "R07", "R09"}


@dataclass
class ClaimState:
    claim: Claim
    rule_ids: list[str]
    evidence: list[Evidence] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)  # "text", "photos", "registry", "link"
    open_sources: list[str] = field(default_factory=list)  # could still hold proof
    budget_exhausted: bool = False
    # The material check applied but couldn't run (search quota, no search key): nothing was
    # searched, so the claim can't honestly be called "not backed"
    material_unchecked: bool = False


@dataclass
class Decision:
    verdict: Verdict
    label_missing: list[str] = field(default_factory=list)  # rule IDs (TRD §9 row 6)
    row: int = 0


def _fits(ev: Evidence, kinds: list[str]) -> bool:
    if ev.kind not in kinds:
        return False
    # A printed code is a lead, not proof, until the registry confirms it
    return not (ev.kind == "registry_match" and ev.source != "registry")


def requirement_status(kinds: list[str], evidence: list[Evidence]) -> str:
    """'yes', 'partly' or 'none' for one requirement (a list of acceptable kinds)."""
    yes = [ev for ev in evidence if ev.covers_claim == "yes" and _fits(ev, kinds)]
    if yes:
        reg_missing = any(e.source == "registry" and e.covers_claim == "no" for e in evidence)
        if reg_missing and all(e.kind == "registry_match" for e in yes):
            return "partly"  # some maker printed on the pack isn't on the list
        return "yes"
    if any(ev.covers_claim in ("yes", "partly") and ev.kind in kinds for ev in evidence):
        return "partly"
    return "none"


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _sources_text(searched: list[str]) -> str:
    return _join([SOURCE_NAMES.get(s, s) for s in dict.fromkeys(searched)])


def _missing_text(rule_ids: list[str], evidence: list[Evidence]) -> str | None:
    lacks = []
    for rule in primary_rules(rule_ids):
        for req in rule.required_evidence:
            if req.kind == "label_text":
                continue
            if requirement_status(req.kinds(), evidence) != "yes":
                lacks.append(req.desc or " or ".join(req.kinds()).replace("_", " "))
    lacks = list(dict.fromkeys(lacks))
    return ("Needs: " + "; ".join(lacks) + ".") if lacks else None


def _registry_summary(evs: list[Evidence]) -> str:
    rows = [e.detail.split(" — ")[0].replace("CPCB certified list, ", "") for e in evs]
    return _join(rows)


def _decide(state: ClaimState) -> Decision:
    claim, ev = state.claim, state.evidence
    rule_ids = list(dict.fromkeys(state.rule_ids + [e.rule_id for e in ev if e.rule_id]))
    searched = list(dict.fromkeys(state.searched))

    def verdict(label: VerdictLabel, ids: list[Evidence], reason: str, missing: str | None = None):
        return Verdict(
            claim_id=claim.id,
            label=label,
            evidence_ids=[e.id for e in ids],
            rule_ids=rule_ids,
            reason=reason,
            missing=missing,
            sources_searched=searched,
        )

    # 1. Not a claim
    if not claim.is_claim:
        return Decision(
            Verdict(
                claim_id=claim.id,
                label=VerdictLabel.NOT_A_CLAIM,
                rule_ids=["R11"],
                reason=claim.not_claim_reason or "Not an environmental claim about this product.",
                sources_searched=[],
            ),
            row=1,
        )

    # 2. Contradicted
    contra = [e for e in ev if e.covers_claim == "contradicts"]
    if contra:
        first = contra[0]
        reason = first.note or f"Conflicts with the listing's own words: {first.detail}"
        return Decision(verdict(VerdictLabel.CONTRADICTED, contra, reason), row=2)

    labels_needed = [
        r.id
        for r in primary_rules(rule_ids)
        if any(q.kind == "label_text" for q in r.required_evidence)
    ]
    label_missing = [
        rid
        for rid in labels_needed
        if requirement_status(["label_text"], [e for e in ev if e.rule_id in (rid, None)]) != "yes"
    ]

    # 3. Registry match decides compostable / biodegradable plastic rules in code
    registry_rules = [
        r
        for r in primary_rules(rule_ids)
        if r.decides_in_code and any(q.kind == "registry_match" for q in r.required_evidence)
    ]
    reg_yes = [e for e in ev if e.source == "registry" and e.covers_claim == "yes"]
    reg_no = [e for e in ev if e.source == "registry" and e.covers_claim == "no"]
    if registry_rules and reg_yes and not reg_no:
        leads = [e for e in ev if e.kind == "registry_match" and e.source == "photo"]
        reason = (
            f"The maker printed on the pack is on CPCB's certified list dated {CPCB_LIST_DATE_TEXT}"
            if len(reg_yes) == 1
            else f"{'Both' if len(reg_yes) == 2 else f'All {len(reg_yes)}'} makers printed on the "
            f"pack are on CPCB's certified list dated {CPCB_LIST_DATE_TEXT}"
        )
        reason += f" ({_registry_summary(reg_yes)})."
        return Decision(
            verdict(VerdictLabel.BACKED, leads + reg_yes, reason),
            label_missing=label_missing,
            row=3,
        )

    # 4. Every requirement met with product-level proof
    reqs = [
        q.kinds()
        for r in primary_rules(rule_ids)
        for q in r.required_evidence
        if q.kind != "label_text"
    ]
    certs = [e for e in ev if e.kind == "certification" and e.covers_claim in ("yes", "partly")]
    certs_ok = all(e.cert_scope in GOOD_CERT_SCOPES for e in certs if e.covers_claim == "yes")
    yes_ev = [e for e in ev if e.covers_claim == "yes"]
    all_met = bool(reqs) and all(requirement_status(k, ev) == "yes" for k in reqs)
    if all_met and certs_ok and claim.scope != "unclear":
        reason = "Proof found: " + "; ".join(e.note or e.detail for e in yes_ev[:3])
        return Decision(
            verdict(VerdictLabel.BACKED, yes_ev, reason), label_missing=label_missing, row=4
        )

    # 4b. No certificate, but public sources say the material printed on the product has the
    # property the claim relies on (check_material; the user's fallback, DECISIONS 24 Oct)
    material = [e for e in ev if e.kind == "material_check" and e.covers_claim == "yes"]
    if material and claim.scope != "unclear" and not set(rule_ids) & NO_MATERIAL_FALLBACK:
        own = [
            e
            for e in ev
            if e.covers_claim in ("yes", "partly") and e.source in ("text", "photo") and e.kind
        ]
        note = material[0].note or material[0].detail
        reason = "Backed on its material, not a certificate: " + note[0].lower() + note[1:]
        return Decision(
            verdict(VerdictLabel.BACKED, own + material, reason),
            label_missing=label_missing,
            row=4,
        )

    # A QR code on the pack leads to another site (W4): it may hold the proof, but Praman follows
    # only same-site links, so a person should open it
    qr_off = [e for e in ev if e.kind == "qr_link"]
    if qr_off:
        partial = [e for e in ev if e.covers_claim in ("yes", "partly")]
        reason = f"{qr_off[0].detail}. It may lead to the proof, so a person should open it."
        return Decision(
            verdict(
                VerdictLabel.NEEDS_REVIEW, qr_off + partial, reason, _missing_text(rule_ids, ev)
            ),
            row=7,
        )

    # 5. Some proof, or a certificate for something else
    partial = [e for e in ev if e.covers_claim in ("yes", "partly")]
    off_scope = [e for e in certs if e.cert_scope in OFF_SCOPE]
    some = any(requirement_status(k, ev) in ("yes", "partly") for k in reqs) or any(
        e.kind == "material_check" for e in partial
    )
    if some or off_scope or (all_met and partial):
        if off_scope:
            c = off_scope[0]
            reason = (
                f"This certificate covers {scope_words(c.cert_scope)}, not this claim ({c.certifier})."
                if c.certifier
                else f"The certificate found covers {scope_words(c.cert_scope)}, not this claim."
            )
        elif all_met and claim.scope == "unclear":
            reason = "Proof found, but the claim doesn't say which part of the product it covers."
        else:
            first = (partial[0].note or partial[0].detail).strip()
            reason = "Partial support only. " + first + ("" if first.endswith(".") else ".")
        return Decision(
            verdict(VerdictLabel.PARTLY, partial, reason, _missing_text(rule_ids, ev)),
            row=5,
        )

    # 7. Out of budget while a source could still hold proof
    if state.budget_exhausted and state.open_sources:
        reason = (
            f"Not decided within the step budget; {_sources_text(state.open_sources)} "
            "not searched yet."
        )
        return Decision(verdict(VerdictLabel.NEEDS_REVIEW, [], reason), row=7)

    # 7b. The check on the product's own material couldn't run: we don't know, a person should
    if state.material_unchecked:
        reason = (
            "No certificate found, and the check of what the product is made of couldn't run "
            "(the web search wasn't available), so a person should confirm it."
        )
        return Decision(
            verdict(VerdictLabel.NEEDS_REVIEW, [], reason, _missing_text(rule_ids, ev)), row=7
        )

    # 8. Nothing found
    reason = f"Proof not found on this page (searched {_sources_text(searched) or 'nothing'})."
    return Decision(
        verdict(VerdictLabel.NOT_BACKED, [], reason, _missing_text(rule_ids, ev)), row=8
    )


def decide_verdict(state: ClaimState) -> Decision:
    """Apply the decision table, then the False-Backed and citation guards."""
    d = _decide(state)
    v = d.verdict
    # False-Backed guard: Backed needs ≥1 'yes' item that substantiates the claim. Qualifiers,
    # links and labels make a claim clearer but don't prove it on their own.
    if v.label == VerdictLabel.BACKED:
        cited = [
            e
            for e in state.evidence
            if e.id in v.evidence_ids and e.covers_claim == "yes" and e.kind in PROOF_KINDS
        ]
        if not cited:
            partly = [e for e in state.evidence if e.covers_claim in ("yes", "partly")]
            v.label = VerdictLabel.PARTLY if partly else VerdictLabel.NEEDS_REVIEW
            v.reason = (
                "The page explains the claim, but no certificate, standard, test or registry "
                "entry backs it."
            )
            v.evidence_ids = [e.id for e in partly]
            v.missing = _missing_text(v.rule_ids, state.evidence) or v.missing
            d.label_missing = []
    # Citation guard
    if v.label != VerdictLabel.NOT_A_CLAIM and not v.rule_ids:
        v.label = VerdictLabel.NEEDS_REVIEW
        v.reason = "No rule could be matched to this claim; a person should check it."
    if (
        v.label in (VerdictLabel.BACKED, VerdictLabel.PARTLY, VerdictLabel.CONTRADICTED)
        and not v.evidence_ids
    ):
        v.label = VerdictLabel.NEEDS_REVIEW
        v.reason = "The verdict had no evidence to cite, so it needs review."
    # Cross-cutting rules as chips: R10 when a certificate was weighed, R03 when no details link
    if any(e.kind == "certification" for e in state.evidence) and "R10" not in v.rule_ids:
        v.rule_ids.append("R10")
    if v.label not in (VerdictLabel.BACKED, VerdictLabel.NOT_A_CLAIM) and not any(
        e.kind == "disclosure_link" and e.covers_claim in ("yes", "partly") for e in state.evidence
    ):
        v.rule_ids.append("R03")
    return d


def injection_guard(v: Verdict, hits: list[str]) -> Verdict:
    """A page that addresses automated checkers (praman/injection.py) can't have a claim backed
    by the machine alone: Backed and Partly backed go to a person, with the reason."""
    if hits and v.label in (VerdictLabel.BACKED, VerdictLabel.PARTLY):
        v.label = VerdictLabel.NEEDS_REVIEW
        v.reason = (
            "The page holds text addressed to automated checkers (set aside before any model read "
            "it), so a person should confirm this proof. " + v.reason
        )
    return v


def label_check_claim(parent: Claim, rule_id: str, new_id: str) -> Claim:
    """The separate Needs-review item for a required label (TRD §9 row 6)."""
    pattern = next(
        (q.pattern or "" for q in get_rule(rule_id).required_evidence if q.kind == "label_text"), ""
    )
    wording = (
        "compostable only under industrial composting"
        if "industrial" in pattern
        else "number of days and the environment in which it degrades"
    )
    quote = f"Required label: {wording}"
    return Claim(
        id=new_id,
        quote=quote,
        normalised=quote.lower(),
        type="specific",
        scope=parent.scope,
        location="n/a",
        rule_ids=[rule_id],
        derived_from=parent.id,
    )


def label_verdict(label_claim: Claim, searched: list[str]) -> Verdict:
    rule = get_rule(label_claim.rule_ids[0])
    searched = [s for s in searched if s in ("text", "photos", "link")] or ["text"]
    return Verdict(
        claim_id=label_claim.id,
        label=VerdictLabel.NEEDS_REVIEW,
        evidence_ids=[],
        rule_ids=[rule.id],
        reason=(
            f"The required label isn't visible in the {_sources_text(searched)}. It may be printed "
            "on each item, so check the physical product."
        ),
        missing=f"Needs: {rule.required_evidence[-1].desc or 'the required label'} "
        f"({label_claim.quote.removeprefix('Required label: ')}).",
        sources_searched=list(dict.fromkeys(searched)),
    )
