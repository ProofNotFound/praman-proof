"""The agent loop (TRD §8): plan → act → observe → decide per claim, with a fixed tool list.

The planner (a model call) picks one tool at a time; every pick is validated against the tools
available for that claim, and anything invalid falls back to the default order
text → photos → registry → link. Verdicts are decided in code (praman/verdict.py).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator
from rapidfuzz import fuzz

from praman import injection, llm
from praman.config import CPCB_LIST_DATE_TEXT
from praman.events import Emit
from praman.models import Claim, Evidence, Listing, PlanActionOut, Verdict, VerdictLabel
from praman.rules import get_rule, match_rules, normalise, primary_rules, rule_lookup, term_in
from praman.run import RunContext
from praman.safety import careful
from praman.tools.claims import claims_from_photos, extract_claims
from praman.tools.consistency import Conflict, model_conflicts, rule_conflicts
from praman.tools.cpcb import certified_count, cpcb_lookup, find_codes
from praman.tools.fetch import (
    FetchError,
    fetch_linked_page,
    find_cert_names,
    registered_domain,
    same_site,
)
from praman.tools.judge import Candidate, judge
from praman.tools.material import (
    applies,
    check_material,
    claim_properties,
    material_lines,
    source_domains,
)
from praman.tools.material import covers as material_covers
from praman.tools.photos import choose_photos, read_photos
from praman.tools.qr import has_stored_codes, is_url, listing_codes
from praman.tools.rewrite import write_rewrites
from praman.tools.text import label_found, sentences, text_candidates
from praman.verdict import (
    ClaimState,
    decide_verdict,
    injection_guard,
    label_check_claim,
    label_verdict,
)

log = logging.getLogger(__name__)

# The fixed tool list (CLAUDE.md rule 2). The planner may name only these.
TOOLS = (
    "search_text",
    "read_photos",
    "decode_qr",
    "cpcb_lookup",
    "fetch_linked_page",
    "rule_lookup",
    "check_material",
)
DEFAULT_ORDER = ("search_text", "read_photos", "decode_qr", "cpcb_lookup", "fetch_linked_page")
SOURCE_OF = {
    "search_text": "text",
    "read_photos": "photos",
    "decode_qr": "qr",
    "cpcb_lookup": "registry",
    "fetch_linked_page": "link",
}
RESERVED_MODEL_CALLS = 2  # keep room for the consistency check and the rewrites
CERT_LINK_WORDS = ("certif", "test", "report", "lab", "compost", "sustainab", "standard", "proof")
MAKER_RE = re.compile(r"manufactured\s+by\s*[:\-]?\s*(?:m/s\.?\s*)?([^,\n]+)", re.I)
REGISTRY_TERMS = ("compostable", "biodegradable", "bio-degradable", "degradable")


class ToolCall(BaseModel):
    """A validated planner decision."""

    tool: Literal[
        "search_text",
        "read_photos",
        "decode_qr",
        "cpcb_lookup",
        "fetch_linked_page",
        "rule_lookup",
        "check_material",
        "STOP",
    ]
    queries: list[str] = Field(default_factory=list, max_length=6)
    url: str | None = None
    rule_id: str | None = None
    why: str
    by: Literal["model", "code"] = "code"

    @field_validator("why")
    @classmethod
    def _careful(cls, v: str) -> str:
        return careful(v.strip())[:240]


# ---------------------------------------------------------------------------
# Stage 1: claims and rules


def _rules_line(claims: list[Claim], limit: int = 110) -> str:
    """ "C1 → R02, R07, R08 · C2 → R02 (+3 more)", cut at a claim boundary."""
    if not claims:
        return "No claims to match."
    parts = [f"{c.id} → {', '.join(c.rule_ids)}" for c in claims]
    out = parts[0]
    for i, p in enumerate(parts[1:], start=1):
        more = f" (+{len(parts) - i} more)"
        if len(out) + 3 + len(p) + len(more) > limit:
            return out + more
        out += " · " + p
    return out


def stage1(ctx: RunContext, photos_in_extraction: bool = False) -> None:
    t0 = time.monotonic()
    calls0, tin0, tout0 = ctx.meter.calls, ctx.meter.tokens_in, ctx.meter.tokens_out
    claims, dropped = extract_claims(
        ctx.listing, ctx.photo_print if photos_in_extraction else None, ctx.meter
    )
    ctx.tool_calls += 1
    real = [c for c in claims if c.is_claim]
    summary = f"Listed {len(real)} claim{'s' if len(real) != 1 else ''}"
    if len(claims) > len(real):
        n = len(claims) - len(real)
        summary += (
            f" and {n} item that looks like a claim but isn't"
            if n == 1
            else f" and {n} items that look like claims but aren't"
        )
    if dropped:
        summary += f"; dropped {len(dropped)} quote(s) not found word for word on the page"
    ctx.step(
        "act",
        None,
        "extract_claims",
        summary + ".",
        {"claims": [c.quote for c in claims], "dropped": dropped},
        ms=int((time.monotonic() - t0) * 1000),
        tokens_in=ctx.meter.tokens_in - tin0,
        tokens_out=ctx.meter.tokens_out - tout0,
    )
    _ = calls0
    for c in claims:
        c.rule_ids = match_rules(c, ctx.listing, ctx.photo_print)
    ctx.step(
        "act",
        None,
        "match_rule",
        _rules_line(claims),
        {c.id: c.rule_ids for c in claims},
    )
    ctx.set_claims(claims)


# ---------------------------------------------------------------------------
# What each claim could still search


def registry_relevant(claim: Claim) -> bool:
    if {"R07", "R09"} & set(claim.rule_ids):
        return True
    return any(term_in(t, claim.quote) for t in REGISTRY_TERMS)


def registry_queries(ctx: RunContext) -> list[str]:
    """CPCB codes printed anywhere (exact), else maker names from 'Manufactured by' lines."""
    texts = [ctx.listing.body_text]
    if ctx.photo_print:
        texts += [it.text for _, it in ctx.photo_print.all_items()]
    codes: list[str] = []
    for t in texts:
        for code in find_codes(t):
            if code not in codes:
                codes.append(code)
    if codes:
        return codes
    makers: list[str] = []
    for t in texts:
        for m in MAKER_RE.finditer(t):
            name = m.group(1).strip(" .")
            if len(name) > 2 and name not in makers:
                makers.append(name)
    return makers[:4]


def cert_links(listing: Listing) -> list[str]:
    """Same-site pages likely to hold certificates (other product pages don't count)."""
    out = []
    for u in listing.links:
        path = urlparse(u).path.lower()
        if "/products/" in path or "/collections/" in path or "/cart" in path:
            continue
        if any(w in path for w in CERT_LINK_WORDS):
            out.append(u)
    return out[:3]


def options_for(ctx: RunContext, state: ClaimState) -> dict[str, str]:
    """Tools that could still help this claim, with a note for the planner."""
    searched = set(state.searched)
    opts: dict[str, str] = {}
    if "text" not in searched:
        opts["search_text"] = "Search the page text (title, description, tags, links) for proof."
    if ctx.mode == "agent" and ctx.listing.photos and "photos" not in searched:
        if ctx.photo_print is not None:
            n = len(ctx.photo_print.photo_indices_read)
            opts["read_photos"] = (
                f"Look at the {n} photos already read for this listing (no new model call)."
            )
        else:
            chosen = choose_photos(ctx.listing)
            opts["read_photos"] = (
                f"Read {len(chosen)} of {len(ctx.listing.photos)} product photos "
                f"({', '.join(map(str, chosen))}; likely box backs first) for codes, "
                "certificate marks, composition and labels."
            )
    # QR codes on the pack: only once the photos were looked at for this claim, and only when the
    # download-time scan stored a code (listings cached before W4 have none, so recorded runs
    # see exactly the options they saw before)
    if (
        ctx.mode == "agent"
        and "photos" in searched
        and "qr" not in searched
        and has_stored_codes(ctx.listing)
    ):
        with_qr = [p.index for p in ctx.listing.photos if p.qr]
        opts["decode_qr"] = (
            f"Decode the QR code{'s' if len(with_qr) > 1 else ''} printed on photo "
            f"{', '.join(map(str, with_qr))}: a link on the store's own site is opened and "
            "searched for proof; a link elsewhere is noted, not followed."
        )
    if ctx.mode == "agent" and "registry" not in searched and registry_relevant(state.claim):
        q = registry_queries(ctx)
        if q:
            opts["cpcb_lookup"] = (
                f"Check CPCB's certified list (dated {CPCB_LIST_DATE_TEXT}) for: " + "; ".join(q)
            )
    if ctx.mode == "agent" and "link" not in searched and cert_links(ctx.listing):
        opts["fetch_linked_page"] = "Open a same-site page linked from the listing: " + ", ".join(
            cert_links(ctx.listing)
        )
    return opts


def default_next(options: dict[str, str]) -> ToolCall:
    for tool in DEFAULT_ORDER:
        if tool in options:
            why = {
                "search_text": "Start with the page text: it's the cheapest source.",
                "read_photos": "No proof in the text yet; pack photos often print codes, marks and labels.",
                "decode_qr": "The pack prints a QR code; it may lead to the details or a certificate.",
                "cpcb_lookup": "A maker name or CPCB code is known, so check the registry.",
                "fetch_linked_page": "The listing links to a page that may hold certificates.",
            }[tool]
            return ToolCall(tool=tool, why=why)  # type: ignore[arg-type]
    return ToolCall(tool="STOP", why="Every source that could hold proof has been searched.")


def _evidence_lines(evs: list[Evidence]) -> str:
    if not evs:
        return "(none yet)"
    return "\n".join(f"- {e.id} [{e.source}] {e.covers_claim}: {e.detail[:140]}" for e in evs[-8:])


def _rules_lines(rule_ids: list[str]) -> str:
    out = []
    for rid in rule_ids:
        r = get_rule(rid)
        needs = "; ".join(" or ".join(q.kinds()) for q in r.required_evidence) or "—"
        out.append(f"- {r.id} {r.name} (needs: {needs})")
    return "\n".join(out)


def plan_next(
    ctx: RunContext, state: ClaimState, options: dict[str, str], first: bool, followups_left: int
) -> ToolCall:
    claim = state.claim
    if not options:
        return ToolCall(tool="STOP", why="Every source that could hold proof has been searched.")
    if first and "search_text" in options:
        return default_next({"search_text": options["search_text"]})
    spare = ctx.model_calls_left() - RESERVED_MODEL_CALLS
    waiting = sum(
        1
        for c in ctx.claims
        if c.is_claim and not c.derived_from and c.id not in ctx.verdicts and c.id != claim.id
    )
    if len(options) == 1 and not state.evidence and spare <= waiting + 1:
        # Nothing found yet, one place left to look, and calls are tight: no real choice to make
        return default_next(options)
    if spare <= 0:
        call = default_next(options)
        call.why = "Model budget used up; default order: " + call.why[0].lower() + call.why[1:]
        return call
    opt_lines = (
        "\n".join(f"- {k}: {v}" for k, v in options.items()) + "\n- STOP: finish this claim."
    )
    res = llm.call(
        "plan_next",
        PlanActionOut,
        variables={
            "claim_id": claim.id,
            "claim_type": claim.type,
            "claim_scope": claim.scope,
            "claim_location": claim.location,
            "claim_quote": claim.quote,
            "title": ctx.listing.title,
            "rules": _rules_lines(state.rule_ids),
            "searched": ", ".join(state.searched) or "nothing yet",
            "evidence": _evidence_lines(state.evidence),
            "options": opt_lines,
            "followups_left": followups_left,
        },
        listing_id=ctx.listing.id,
        meter=ctx.meter,
    )
    out = res.data
    try:
        call = ToolCall(
            tool=out.tool,
            queries=out.queries or [],
            url=out.url,
            rule_id=out.rule_id,
            why=out.why or "",
            by="model",
        )
    except ValidationError:
        return default_next(options)
    call._llm = res  # type: ignore[attr-defined]
    if call.tool == "STOP":
        return call
    if call.tool not in options:
        fb = default_next(options)
        fb.why = (
            f"Planner picked {call.tool}, which isn't available here; "
            + fb.why[0].lower()
            + fb.why[1:]
        )
        fb._llm = res  # type: ignore[attr-defined]
        return fb
    if call.tool == "cpcb_lookup":
        known = registry_queries(ctx)
        valid = [
            q for q in call.queries if any(fuzz.ratio(q.lower(), k.lower()) >= 90 for k in known)
        ]
        call.queries = valid or known
    if call.tool == "fetch_linked_page" and call.url not in ctx.listing.links:
        call.url = cert_links(ctx.listing)[0]
    return call


# ---------------------------------------------------------------------------
# Acting and observing


def _judged_to_evidence(ctx: RunContext, claim: Claim, judged, source: str) -> list[Evidence]:
    out = []
    for j in judged:
        if j.covers == "no":
            continue
        c: Candidate = j.cand
        out.append(
            ctx.add_evidence(
                claim_id=claim.id,
                source=source,
                detail=c.text if source != "photo" else f"Photo {c.photo_index}: {c.text}",
                photo_index=c.photo_index,
                crop_box=tuple(c.box_2d) if c.box_2d else None,
                covers_claim=j.covers,
                certifier=j.certifier,
                cert_scope=j.cert_scope if j.cert_scope else None,
                kind=None if j.kind == "none" else j.kind,
                note=j.note,
            )
        )
    return out


def _conflict_evidence(ctx: RunContext, claim: Claim, conflicts: list[Conflict]) -> list[Evidence]:
    have = {
        (e.claim_id, normalise(e.detail)) for e in ctx.evidence if e.covers_claim == "contradicts"
    }
    out = []
    for cf in conflicts:
        if cf.other_claim_id:
            detail = f'"{claim.quote}" vs "{cf.quote}" ({cf.where})'
        elif cf.photo_index:
            detail = f"Photo {cf.photo_index}: {cf.quote}"
        else:
            detail = f"{cf.where.capitalize()}: {cf.quote}"
        if (claim.id, normalise(detail)) in have:
            continue
        have.add((claim.id, normalise(detail)))
        source = (
            "photo"
            if cf.photo_index and not cf.other_claim_id
            else ("consistency" if cf.other_claim_id or cf.rule_id is None else "text")
        )
        out.append(
            ctx.add_evidence(
                claim_id=claim.id,
                source=source,
                detail=detail,
                photo_index=cf.photo_index,
                crop_box=tuple(cf.box_2d) if cf.box_2d else None,
                covers_claim="contradicts",
                rule_id=cf.rule_id,
                note=cf.explanation,
                conflict={"a": claim.quote, "b": cf.quote, "b_location": cf.where},
            )
        )
    return out


def _label_evidence(
    ctx: RunContext, state: ClaimState, texts: list[tuple[str, str, int | None, list[int] | None]]
) -> list[Evidence]:
    out = []
    have = {(e.rule_id, e.detail) for e in state.evidence if e.kind == "label_text"}
    for rid, loc, text in label_found(state.rule_ids, [(t[0], t[1]) for t in texts]):
        pidx, box = next(
            ((t[2], t[3]) for t in texts if t[0] == loc and t[1] == text), (None, None)
        )
        detail = f"Photo {pidx}: {text}" if pidx else text
        if (rid, detail) in have:
            continue
        have.add((rid, detail))
        out.append(
            ctx.add_evidence(
                claim_id=state.claim.id,
                source="photo" if pidx else "text",
                detail=detail,
                photo_index=pidx,
                crop_box=tuple(box) if box else None,
                covers_claim="yes",
                kind="label_text",
                rule_id=rid,
                note=f"The label {get_rule(rid).id} asks for is visible.",
            )
        )
    return out


def act_search_text(ctx: RunContext, state: ClaimState, use_model: bool) -> str:
    claim = state.claim
    cands = text_candidates(claim, state.rule_ids, ctx.listing)
    judged = judge(claim, state.rule_ids, cands, ctx.listing, ctx.meter, use_model=use_model)
    new = _judged_to_evidence(ctx, claim, judged, "text")
    texts = [(loc, s, None, None) for loc, s in sentences(ctx.listing)]
    new += _label_evidence(ctx, state, texts)
    state.searched.append("text")
    new += _conflict_evidence(
        ctx,
        claim,
        rule_conflicts(claim, ctx.claims, ctx.listing, ctx.photo_print, set(state.searched)),
    )
    state.evidence = ctx.evidence_for(claim.id)
    n_sent = len(sentences(ctx.listing))
    if not cands and not new:
        return f"No proof in the page text: none of {n_sent} lines names a certificate, standard, test, code or link."
    if not cands:
        return _observe_summary(new, "No proof in the page text")
    lead = f"{len(cands)} line{'s' if len(cands) != 1 else ''} in the page text looked relevant"
    return _observe_summary(new, lead)


def _short(text: str, limit: int = 120) -> str:
    """Cut at a word boundary, never mid-word."""
    text = text.strip()
    if len(text) <= limit:
        return text.rstrip(".")
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _observe_summary(new: list[Evidence], lead: str) -> str:
    if not new:
        return f"{lead}; none of it is proof for this claim."
    leads = [e for e in new if e.kind == "registry_match" and e.source == "photo"]
    rest = [e for e in new if e not in leads]
    parts = []
    if leads:
        photos = sorted({e.photo_index for e in leads if e.photo_index})
        where = f"photo {', '.join(map(str, photos))}" if photos else "the photos"
        n = len(leads)
        parts.append(
            f"{where} prints {'a CPCB code' if n == 1 else f'{n} CPCB codes'} "
            f"({', '.join(e.id for e in leads)}) to check on the registry"
        )
    for e in rest[:3]:
        word = {"yes": "backs", "partly": "partly supports", "contradicts": "conflicts with"}.get(
            e.covers_claim, e.covers_claim
        )
        parts.append(f"{e.id} {word} the claim: {_short(e.note or e.detail)}")
    more = f" (+{len(rest) - 3} more)" if len(rest) > 3 else ""
    body = "; ".join(p[0].upper() + p[1:] for p in parts) + more
    return f"{lead}. {body}" + ("" if body.endswith("…") else ".")


def act_read_photos(ctx: RunContext, state: ClaimState, use_model: bool) -> str:
    claim = state.claim
    lead = ""
    if ctx.photo_print is None:
        ctx.photo_print = read_photos(ctx.listing, meter=ctx.meter)
        pp = ctx.photo_print
        hits: list[str] = []
        for ph in pp.photos:
            for it in ph.items:
                it.text, h = injection.neutralise(it.text)
                hits += h
            ph.items = [it for it in ph.items if it.text.strip()]
        set_aside(ctx, hits, "photo print", claim.id, "read_photos")
        ctx.emit(
            "photo_read",
            {
                "photos": [
                    {
                        "index": p.index,
                        "items": [it.event_dict() for it in p.items] + _qr_items(ctx, p.index),
                    }
                    for p in pp.photos
                ],
                "claim_id": claim.id,
            },
        )
        n_items = len(pp.all_items())
        kinds: dict[str, int] = {}
        for _, it in pp.all_items():
            kinds[it.kind] = kinds.get(it.kind, 0) + 1
        lead = (
            f"Read {len(pp.photo_indices_read)} photos ({', '.join(map(str, pp.photo_indices_read))}): "
            f"{n_items} printed items ("
            + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))
            + ")"
        )
    else:
        lead = f"Reused the photo print from earlier ({len(ctx.photo_print.all_items())} items)"
    pp = ctx.photo_print
    new: list[Evidence] = []
    # Printed CPCB codes are leads for the registry, not proof yet
    if registry_relevant(claim):
        for idx, it in pp.all_items():
            for code in find_codes(it.text):
                new.append(
                    ctx.add_evidence(
                        claim_id=claim.id,
                        source="photo",
                        detail=f"Photo {idx}: {code}",
                        photo_index=idx,
                        crop_box=tuple(it.box_2d) if it.box_2d else None,
                        covers_claim="partly",
                        kind="registry_match",
                        certifier="CPCB",
                        note="A CPCB registration code printed on the pack; it counts as proof once the registry confirms it.",
                    )
                )
    cands: list[Candidate] = []
    seen_text: set[str] = set()
    for idx, it in pp.all_items():
        if it.kind not in ("certificate", "composition", "label") or find_codes(it.text):
            continue
        if normalise(it.text) in seen_text:
            continue  # the same print on several photos is one piece of evidence
        seen_text.add(normalise(it.text))
        cands.append(
            Candidate(
                text=it.text,
                source="photo",
                location=f"photo:{idx}",
                hint=it.kind,
                photo_index=idx,
                box_2d=it.box_2d,
            )
        )
    cands = cands[:10]
    judged = judge(claim, state.rule_ids, cands, ctx.listing, ctx.meter, use_model=use_model)
    new += _judged_to_evidence(ctx, claim, judged, "photo")
    texts = [(f"photo:{i}", it.text, i, it.box_2d) for i, it in pp.all_items()]
    new += _label_evidence(ctx, state, texts)
    state.searched.append("photos")
    new += _conflict_evidence(
        ctx, claim, rule_conflicts(claim, ctx.claims, ctx.listing, pp, set(state.searched))
    )
    state.evidence = ctx.evidence_for(claim.id)
    return _observe_summary(new, lead)


