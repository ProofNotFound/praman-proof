"""Pydantic models (TRD §5) plus the structured outputs the prompts return."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

ClaimType = Literal["vague", "specific", "comparative", "future"]
Scope = Literal[
    "product", "part", "packaging", "process", "disposal", "delivery", "brand", "unclear"
]
EvidenceSource = Literal["text", "photo", "registry", "link", "consistency", "web"]
Covers = Literal["yes", "partly", "no", "contradicts"]
CertScope = Literal["product", "material", "ingredient", "company", "other", "unknown"]
PhotoItemKind = Literal["code", "certificate", "composition", "label", "claim", "other"]
Phase = Literal["plan", "act", "observe", "decide"]


class QrCode(BaseModel):
    """A QR code decoded from a photo (W4): its text and where it sits ([ymin, xmin, ymax, xmax],
    0–1000)."""

    data: str
    box_2d: list[int] | None = None


class Photo(BaseModel):
    index: int  # position in the listing (1-based)
    url: str
    local_path: str | None = None
    alt: str = ""
    width: int | None = None
    height: int | None = None
    # Share of strong edges, computed once when the photo is downloaded and kept in the cached
    # listing, so photo choice (and replay keys) don't depend on the gitignored image files
    text_score: float | None = None
    # QR codes decoded when the photo was downloaded (W4); None means "not scanned" (listings
    # cached before W4, including the demo cases), so the planner's options stay as recorded
    qr: list[QrCode] | None = None


class Listing(BaseModel):
    id: str
    # shopify_json: /products/<handle>.json; json_ld / html: any product page (W2)
    source: Literal["shopify_json", "json_ld", "html", "pasted", "cache"]
    url: str | None = None
    store: str | None = None
    title: str
    body_text: str
    tags: list[str] = []
    photos: list[Photo] = []
    fetched_at: datetime
    product_type: str = ""
    vendor: str = ""
    links: list[str] = []  # same-site links found in the description HTML

    def full_text(self) -> str:
        parts = [self.title, self.body_text]
        if self.tags:
            parts.append("Tags: " + ", ".join(self.tags))
        return "\n\n".join(p for p in parts if p)


class Claim(BaseModel):
    id: str
    quote: str
    normalised: str
    type: ClaimType
    scope: Scope
    location: str  # "title" | "description" | "tag" | "photo:3" | "n/a"
    is_claim: bool = True
    not_claim_reason: str | None = None
    rule_ids: list[str] = []
    # Set on a label check split out of another claim (TRD §9 row 6)
    derived_from: str | None = None


class Evidence(BaseModel):
    id: str
    claim_id: str
    source: EvidenceSource
    detail: str
    photo_index: int | None = None
    crop_box: tuple[int, int, int, int] | None = None  # [ymin, xmin, ymax, xmax], 0–1000
    covers_claim: Covers
    certifier: str | None = None
    cert_scope: CertScope | None = None
    # Which required_evidence kind it speaks to (certification, registry_match …)
    kind: str | None = None
    # The rule a contradiction or label check comes from
    rule_id: str | None = None
    # One neutral sentence on why it covers (or doesn't cover) the claim
    note: str | None = None
    # A QR code on the pack (W4): {"domain", "followed", "path"?}; only on decode_qr evidence
    qr: dict[str, Any] | None = None


class Step(BaseModel):
    run_id: str
    claim_id: str | None
    n: int
    phase: Phase
    tool: str | None
    summary: str
    payload: dict[str, Any] = {}
    ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class VerdictLabel(StrEnum):
    BACKED = "Backed"
    PARTLY = "Partly backed"
    NOT_BACKED = "Not backed"
    CONTRADICTED = "Contradicted"
    NEEDS_REVIEW = "Needs review"
    NOT_A_CLAIM = "Not a claim"


class Verdict(BaseModel):
    claim_id: str
    label: VerdictLabel
    evidence_ids: list[str] = []
    rule_ids: list[str] = []
    reason: str
    missing: str | None = None
    rewrite: str | None = None
    sources_searched: list[str] = []


class Run(BaseModel):
    id: str
    listing_id: str
    mode: Literal["agent", "baseline"]
    llm_mode: Literal["live", "replay", "offline"]
    started_at: datetime
    finished_at: datetime | None = None
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_inr: float = 0.0
    approved_by: str | None = None
    approved_at: datetime | None = None


# ---------------------------------------------------------------------------
# Photo print (read_photos output, TRD §7.1)


class PhotoItem(BaseModel):
    text: str
    kind: PhotoItemKind
    box_2d: list[int] | None = None  # [ymin, xmin, ymax, xmax], 0–1000
    claim_type: ClaimType | None = None  # kind == "claim" only; not sent in events
    scope: Scope | None = None

    def event_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind, "box_2d": self.box_2d}


class PhotoReading(BaseModel):
    index: int
    items: list[PhotoItem] = []
    qr_present: bool = False


class PhotoPrint(BaseModel):
    photos: list[PhotoReading] = []
    photo_indices_read: list[int] = []

    def all_items(self) -> list[tuple[int, PhotoItem]]:
        return [(p.index, it) for p in self.photos for it in p.items]

    def text(self) -> str:
        lines = []
        for p in self.photos:
            for it in p.items:
                lines.append(f"[photo {p.index}] ({it.kind}) {it.text}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Structured LLM outputs. Kept to plain types so the response schema stays simple.


class LLMClaim(BaseModel):
    quote: str = Field(description="Exact words as they appear in the listing")
    type: ClaimType
    scope: Scope
    location: str = Field(description='"title", "description", "tag" or "photo:N"')
    is_claim: bool
    not_claim_reason: str | None = None


class ExtractClaimsOut(BaseModel):
    claims: list[LLMClaim]


class LLMPhotoItem(BaseModel):
    text: str = Field(description="Exact printed string, never paraphrased")
    kind: PhotoItemKind
    box_2d: list[int] | None = Field(
        default=None, description="[ymin, xmin, ymax, xmax] normalised 0-1000, or null"
    )
    claim_type: ClaimType | None = Field(default=None, description='Only when kind is "claim"')
    scope: Scope | None = Field(default=None, description='Only when kind is "claim"')


class LLMPhoto(BaseModel):
    photo: int = Field(description="The photo number as given in the prompt")
    items: list[LLMPhotoItem]
    qr_present: bool


class ReadPhotosOut(BaseModel):
    photos: list[LLMPhoto]


class PlanAction(BaseModel):
    tool: str = Field(description="One allowed tool name, or STOP")
    args: dict[str, Any] = {}
    why: str = Field(description="One sentence shown to the reviewer")


class PlanActionOut(BaseModel):
    """Gemini schemas can't express free-form dicts, so args travel as named optional fields."""

    tool: Literal[
        "search_text",
        "read_photos",
        "decode_qr",
        "cpcb_lookup",
        "fetch_linked_page",
        "rule_lookup",
        "STOP",
    ]
    queries: list[str] | None = Field(
        default=None, description="cpcb_lookup only: maker names or CPCB codes, exact"
    )
    url: str | None = Field(default=None, description="fetch_linked_page only")
    rule_id: str | None = Field(default=None, description="rule_lookup only")
    why: str


