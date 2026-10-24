"""Event contract between core and frontend (TRD §15.3), and the per-run event sink.

Every event is {"seq", "t_ms", "type", "run_id", "data"}. `frontend/src/lib/events.ts` mirrors
these models by hand; the TRD table is the source of truth for both.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from praman import db

# ---------------------------------------------------------------------------
# Data payloads


class _Data(BaseModel):
    model_config = ConfigDict(extra="allow")  # optional fields may be added (TRD §15.3)


class RunStartedData(_Data):
    run_id: str
    listing_id: str
    mode: Literal["agent", "baseline"]
    llm_mode: Literal["live", "replay", "offline"]
    started_at: str


class PhotoRef(_Data):
    index: int
    url: str
    width: int | None = None
    height: int | None = None


class ListingData(_Data):
    id: str
    title: str
    store: str | None
    body_text: str
    photos: list[PhotoRef]


class ClaimData(_Data):
    id: str
    quote: str
    normalised: str
    type: Literal["vague", "specific", "comparative", "future"]
    scope: Literal[
        "product", "part", "packaging", "process", "disposal", "delivery", "brand", "unclear"
    ]
    location: str
    is_claim: bool
    not_claim_reason: str | None = None
    rule_ids: list[str]


class ClaimsData(_Data):
    claims: list[ClaimData]


class StepData(_Data):
    run_id: str
    claim_id: str | None
    n: int
    phase: Literal["plan", "act", "observe", "decide"]
    tool: str | None
    summary: str
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    payload_preview: str = Field(max_length=300)


class PhotoItemData(_Data):
    text: str
    kind: Literal["code", "certificate", "composition", "label", "claim", "other"]
    box_2d: list[int] | None


class PhotoReadPhoto(_Data):
    index: int
    items: list[PhotoItemData]


class PhotoReadData(_Data):
    photos: list[PhotoReadPhoto]


class RegistryMatch(_Data):
    s_no: int
    name: str
    state: str
    type: str
    validity: str


class RegistryLookupData(_Data):
    claim_id: str | None
    query: str
    rows_scanned: int
    list_date: str
    match: RegistryMatch | None
    score: float  # name similarity, 0–1


class EvidenceData(_Data):
    id: str
    claim_id: str
    source: Literal["text", "photo", "registry", "link", "consistency", "web"]
    detail: str
    photo_index: int | None = None
    crop_box: list[int] | None = None
    covers_claim: Literal["yes", "partly", "no", "contradicts"]
    certifier: str | None = None
    cert_scope: (
        Literal["product", "material", "ingredient", "company", "other", "unknown"] | None
    ) = None
    # Optional (W4): a QR code on the pack, {domain, followed, path?}
    qr: dict[str, Any] | None = None


class RuleChip(_Data):
    id: str
    name: str
    summary: str
    clause: str
    source: str


class VerdictData(_Data):
    claim_id: str
    label: Literal[
        "Backed", "Partly backed", "Not backed", "Contradicted", "Needs review", "Not a claim"
    ]
    evidence_ids: list[str]
    rule_ids: list[str]
    reason: str
    missing: str | None = None
    rewrite: str | None = None
    sources_searched: list[str]
    rules: list[RuleChip] = []


class RunFinishedData(_Data):
    llm_calls: int
    tokens_in: int
    tokens_out: int
    est_cost_inr: float
    elapsed_ms: int
    counts: dict[str, int]
    # Optional: true when the model's quota ran out mid-run (unchecked claims are Needs review)
    quota_reached: bool | None = None


class ErrorData(_Data):
    message: str
    recoverable: bool


# ---------------------------------------------------------------------------
# Envelopes (discriminated union on `type`)


class _Env(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int
    t_ms: int
    run_id: str


class RunStartedEvent(_Env):
    type: Literal["run_started"]
    data: RunStartedData


class ListingEvent(_Env):
    type: Literal["listing"]
    data: ListingData


class ClaimsEvent(_Env):
    type: Literal["claims"]
    data: ClaimsData


class StepEvent(_Env):
    type: Literal["step"]
    data: StepData


class PhotoReadEvent(_Env):
    type: Literal["photo_read"]
    data: PhotoReadData


class RegistryLookupEvent(_Env):
    type: Literal["registry_lookup"]
    data: RegistryLookupData


class EvidenceEvent(_Env):
    type: Literal["evidence"]
    data: EvidenceData


class VerdictEvent(_Env):
    type: Literal["verdict"]
    data: VerdictData


class RunFinishedEvent(_Env):
    type: Literal["run_finished"]
    data: RunFinishedData


class ErrorEvent(_Env):
    type: Literal["error"]
    data: ErrorData


Event = Annotated[
    RunStartedEvent
    | ListingEvent
    | ClaimsEvent
    | StepEvent
    | PhotoReadEvent
    | RegistryLookupEvent
    | EvidenceEvent
    | VerdictEvent
    | RunFinishedEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
EventAdapter: TypeAdapter[Event] = TypeAdapter(Event)
EVENT_TYPES = (
    "run_started",
    "listing",
    "claims",
    "step",
    "photo_read",
    "registry_lookup",
    "evidence",
    "verdict",
    "run_finished",
    "error",
)

Emit = Callable[[dict[str, Any]], None]


def no_emit(_event: dict[str, Any]) -> None:
    """Default listener: the CLI and tests run without the API."""


def validate_event(event: dict[str, Any]) -> Event:
    return EventAdapter.validate_python(event)


class EventSink:
    """Numbers, masks, validates, stores and forwards every event of one run."""

    def __init__(
        self,
        run_id: str,
        on_event: Emit | None = None,
        mask: Callable[[Any], Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.on_event = on_event or no_emit
        self.mask = mask
        self.seq = 0
        self.t0 = time.monotonic()
        self._lock = threading.Lock()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    def emit(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.seq += 1
            if self.mask is not None:
                data = self.mask(data)
            event = {
                "seq": self.seq,
                "t_ms": self.elapsed_ms(),
                "type": type_,
                "run_id": self.run_id,
                "data": data,
            }
            validate_event(event)
            db.execute(
                "INSERT INTO events (run_id, seq, type, t_ms, data_json) VALUES (?, ?, ?, ?, ?)",
                (self.run_id, event["seq"], type_, event["t_ms"], db.dumps(data)),
            )
        self.on_event(event)
        return event


def load_events(run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    import json

    rows = db.query(
        "SELECT seq, type, t_ms, data_json FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
        (run_id, after_seq),
    )
    return [
        {
            "seq": r["seq"],
            "t_ms": r["t_ms"],
            "type": r["type"],
            "run_id": run_id,
            "data": json.loads(r["data_json"]),
        }
        for r in rows
    ]