def _qr_items(ctx: RunContext, index: int) -> list[dict]:
    """QR codes stored for a photo, as printed items, so the Scan boxes them (W4). None for
    listings cached before W4."""
    photo = next((p for p in ctx.listing.photos if p.index == index), None)
    out = []
    for code in (photo.qr or []) if photo else []:
        where = registered_domain(urlparse(code.data).netloc) if is_url(code.data) else ""
        out.append(
            {
                "text": f"QR code: {where}" if where else "QR code",
                "kind": "code",
                "box_2d": code.box_2d,
            }
        )
    return out


def _add_photo_claims(ctx: RunContext) -> None:
    """Claims printed only on photos join the queue; rules are re-matched with the photo print."""
    assert ctx.photo_print is not None
    extra = claims_from_photos(ctx.photo_print, ctx.claims, ctx.listing)
    changed = bool(extra)
    for c in ctx.claims:
        if c.id in ctx.verdicts:
            continue
        ids = match_rules(c, ctx.listing, ctx.photo_print)
        if ids != c.rule_ids:
            c.rule_ids = ids
            changed = True
    for c in extra:
        c.rule_ids = match_rules(c, ctx.listing, ctx.photo_print)
    if changed:
        ctx.set_claims(ctx.claims + extra)
    if extra:
        ctx.step(
            "observe",
            None,
            "read_photos",
            f"Photos print {_plural(len(extra), 'claim', 'claims')} not in the page text "
            f"({', '.join(c.id for c in extra)}); added to the queue.",
            {
                "added": [c.model_dump() for c in extra],
                "detail": "; ".join(f'{c.id} "{c.quote}" ({c.location})' for c in extra),
            },
        )


