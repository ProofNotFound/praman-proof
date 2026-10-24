"""Baseline mode (TRD §8.4): extract_claims (text only) → match_rule → search_text → decide_verdict.

No photos, no registry, no linked pages, no re-planning. Used only for the comparison.
"""

from __future__ import annotations

from praman import llm
from praman.agent import ToolCall, decide_and_emit, quota_stop, run_tool, stage1
from praman.run import RunContext
from praman.verdict import ClaimState


def baseline_pipeline(ctx: RunContext) -> None:
    try:
        _pipeline(ctx)
    except llm.QuotaReached:
        quota_stop(ctx)


def _pipeline(ctx: RunContext) -> None:
    stage1(ctx)
    for claim in list(ctx.claims):
        if claim.derived_from or claim.id in ctx.verdicts:
            continue
        state = ClaimState(claim=claim, rule_ids=claim.rule_ids)
        if claim.is_claim:
            call = ToolCall(
                tool="search_text", why="Fixed pipeline: the page text is the only source."
            )
            ctx.step(
                "plan", claim.id, "search_text", call.why, {"tool": "search_text", "by": "code"}
            )
            run_tool(ctx, state, call)
        decide_and_emit(ctx, state)
