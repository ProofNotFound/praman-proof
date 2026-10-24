"""One run's state: steps, claims, evidence and verdicts, written to SQLite and emitted as events."""

from __future__ import annotations

import json
import re
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from praman import anonymise, db, llm, provenance
from praman.config import get_settings
from praman.events import Emit, EventSink
from praman.models import Claim, Evidence, Listing, PhotoPrint, Step, Verdict, VerdictLabel
from praman.rules import get_rule, load_rules

PREVIEW_CHARS = 300


def new_run_id(listing_id: str, mode: str) -> str:
    return f"{listing_id}-{mode[0]}-{secrets.token_hex(3)}"


def claim_event(c: Claim) -> dict[str, Any]:
    """Claim as sent in events: `derived_from` only on label checks split out of a claim."""
    data = c.model_dump()
    if data.get("derived_from") is None:
        data.pop("derived_from", None)
    return data


SUMMARY_CHARS = 110
_ABBREV = ("No", "S.No", "Pvt", "Ltd", "Nr", "Dr", "St", "vs", "e.g", "i.e", "approx")


def one_line(text: str, limit: int = SUMMARY_CHARS) -> str:
    """The trace shows one sentence of about `limit` characters: the first sentence, without
    parentheses if it's still long, cut at a word boundary as a last resort."""
    t = " ".join(text.split())
    end = None
    for m in re.finditer(r"[.!?](?=\s+[A-Z\"“(]|$)", t):
        before = t[: m.start()].rsplit(" ", 1)[-1]
        if before in _ABBREV or before.endswith(_ABBREV) or re.fullmatch(r"[A-Z]", before):
            continue
        end = m.end()
        break
    first = t[:end] if end else t
    if len(first) > limit:
        first = re.sub(r"\s*\([^)]*\)", "", first)
    if len(first) > limit:
        first = first[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:—–-") + "…"
    return first


def preview(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str) if payload else ""
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1] + "…"