def act_cpcb_lookup(ctx: RunContext, state: ClaimState, queries: list[str]) -> str:
    claim = state.claim
    rows = certified_count()
    new: list[Evidence] = []
    found, missing = [], []
    for q in queries:
        r = cpcb_lookup(q)
        match = r.match
        ctx.emit(
            "registry_lookup",
            {
                "claim_id": claim.id,
                "query": q,
                "rows_scanned": r.rows_scanned,
                "rows_uncertified": r.rows_uncertified,
                "list_date": r.list_date,
                "match": (
                    {
                        "s_no": match.s_no,
                        "name": match.name,
                        "state": match.state,
                        "type": match.type,
                        "validity": match.validity,
                        "certificate": match.certificate,
                        "table": match.table,
                    }
                    if match
                    else None
                ),
                "score": round(r.score / 100, 2),
            },
        )
        if match and match.table == 1:
            found.append(f"S.No. {match.s_no} {match.name}")
            if match.validity and match.validity.upper() != "NA":
                validity = f", valid until {match.validity}"
            elif match.certificate:
                validity = f", {match.certificate[0].lower()}{match.certificate[1:]}"
            else:
                validity = ""
            new.append(
                ctx.add_evidence(
                    claim_id=claim.id,
                    source="registry",
                    detail=(
                        f"CPCB certified list, S.No. {match.s_no}: {match.name}, {match.state or 'state not listed'}"
                        f"{validity} — matches “{q}” (name match {r.score / 100:.2f})"
                    ),
                    covers_claim="yes",
                    kind="registry_match",
                    certifier="CPCB",
                    cert_scope="product",
                    note=f"The maker is on CPCB's certified list dated {CPCB_LIST_DATE_TEXT}.",
                )
            )
        else:
            missing.append(q)
            why = (
                f"listed among units without a certificate (S.No. {match.s_no})"
                if match
                else f"no row matches (best name match {r.score / 100:.2f})"
            )
            new.append(
                ctx.add_evidence(
                    claim_id=claim.id,
                    source="registry",
                    detail=f"CPCB certified list: “{q}” — {why}",
                    covers_claim="no",
                    kind="registry_match",
                    certifier="CPCB",
                    note=f"This maker isn't on CPCB's certified list dated {CPCB_LIST_DATE_TEXT}.",
                )
            )
    state.searched.append("registry")
    state.evidence = ctx.evidence_for(claim.id)
    if found and not missing:
        return (
            (
                "Both makers are"
                if len(found) == 2
                else f"All {len(found)} makers are"
                if len(found) > 2
                else "The maker is"
            )
            + f" on CPCB's certified list ({CPCB_LIST_DATE_TEXT}): "
            + "; ".join(found)
            + "."
        )
    if found:
        return f"On the CPCB list: {'; '.join(found)}. Not found: {'; '.join(missing)}."
    return f"Not on CPCB's certified list ({rows} rows scanned): {'; '.join(missing)}."