class EvidenceJudgement(BaseModel):
    candidate: int = Field(description="Number of the candidate being judged")
    covers_claim: Covers
    kind: Literal[
        "qualifier",
        "certification",
        "scientific_evidence",
        "registry_match",
        "label_text",
        "disclosure_link",
        "comparison_data",
        "plan",
        "none",
    ]
    certifier: str | None = None
    cert_scope: CertScope | None = None
    note: str = Field(description="One short sentence in careful, neutral language")


class JudgeEvidenceOut(BaseModel):
    judgements: list[EvidenceJudgement]


class Conflict(BaseModel):
    claim_id: str
    conflicting_quote: str = Field(description="Exact words from the listing or photo print")
    where: str = Field(description='"title", "description", "tag" or "photo:N"')
    explanation: str = Field(description="One neutral sentence")


class WebSource(BaseModel):
    title: str = ""
    url: str = ""


class MaterialCheckOut(BaseModel):
    """check_material: whether the material named on the product has the claimed property, from a
    web-search answer. `sources` and `queries` come from what the search tool returned, never
    from the model's own words."""

    material: str = Field(description="The material as named on the product, e.g. glassine paper")
    material_line: int | None = Field(
        default=None, description="Number of the line the material was taken from"
    )
    property: str
    answer: Literal["yes", "partly", "no", "unclear"]
    summary: str = Field(description="One neutral sentence on what the sources say")
    caveat: str | None = None
    sources: list[WebSource] = []
    queries: list[str] = []


class CheckConsistencyOut(BaseModel):
    conflicts: list[Conflict]


class Rewrite(BaseModel):
    claim_id: str
    rewrite: str


class WriteRewriteOut(BaseModel):
    rewrites: list[Rewrite]
