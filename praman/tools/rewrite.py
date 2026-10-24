"""write_rewrite (TRD §10): one suggested wording per claim that isn't Backed, in one model call."""

from __future__ import annotations

from praman import llm
from praman.models import Claim, Listing, Verdict, VerdictLabel, WriteRewriteOut
from praman.safety import careful

NEEDS_REWRITE = {
    VerdictLabel.PARTLY,
    VerdictLabel.NOT_BACKED,
    VerdictLabel.CONTRADICTED,
    VerdictLabel.NEEDS_REVIEW,
}


def write_rewrites(
    listing: Listing,
    claims: list[Claim],
    verdicts: dict[str, Verdict],
    meter: llm.Meter | None,
) -> dict[str, str]:
    todo = [
        c
        for c in claims
        if c.is_claim and c.id in verdicts and verdicts[c.id].label in NEEDS_REWRITE
    ]
    if not todo:
        return {}
    lines = "\n".join(
        f'{c.id}: "{c.quote}" ({c.type}, {c.scope}) — {verdicts[c.id].label.value}: '
        f"{verdicts[c.id].reason}"
        for c in todo
    )
    res = llm.call(
        "write_rewrite",
        WriteRewriteOut,
        variables={"title": listing.title, "claims": lines},
        listing_id=listing.id,
        meter=meter,
    )
    wanted = {c.id for c in todo}
    return {
        r.claim_id: careful(r.rewrite.strip())
        for r in res.data.rewrites
        if r.claim_id in wanted and r.rewrite.strip()
    }