def act_fetch_linked_page(ctx: RunContext, state: ClaimState, url: str, use_model: bool) -> str:
    claim = state.claim
    state.searched.append("link")
    try:
        doc = fetch_linked_page(url, ctx.listing)
    except FetchError as e:
        return f"Couldn't open the linked page: {e}."
    except Exception as e:  # noqa: BLE001 - network trouble is an observation, not a crash
        return f"Couldn't open the linked page ({type(e).__name__})."
    new, lead = _page_proof(ctx, state, url, doc, use_model)
    state.evidence = ctx.evidence_for(claim.id)
    return _observe_summary(new, lead)


def _page_proof(
    ctx: RunContext, state: ClaimState, url: str, doc: dict, use_model: bool
) -> tuple[list[Evidence], str]:
    """Certificate lines on a same-site page, judged for this claim: (new evidence, lead)."""
    claim = state.claim
    text, hits = injection.neutralise(doc.get("text", ""))
    if hits:
        doc = {**doc, "text": text}
        set_aside(ctx, hits, "linked page", claim.id, "fetch_linked_page")
    certs = doc.get("certificates") or find_cert_names(doc.get("text", ""))
    lines = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n", doc.get("text", ""))
        if s.strip() and any(c.lower() in s.lower() for c in certs)
    ][:8]
    cands = [Candidate(text=s, source="link", location=url, hint="certification") for s in lines]
    judged = judge(claim, state.rule_ids, cands, ctx.listing, ctx.meter, use_model=use_model)
    # A general certificates page doesn't tie a certificate to this product (code decides)
    tied = fuzz.partial_ratio(normalise(ctx.listing.title), normalise(doc.get("text", ""))) >= 90
    if not tied:
        for j in judged:
            if j.covers == "yes":
                j.covers = "partly"
                j.note = (j.note + " " if j.note else "") + (
                    "The page lists certificates without saying which products they cover."
                )
    new = _judged_to_evidence(ctx, claim, judged, "link")
    lead = f"Linked page names {len(certs)} certificate(s): {', '.join(certs[:6]) or 'none'}"
    if not tied:
        lead += ", but doesn't name this product"
    return new, lead