class RunContext:
    def __init__(
        self,
        listing: Listing,
        mode: str,
        on_event: Emit | None = None,
        run_id: str | None = None,
    ) -> None:
        s = get_settings()
        self.settings = s
        self.listing = listing
        self.mode = mode
        self.llm_mode = s.praman_llm_mode
        self.run_id = run_id or new_run_id(listing.id, mode)
        if s.praman_anonymise:
            anonymise.register_listing(listing)  # a new store gets its letter before any event
        self.meter = llm.Meter()
        self.sink = EventSink(self.run_id, on_event, anonymise.mask if s.praman_anonymise else None)
        self.n = 0
        self.tool_calls = 0
        self.claims: list[Claim] = []
        self.evidence: list[Evidence] = []
        self.verdicts: dict[str, Verdict] = {}
        self.photo_print: PhotoPrint | None = None
        self.started_at = datetime.now(UTC)
        self.deadline = time.monotonic() + s.praman_max_wall_s
        self.tools_used: list[str] = []
        self.failed = False
        # The model answered with a quota or rate-limit error: no more model calls this run
        self.quota_reached = False
        # Sentences addressed to automated checkers, set aside before any model read them
        self.injection_hits: list[str] = []
        # check_material answers (or the failure message) by property, shared by the claims of one run
        self.material_checks: dict[str, Any] = {}
        db.execute(
            "INSERT INTO runs (id, listing_id, mode, llm_mode, started_at, status, listing_json, "
            "provenance_json) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
            (
                self.run_id,
                listing.id,
                mode,
                self.llm_mode,
                self.started_at.isoformat(),
                listing.model_dump_json(),
                db.dumps(provenance.snapshot()),
            ),
        )

    # -- budgets -----------------------------------------------------------

    def model_calls_left(self) -> int:
        if self.quota_reached:
            return 0
        return self.settings.praman_max_model_calls - self.meter.calls

    def out_of_time(self) -> bool:
        return time.monotonic() > self.deadline

    def out_of_tools(self) -> bool:
        return self.tool_calls >= self.settings.praman_max_tool_calls

    # -- events and storage --------------------------------------------------

    def emit(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.sink.emit(type_, data)

    def step(
        self,
        phase: str,
        claim_id: str | None,
        tool: str | None,
        summary: str,
        payload: dict[str, Any] | None = None,
        ms: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> Step:
        self.n += 1
        short = one_line(summary)
        if short != " ".join(summary.split()):
            payload = {**(payload or {})}
            payload.setdefault("detail", summary)
        summary = short
        st = Step(
            run_id=self.run_id,
            claim_id=claim_id,
            n=self.n,
            phase=phase,  # type: ignore[arg-type]
            tool=tool,
            summary=summary,
            payload=payload or {},
            ms=ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        db.execute(
            "INSERT INTO steps (run_id, n, claim_id, phase, tool, summary, payload_json, ms, "
            "tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                st.n,
                claim_id,
                phase,
                tool,
                summary,
                db.dumps(st.payload),
                ms,
                tokens_in,
                tokens_out,
            ),
        )
        data = st.model_dump(exclude={"payload"})
        data["payload_preview"] = preview(st.payload)
        self.emit("step", data)
        return st

    def emit_listing(self, photo_url: str = "/api/photos/{listing_id}/{n}") -> None:
        lst = self.listing
        self.emit(
            "listing",
            {
                "id": lst.id,
                "title": lst.title,
                "store": lst.store,
                "body_text": lst.body_text,
                "photos": [
                    {
                        "index": p.index,
                        "url": photo_url.format(listing_id=lst.id, n=p.index),
                        "width": p.width,
                        "height": p.height,
                    }
                    for p in lst.photos
                ],
                "tags": lst.tags,
            },
        )

    def set_claims(self, claims: list[Claim]) -> None:
        self.claims = claims
        for c in claims:
            db.execute(
                "INSERT OR REPLACE INTO claims (run_id, claim_id, quote, type, scope, location, "
                "is_claim, rule_ids_json, claim_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.run_id,
                    c.id,
                    c.quote,
                    c.type,
                    c.scope,
                    c.location,
                    int(c.is_claim),
                    db.dumps(c.rule_ids),
                    c.model_dump_json(),
                ),
            )
        self.emit("claims", {"claims": [claim_event(c) for c in claims]})

    def claim(self, claim_id: str) -> Claim:
        return next(c for c in self.claims if c.id == claim_id)

    def add_evidence(self, **fields: Any) -> Evidence:
        ev = Evidence(id=f"E{len(self.evidence) + 1}", **fields)
        self.evidence.append(ev)
        db.execute(
            "INSERT INTO evidence (run_id, evidence_id, claim_id, source, detail, photo_index, "
            "crop_box_json, covers_claim, certifier, cert_scope, evidence_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                ev.id,
                ev.claim_id,
                ev.source,
                ev.detail,
                ev.photo_index,
                db.dumps(list(ev.crop_box)) if ev.crop_box else None,
                ev.covers_claim,
                ev.certifier,
                ev.cert_scope,
                ev.model_dump_json(),
            ),
        )
        data = ev.model_dump()
        data["crop_box"] = list(ev.crop_box) if ev.crop_box else None
        if data.get("qr") is None:
            data.pop("qr", None)  # optional (TRD §15.3): only QR evidence carries it
        self.emit("evidence", data)
        return ev

    def evidence_for(self, claim_id: str) -> list[Evidence]:
        return [e for e in self.evidence if e.claim_id == claim_id]

    def set_verdict(self, v: Verdict) -> None:
        self.verdicts[v.claim_id] = v
        db.execute(
            "INSERT OR REPLACE INTO verdicts (run_id, claim_id, label, evidence_ids_json, "
            "rule_ids_json, reason, missing, rewrite, verdict_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                v.claim_id,
                v.label.value,
                db.dumps(v.evidence_ids),
                db.dumps(v.rule_ids),
                v.reason,
                v.missing,
                v.rewrite,
                v.model_dump_json(),
            ),
        )
        rules = load_rules()
        data = v.model_dump(mode="json")
        data["rules"] = [get_rule(r).chip() for r in v.rule_ids if r in rules]
        self.emit("verdict", data)

    # -- end of run ----------------------------------------------------------

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.verdicts.values():
            out[v.label.value] = out.get(v.label.value, 0) + 1
        return out

    def finish(self) -> None:
        m = self.meter
        elapsed = self.sink.elapsed_ms()
        db.execute(
            "UPDATE runs SET finished_at = ?, llm_calls = ?, tokens_in = ?, tokens_out = ?, "
            "est_cost_inr = ?, status = 'finished' WHERE id = ?",
            (
                datetime.now(UTC).isoformat(),
                m.calls,
                m.tokens_in,
                m.tokens_out,
                m.cost_inr(),
                self.run_id,
            ),
        )
        data = {
            "llm_calls": m.calls,
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "est_cost_inr": m.cost_inr(),
            "elapsed_ms": elapsed,
            "counts": self.counts(),
            "cached_calls": m.cached_calls,
            "tool_calls": self.tool_calls,
        }
        if self.quota_reached:
            data["quota_reached"] = True  # optional (TRD §15.3): unchecked claims are Needs review
        self.emit("run_finished", data)

    def fail(self, message: str, recoverable: bool = False) -> None:
        self.failed = True
        db.execute(
            "UPDATE runs SET finished_at = ?, status = 'error', llm_calls = ?, tokens_in = ?, "
            "tokens_out = ?, est_cost_inr = ? WHERE id = ?",
            (
                datetime.now(UTC).isoformat(),
                self.meter.calls,
                self.meter.tokens_in,
                self.meter.tokens_out,
                self.meter.cost_inr(),
                self.run_id,
            ),
        )
        self.emit("error", {"message": message, "recoverable": recoverable})


def label_counts(verdicts: list[Verdict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in verdicts:
        out[v.label.value] = out.get(v.label.value, 0) + 1
    return out


__all__ = ["RunContext", "VerdictLabel", "label_counts", "new_run_id", "preview"]
