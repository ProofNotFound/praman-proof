"""Golden traces (TRD §16): the four demo listings, replayed offline from tests/fixtures/replay."""

import json

import pytest

from praman.agent import run_listing
from praman.anonymise import has_brand
from praman.events import validate_event
from praman.models import VerdictLabel as V
from praman.tools.fetch import load_cached


def run(lid, mode="agent"):
    events = []
    ctx = run_listing(load_cached(lid), mode, on_event=events.append)
    assert not ctx.failed, events[-1]["data"]
    return ctx, events


def verdict_for(ctx, needle, derived=False):
    hits = [
        c
        for c in ctx.claims
        if needle.lower() in c.quote.lower() and bool(c.derived_from) == derived and c.is_claim
    ]
    assert hits, f"no claim containing {needle!r}: {[c.quote for c in ctx.claims]}"
    return [ctx.verdicts[c.id].label for c in hits]


def tools_in_order(events):
    return [
        e["data"]["tool"] for e in events if e["type"] == "step" and e["data"]["phase"] == "act"
    ]


@pytest.fixture(scope="module", autouse=True)
def _check_fixtures():
    from praman.config import REPLAY_DIR

    for lid in ("L14", "L06", "L08", "L21"):
        assert (REPLAY_DIR / f"{lid}.json").exists(), "run scripts/export_recordings.py"


def test_l14_normal_case():
    ctx, events = run("L14")
    assert verdict_for(ctx, "compostable garbage bags") == [V.BACKED]
    assert verdict_for(ctx, "0% plastic") == [V.CONTRADICTED]
    assert verdict_for(ctx, "industrial composting", derived=True) == [V.NEEDS_REVIEW]
    tools = tools_in_order(events)
    assert tools.index("read_photos") < tools.index("cpcb_lookup")
    lookups = [e["data"] for e in events if e["type"] == "registry_lookup"]
    assert {lk["match"]["s_no"] for lk in lookups if lk["match"]} == {2, 32}
    assert all(0 <= lk["score"] <= 1 for lk in lookups)


def test_l06_failure_case_stops_on_the_pack():
    ctx, events = run("L06")
    assert verdict_for(ctx, "biodegradable") == [V.CONTRADICTED]
    assert verdict_for(ctx, "environment-friendly") == [V.CONTRADICTED]
    pack = [
        e["data"]
        for e in events
        if e["type"] == "evidence" and e["data"]["covers_claim"] == "contradicts"
    ]
    assert any("PE Virgin Grade" in e["detail"] and e["photo_index"] == 3 for e in pack)
    assert "cpcb_lookup" not in tools_in_order(events)


def test_l08_ambiguous_case():
    ctx, _ = run("L08")
    assert set(verdict_for(ctx, "plastic-free")) == {V.CONTRADICTED}
    assert V.CONTRADICTED in verdict_for(ctx, "zero waste")
    assert V.PARTLY in verdict_for(ctx, "bamboo handle")


def test_l21_not_a_claim_without_tool_calls():
    ctx, events = run("L21")
    assert ctx.claims and all(not c.is_claim for c in ctx.claims)
    assert all(v.label == V.NOT_A_CLAIM for v in ctx.verdicts.values())
    assert set(tools_in_order(events)) <= {"extract_claims", "match_rule"}


def test_baseline_misses_photo_and_registry_proof():
    ctx, events = run("L14", "baseline")
    assert verdict_for(ctx, "compostable garbage bags") == [V.NOT_BACKED]
    assert not any("0% plastic" in c.quote for c in ctx.claims)  # printed only on the box
    assert set(tools_in_order(events)) <= {"extract_claims", "match_rule", "search_text"}


@pytest.mark.parametrize("lid", ["L14", "L06", "L08", "L21"])
def test_event_stream_is_valid_ordered_and_anonymised(lid):
    _, events = run(lid)
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    for e in events:
        validate_event(e)
    assert not has_brand(json.dumps(events, ensure_ascii=False))
    # Within a claim: plan → act → (tool events, evidence) → observe … → decide → verdict
    last_phase: dict[str, str] = {}
    for e in events:
        d = e["data"]
        if e["type"] == "step" and d["claim_id"]:
            prev = last_phase.get(d["claim_id"])
            if d["phase"] == "act":
                assert prev == "plan", (lid, d)
            if d["phase"] == "observe" and d["tool"] != "read_photos":
                assert prev in ("act", "observe"), (lid, d)
            last_phase[d["claim_id"]] = d["phase"]
        if e["type"] == "verdict":
            assert last_phase.get(d["claim_id"]) == "decide", (lid, d["claim_id"])