def act_decode_qr(ctx: RunContext, state: ClaimState, use_model: bool) -> str:
    """Decode the QR codes on the photos. A link on the listing's own site is opened and searched
    for proof like fetch_linked_page; a link elsewhere becomes evidence "not followed" (CLAUDE.md
    rule 10), which keeps the claim at Needs review."""
    claim = state.claim
    state.searched.append("qr")
    codes = [(idx, c) for idx, cs in sorted(listing_codes(ctx.listing).items()) for c in cs]
    if not codes:
        state.evidence = ctx.evidence_for(claim.id)
        return "No QR code could be read on the photos."
    notes: list[str] = []
    for idx, code in codes:
        box = tuple(code.box_2d) if code.box_2d else None
        if not is_url(code.data):
            notes.append(f"photo {idx}: a QR code with text, not a link")
            continue
        parts = urlparse(code.data.strip())
        domain = registered_domain(parts.netloc)
        if ctx.listing.url and same_site(code.data, ctx.listing.url):
            path = parts.path or "/"
            ctx.add_evidence(
                claim_id=claim.id,
                source="photo",
                detail=f"Photo {idx}: QR code links to {path} on the store's own site",
                photo_index=idx,
                crop_box=box,
                covers_claim="partly",
                kind="disclosure_link",
                note="The pack's QR code leads to details on the store's own site.",
                qr={"domain": domain, "followed": True, "path": path},
            )
            try:
                doc = fetch_linked_page(code.data.strip(), ctx.listing)
            except FetchError as e:
                notes.append(f"photo {idx}: QR link on the store's site couldn't be opened ({e})")
                continue
            except Exception as e:  # noqa: BLE001 - network trouble is an observation
                notes.append(f"photo {idx}: QR link couldn't be opened ({type(e).__name__})")
                continue
            _, lead = _page_proof(ctx, state, code.data.strip(), doc, use_model)
            notes.append(f"photo {idx}: QR link opened; {lead[0].lower()}{lead[1:]}")
        else:
            ctx.add_evidence(
                claim_id=claim.id,
                source="photo",
                detail=f"QR code links to {domain}; not followed",
                photo_index=idx,
                crop_box=box,
                covers_claim="no",
                kind="qr_link",
                note=(
                    f"Praman opens only links on the store's own site; this QR code leads to "
                    f"{domain}, so a person should open it."
                ),
                qr={"domain": domain, "followed": False},
            )
            notes.append(f"photo {idx}: QR code links to {domain}; not followed")
    state.evidence = ctx.evidence_for(claim.id)
    return f"{_plural(len(codes), 'QR code', 'QR codes')} read: " + "; ".join(notes) + "."


def _material_check(ctx: RunContext, state: ClaimState) -> tuple[list, str, str]:
    """(material lines, property, '' or why the check doesn't apply) for this claim."""
    lines = material_lines(ctx.listing, ctx.photo_print)
    props = claim_properties(state.claim, ctx.listing, ctx.claims)
    why_not = applies(state.claim, state.rule_ids, lines, props, ctx.claims)
    return lines, (props[0] if props else ""), why_not


def material_fallback_due(ctx: RunContext, state: ClaimState) -> bool:
    """No certificate settled the claim: check the product's own material instead (agent mode,
    model budget left, and code says the check applies)."""
    if ctx.mode != "agent" or "material" in state.searched or state.material_unchecked:
        return False
    if ctx.out_of_time() or ctx.out_of_tools():
        return False
    if decide_verdict(state).verdict.label not in (
        VerdictLabel.PARTLY,
        VerdictLabel.NOT_BACKED,
        VerdictLabel.NEEDS_REVIEW,
    ):
        return False
    _, prop, why_not = _material_check(ctx, state)
    if why_not:
        return False
    cached = prop in ctx.material_checks
    return cached or ctx.model_calls_left() > RESERVED_MODEL_CALLS


def act_check_material(ctx: RunContext, state: ClaimState) -> str:
    """Ask a web-search model (Groq browser search) whether the material printed on the product has the
    property the claim relies on. One call per property per run; each claim gets its own item."""
    claim = state.claim
    lines, prop, why_not = _material_check(ctx, state)
    if why_not:
        state.evidence = ctx.evidence_for(claim.id)
        return f"Material check skipped: {why_not}."
    out = ctx.material_checks.get(prop)
    if out is None:
        try:
            out = check_material(lines, prop, ctx.listing, ctx.meter)
        except llm.LLMError as e:
            out = f"Couldn't run the material check ({str(e)[:80]})."
        ctx.material_checks[prop] = out  # a failure isn't retried for the next claim
    if isinstance(out, str):
        # Nothing was searched: don't list "public sources on the material" as searched, and
        # don't let the claim fall to "Not backed" (decide_verdict row 7b)
        state.material_unchecked = True
        state.evidence = ctx.evidence_for(claim.id)
        return out
    state.searched.append("material")
    cov = material_covers(out)
    n = out.material_line
    line = lines[n - 1] if n and 1 <= n <= len(lines) else lines[0]
    names = source_domains(out)
    material = out.material.strip() or line.text
    if cov == "no":
        state.evidence = ctx.evidence_for(claim.id)
        why = "no source was found" if out.answer == "yes" else f"the answer was {out.answer}"
        return _short(f"Material check: {material} isn't shown to be {prop} ({why}).", 200)
    said = "is" if cov == "yes" else "may be"
    note = f"{material[0].upper()}{material[1:]} ({line.where}) {said} {prop} according to public sources"
    note += f" ({', '.join(names)})." if names else "."
    if out.caveat and cov != "yes":
        note += " " + out.caveat
    ev = ctx.add_evidence(
        claim_id=claim.id,
        source="web",
        detail=f"Material: {material} — {out.summary}"
        + (f" {out.caveat}" if out.caveat else "")
        + (f" Sources: {', '.join(names)}." if names else ""),
        covers_claim=cov,
        kind="material_check",
        note=careful(note),
    )
    state.evidence = ctx.evidence_for(claim.id)
    word = "backs" if cov == "yes" else "partly supports"
    return _short(f"{ev.id} {word} the claim: {note}", 200)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _lookup_line(queries: list[str]) -> str:
    codes = sum(1 for q in queries if find_codes(q))
    names = len(queries) - codes
    what = []
    if codes:
        what.append(_plural(codes, "CPCB code", "CPCB codes"))
    if names:
        what.append(_plural(names, "maker name", "maker names"))
    return f"Looking up {' and '.join(what) or 'the maker'} on CPCB's certified list."


