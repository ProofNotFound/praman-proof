"""A quota or rate-limit error mid-run finishes the run cleanly (W1): no error event, unchecked
claims become Needs review with the reason "Model quota reached", run_finished says so."""

import pytest

from praman import llm
from praman.agent import QUOTA_REASON, run_listing
from praman.events import validate_event
from praman.models import VerdictLabel as V
from praman.tools.fetch import load_cached


def _quota_after(monkeypatch, n_ok: int):
    real = llm.call
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > n_ok:
            raise llm.QuotaReached("429 RESOURCE_EXHAUSTED")
        return real(*args, **kwargs)

    monkeypatch.setattr(llm, "call", flaky)


@pytest.mark.parametrize(("lid", "mode"), [("L14", "agent"), ("L06", "baseline")])
def test_quota_mid_run_marks_unchecked_claims_needs_review(monkeypatch, lid, mode):
    _quota_after(monkeypatch, 2)  # extract_claims and one more answer, then 429s
    events: list[dict] = []
    ctx = run_listing(load_cached(lid), mode, on_event=events.append)
    assert not ctx.failed
    assert events[-1]["type"] == "run_finished"
    assert events[-1]["data"]["quota_reached"] is True
    assert not any(e["type"] == "error" for e in events)
    for e in events:
        validate_event(e)
    real = [c for c in ctx.claims if c.is_claim]
    assert real and all(c.id in ctx.verdicts for c in real)
    quota = [v for v in ctx.verdicts.values() if v.reason == QUOTA_REASON]
    assert quota and all(v.label == V.NEEDS_REVIEW for v in quota)
    assert QUOTA_REASON.startswith("Model quota reached")


def test_quota_before_claims_are_listed(monkeypatch):
    _quota_after(monkeypatch, 0)
    events: list[dict] = []
    ctx = run_listing(load_cached("L14"), "agent", on_event=events.append)
    assert not ctx.failed and not ctx.claims
    fin = events[-1]
    assert fin["type"] == "run_finished" and fin["data"]["quota_reached"] is True
    assert fin["data"]["counts"] == {}


def test_normal_runs_carry_no_quota_flag():
    events: list[dict] = []
    run_listing(load_cached("L21"), "agent", on_event=events.append)
    assert "quota_reached" not in events[-1]["data"]


def test_rate_limit_after_retries_raises_quota_reached(monkeypatch):
    class Http429(Exception):
        code = 429

    def always_429(*_a, **_k):
        raise Http429("Too many requests")

    monkeypatch.setattr(llm, "_live_call", always_429)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    with pytest.raises(llm.QuotaReached):
        llm._call_with_retries("some-model", "prompt", llm.BaseModel, [])