def observation_line(
    ctx: RunContext, tool: str, new: list[Evidence], fresh_photos: bool, detail: str
) -> str:
    """One sentence for the trace (≤ ~110 characters); the full observation stays in the payload."""
    if tool == "cpcb_lookup":
        yes = [e for e in new if e.source == "registry" and e.covers_claim == "yes"]
        no = [e for e in new if e.source == "registry" and e.covers_claim == "no"]
        snos = [m.group(1) for e in yes if (m := re.search(r"S\.No\. (\d+)", e.detail))]
        listed = " and ".join(f"S.No. {n}" for n in snos)
        if yes and not no:
            who = (
                "Both makers are" if len(yes) == 2 else _plural(len(yes), "maker is", "makers are")
            )
            if len(yes) == 1:
                who = "The maker is"
            return f"{who} on CPCB's certified list: {listed}."
        if yes:
            return f"{listed} on CPCB's certified list; {_plural(len(no), 'maker', 'makers')} not found."
        return f"Not on CPCB's certified list ({certified_count()} rows checked)."
    if tool in ("rule_lookup", "check_material") or detail.startswith("Couldn't"):
        return detail
    if tool == "decode_qr":
        off = [e for e in new if e.kind == "qr_link"]
        same = [e for e in new if e.kind == "disclosure_link"]
        if not off and not same:
            return detail if len(detail) <= 110 else "QR codes read; none is a link."
        bits = []
        if same:
            bits.append(f"{_plural(len(same), 'link', 'links')} on the store's site opened")
        if off:
            doms = sorted({(e.qr or {}).get("domain", "") for e in off} - {""})
            bits.append(f"{_plural(len(off), 'link', 'links')} to {', '.join(doms)} not followed")
        proof = [e for e in new if e.source == "link" and e.covers_claim in ("yes", "partly")]
        if proof:
            bits.append(f"{_plural(len(proof), 'item', 'items')} on the page support it")
        return "QR codes: " + "; ".join(bits) + "."
    if tool == "search_text":
        lead = "Page text"
        if not new:
            return detail if len(detail) <= 110 else "No proof in the page text."
    elif tool == "read_photos":
        pp = ctx.photo_print
        lead = (
            f"Read {len(pp.photo_indices_read)} photos, {len(pp.all_items())} printed items"
            if fresh_photos and pp
            else "Photo print"
        )
    else:
        lead = "Linked page"
    if not new:
        return f"{lead}: nothing that is proof for this claim."
    leads = [e for e in new if e.kind == "registry_match" and e.source == "photo"]
    rest = [e for e in new if e not in leads]
    con = [e for e in rest if e.covers_claim == "contradicts"]
    yes = [e for e in rest if e.covers_claim == "yes"]
    partly = [e for e in rest if e.covers_claim == "partly"]
    parts = []
    if leads:
        photos = sorted({e.photo_index for e in leads if e.photo_index})
        where = f"photo {', '.join(map(str, photos))}" if photos else "the photos"
        parts.append(
            f"{where} prints {_plural(len(leads), 'CPCB code', 'CPCB codes')} to check on the registry"
        )
    if con:
        parts.append(f"{_plural(len(con), 'item conflicts', 'items conflict')} with the claim")
    if yes:
        parts.append(f"{_plural(len(yes), 'item backs', 'items back')} the claim")
    if partly:
        parts.append(f"{_plural(len(partly), 'item partly supports', 'items partly support')} it")
    line = f"{lead}: " + ", ".join(parts)
    if (yes or partly) and not con and not any(e.certifier for e in yes + partly):
        line += "; none names a standard or certifier"
    return line + "."


def run_tool(ctx: RunContext, state: ClaimState, call: ToolCall) -> None:
    claim = state.claim
    use_model = ctx.model_calls_left() > (RESERVED_MODEL_CALLS if ctx.mode == "agent" else 0)
    act_summary = {
        "search_text": "Searching the page text for certificates, standards, tests, codes, links and labels.",
        "read_photos": "Reading the product photos."
        if ctx.photo_print is None
        else "Checking the photo print for this claim.",
        "decode_qr": "Decoding the QR codes printed on the photos.",
        "cpcb_lookup": _lookup_line(call.queries),
        "fetch_linked_page": f"Opening {call.url}.",
        "rule_lookup": f"Looking up rule {call.rule_id}.",
        "check_material": "Checking with a web search whether the material named on the product "
        "has the claimed property.",
    }[call.tool]
    ctx.tool_calls += 1
    t0 = time.monotonic()
    m0 = (ctx.meter.tokens_in, ctx.meter.tokens_out)
    fresh_photos = call.tool == "read_photos" and ctx.photo_print is None
    n0 = len(ctx.evidence)
    ctx.step("act", claim.id, call.tool, act_summary, call.model_dump(exclude={"why", "by"}))
    if call.tool == "search_text":
        obs = act_search_text(ctx, state, use_model)
    elif call.tool == "read_photos":
        obs = act_read_photos(ctx, state, use_model)
    elif call.tool == "decode_qr":
        obs = act_decode_qr(ctx, state, use_model)
    elif call.tool == "cpcb_lookup":
        obs = act_cpcb_lookup(ctx, state, call.queries)
    elif call.tool == "fetch_linked_page":
        obs = act_fetch_linked_page(ctx, state, call.url or "", use_model)
    elif call.tool == "check_material":
        obs = act_check_material(ctx, state)
    else:
        info = rule_lookup(call.rule_id or "")
        obs = f"{info['id']}: {info['summary']}"
    new = [e for e in ctx.evidence[n0:] if e.claim_id == claim.id]
    ctx.step(
        "observe",
        claim.id,
        call.tool,
        observation_line(ctx, call.tool, new, fresh_photos, obs),
        {"evidence": [e.id for e in state.evidence], "detail": obs},
        ms=int((time.monotonic() - t0) * 1000),
        tokens_in=ctx.meter.tokens_in - m0[0],
        tokens_out=ctx.meter.tokens_out - m0[1],
    )
    if fresh_photos:
        _add_photo_claims(ctx)


# ---------------------------------------------------------------------------
# Deciding


def open_sources(ctx: RunContext, state: ClaimState) -> list[str]:
    return [SOURCE_OF[t] for t in options_for(ctx, state) if t in SOURCE_OF]


def set_aside(
    ctx: RunContext,
    hits: list[str],
    where: str,
    claim_id: str | None = None,
    tool: str | None = None,
) -> None:
    """Record text addressed to automated checkers (already removed from what the model reads)."""
    new = [h for h in hits if h not in ctx.injection_hits]
    if not new:
        return
    ctx.injection_hits += new
    ctx.step(
        "observe",
        claim_id,
        tool,
        f"Set aside {_plural(len(new), 'line', 'lines')} in the {where} addressed to automated "
        "checkers; no model read them, and supported claims on this page go to a person",
        {"injection": new, "where": where},
    )


def injection_pass(ctx: RunContext) -> None:
    """Claims decided before photo or linked-page text addressed to checkers turned up."""
    if not ctx.injection_hits:
        return
    for cid, v in list(ctx.verdicts.items()):
        if v.label not in (VerdictLabel.BACKED, VerdictLabel.PARTLY):
            continue
        nv = injection_guard(v.model_copy(deep=True), ctx.injection_hits)
        nv.reason = careful(nv.reason)
        ctx.step("decide", cid, None, f"{nv.label.value}: {nv.reason}", {"row": "injection"})
        ctx.set_verdict(nv)


def decide_and_emit(ctx: RunContext, state: ClaimState) -> None:
    d = decide_verdict(state)
    v = injection_guard(d.verdict, ctx.injection_hits)
    v.reason = careful(v.reason)
    ctx.step(
        "decide",
        state.claim.id,
        None,
        f"{v.label.value}: {v.reason}",
        {"row": d.row, "evidence_ids": v.evidence_ids, "rule_ids": v.rule_ids},
    )
    ctx.set_verdict(v)
    for rid in d.label_missing:
        lc = label_check_claim(state.claim, rid, f"C{len(ctx.claims) + 1}")
        ctx.set_claims(ctx.claims + [lc])
        lv = label_verdict(lc, state.searched)
        ctx.step(
            "decide",
            lc.id,
            None,
            f"{lv.label.value}: {lv.reason}",
            {"derived_from": state.claim.id, "rule_ids": lv.rule_ids},
        )
        ctx.set_verdict(lv)


def process_claim(ctx: RunContext, claim: Claim, plan: Callable[..., ToolCall] = plan_next) -> None:
    state = ClaimState(claim=claim, rule_ids=claim.rule_ids)
    if not claim.is_claim:
        decide_and_emit(ctx, state)
        return
    max_follow = ctx.settings.praman_max_followups
    searches = 0  # tool actions so far; the first one isn't a follow-up (TRD §8.1)
    while True:
        if ctx.out_of_time() or ctx.out_of_tools():
            state.budget_exhausted = True
            break
        options = options_for(ctx, state)
        t0 = time.monotonic()
        m0 = (ctx.meter.tokens_in, ctx.meter.tokens_out)
        first = searches == 0
        followups_left = max_follow if first else max_follow - (searches - 1)
        call = plan(ctx, state, options, first, followups_left)
        ctx.step(
            "plan",
            claim.id,
            None if call.tool == "STOP" else call.tool,
            call.why,
            {"tool": call.tool, "by": call.by, "options": list(options)},
            ms=int((time.monotonic() - t0) * 1000),
            tokens_in=ctx.meter.tokens_in - m0[0],
            tokens_out=ctx.meter.tokens_out - m0[1],
        )
        if call.tool == "STOP":
            break
        run_tool(ctx, state, call)
        state.rule_ids = ctx.claim(claim.id).rule_ids  # photos may re-match rules
        provisional = decide_verdict(state).verdict.label
        if provisional in (VerdictLabel.BACKED, VerdictLabel.CONTRADICTED):
            break
        if call.tool == "rule_lookup":
            continue
        searches += 1
        if searches > max_follow:  # the first search plus max_follow follow-ups are done
            state.budget_exhausted = True
            break
    if material_fallback_due(ctx, state):
        call = ToolCall(
            tool="check_material",
            why="No certificate settles it; check whether the material printed on the product "
            "has this property.",
        )
        ctx.step("plan", claim.id, call.tool, call.why, {"tool": call.tool, "by": call.by})
        run_tool(ctx, state, call)
    state.open_sources = open_sources(ctx, state)
    decide_and_emit(ctx, state)


# ---------------------------------------------------------------------------
# End of run: consistency and rewrites


def consistency_pass(ctx: RunContext) -> None:
    t0 = time.monotonic()
    m0 = (ctx.meter.tokens_in, ctx.meter.tokens_out)
    ctx.step(
        "plan",
        None,
        "check_consistency",
        "Check the listing against itself: claims vs materials, numbers and printed text.",
    )
    ctx.tool_calls += 1
    ctx.step(
        "act", None, "check_consistency", "Comparing every claim with the page and the photo print."
    )
    sources = {"text", "photos"} if ctx.photo_print else {"text"}
    real = [c for c in ctx.claims if c.is_claim and not c.derived_from]
    known: list[Conflict] = []
    for c in real:
        known += rule_conflicts(c, ctx.claims, ctx.listing, ctx.photo_print, sources)
    found: list[Conflict] = list(known)
    if ctx.model_calls_left() > 1:
        try:
            found += model_conflicts(ctx.listing, ctx.photo_print, ctx.claims, known, ctx.meter)
        except llm.QuotaReached:
            ctx.quota_reached = True  # the code checks above still count
        except llm.LLMError as e:
            # A timeout here must not throw away verdicts that are already decided: the checks
            # in code above still count, and the trace says what didn't run
            log.warning("consistency model check failed in run %s: %s", ctx.run_id, e)
            ctx.step(
                "observe",
                None,
                "check_consistency",
                "The model part of the consistency check didn't answer, so only the checks in "
                "code ran; the verdicts stand.",
            )
    touched: dict[str, list[Evidence]] = {}
    for cf in found:
        claim = ctx.claim(cf.claim_id)
        new = _conflict_evidence(ctx, claim, [cf])
        if new:
            touched.setdefault(claim.id, []).extend(new)
    n_new = sum(len(v) for v in touched.values())
    ctx.step(
        "observe",
        None,
        "check_consistency",
        (
            f"{_plural(n_new, 'new conflict', 'new conflicts')} found ({', '.join(touched)})."
            if n_new
            else "No new conflicts between the claims and the listing's own facts."
        ),
        {
            "conflicts": {k: [e.id for e in v] for k, v in touched.items()},
            "detail": "; ".join(
                f"{cid}: {evs[0].note or evs[0].detail}" for cid, evs in touched.items()
            ),
        },
        ms=int((time.monotonic() - t0) * 1000),
        tokens_in=ctx.meter.tokens_in - m0[0],
        tokens_out=ctx.meter.tokens_out - m0[1],
    )
    for cid in touched:
        old = ctx.verdicts.get(cid)
        state = ClaimState(
            claim=ctx.claim(cid),
            rule_ids=ctx.claim(cid).rule_ids,
            evidence=ctx.evidence_for(cid),
            searched=list(old.sources_searched) + ["consistency"] if old else ["consistency"],
        )
        d = decide_verdict(state)
        if old and d.verdict.label == old.label and d.verdict.evidence_ids == old.evidence_ids:
            continue
        d.verdict.reason = careful(d.verdict.reason)
        prev = f" (was {old.label.value})" if old and old.label != d.verdict.label else ""
        ctx.step(
            "decide",
            cid,
            None,
            f"{d.verdict.label.value}{prev}: {d.verdict.reason}",
            {"row": d.row},
        )
        ctx.set_verdict(d.verdict)


def rewrite_pass(ctx: RunContext) -> None:
    if ctx.quota_reached:
        ctx.step(
            "act", None, "write_rewrite", "Model quota reached; no suggested wording this run."
        )
        return
    if ctx.model_calls_left() < 1:
        ctx.step(
            "act", None, "write_rewrite", "Model budget used up; no suggested wording this run."
        )
        return
    t0 = time.monotonic()
    m0 = (ctx.meter.tokens_in, ctx.meter.tokens_out)
    try:
        rewrites = write_rewrites(ctx.listing, ctx.claims, ctx.verdicts, ctx.meter)
    except llm.QuotaReached:
        ctx.quota_reached = True
        ctx.step(
            "act", None, "write_rewrite", "Model quota reached; no suggested wording this run."
        )
        return
    except llm.LLMError as e:
        log.warning("rewrite failed in run %s: %s", ctx.run_id, e)
        ctx.step(
            "act",
            None,
            "write_rewrite",
            "The model didn't answer, so there is no suggested wording this run; the verdicts stand.",
        )
        return
    ctx.step(
        "act",
        None,
        "write_rewrite",
        f"Suggested wording for {len(rewrites)} claim(s) that aren't Backed."
        if rewrites
        else "No claims need new wording.",
        rewrites,
        ms=int((time.monotonic() - t0) * 1000),
        tokens_in=ctx.meter.tokens_in - m0[0],
        tokens_out=ctx.meter.tokens_out - m0[1],
    )
    for cid, text in rewrites.items():
        v = ctx.verdicts[cid].model_copy()
        v.rewrite = text
        ctx.set_verdict(v)


# ---------------------------------------------------------------------------
# Model quota: finish cleanly instead of failing the run

QUOTA_REASON = "Model quota reached; this claim wasn't checked, so a person should review it."


def quota_stop(ctx: RunContext) -> None:
    """The model kept answering with a quota or rate-limit error. Every claim without a verdict
    becomes Needs review (not-a-claim items need no model and are decided as usual)."""
    ctx.quota_reached = True
    if not ctx.claims:
        ctx.step(
            "act", None, "extract_claims", "Model quota reached before the claims were listed."
        )
        return
    for c in list(ctx.claims):
        if c.id in ctx.verdicts or c.derived_from:
            continue
        if not c.is_claim:
            decide_and_emit(ctx, ClaimState(claim=c, rule_ids=c.rule_ids))
            continue
        v = Verdict(
            claim_id=c.id,
            label=VerdictLabel.NEEDS_REVIEW,
            rule_ids=list(c.rule_ids),
            reason=QUOTA_REASON,
            sources_searched=[],
        )
        ctx.step("decide", c.id, None, f"Needs review: {QUOTA_REASON}", {"quota_reached": True})
        ctx.set_verdict(v)


# ---------------------------------------------------------------------------
# Entry points


def agent_pipeline(ctx: RunContext) -> None:
    try:
        stage1(ctx)
        i = 0
        while i < len(ctx.claims):  # the queue grows when photos show new claims
            c = ctx.claims[i]
            i += 1
            if c.derived_from or c.id in ctx.verdicts:
                continue
            process_claim(ctx, c)
        injection_pass(ctx)
    except llm.QuotaReached:
        log.warning("model quota reached in run %s", ctx.run_id)
        quota_stop(ctx)
    if any(c.is_claim for c in ctx.claims):
        consistency_pass(ctx)
        rewrite_pass(ctx)


def run_listing(
    listing: Listing, mode: str = "agent", on_event: Emit | None = None, run_id: str | None = None
) -> RunContext:
    """Run one listing in agent or baseline mode. Never raises: failures become an error event."""
    ctx = RunContext(listing, mode, on_event=on_event, run_id=run_id)
    try:
        ctx.emit(
            "run_started",
            {
                "run_id": ctx.run_id,
                "listing_id": listing.id,
                "mode": mode,
                "llm_mode": ctx.llm_mode,
                "started_at": ctx.started_at.isoformat(),
            },
        )
        # Seller text that talks to an automated checker is set aside before any model reads it
        clean, hits = injection.neutralise_listing(listing)
        ctx.listing = clean
        ctx.emit_listing()
        set_aside(ctx, hits, "page text")
        if mode == "baseline":
            from praman.baseline import baseline_pipeline

            baseline_pipeline(ctx)
        else:
            agent_pipeline(ctx)
        ctx.finish()
    except llm.ReplayMiss:
        log.warning("replay miss in run %s", ctx.run_id)
        ctx.fail(
            "This run needs a model answer that isn't recorded yet. Use replay or live mode to record it."
        )
    except llm.LLMError as e:
        log.warning("model error in run %s: %s", ctx.run_id, e)
        ctx.fail(
            "The model didn't answer after several tries. Try again in a minute.", recoverable=True
        )
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed", ctx.run_id)
        ctx.fail(f"The run stopped on an internal error ({type(e).__name__}).")
    return ctx


TOOL_REGISTRY = {name: name for name in TOOLS}  # names the planner may use (validated by ToolCall)
_ = primary_rules
