import pytest
from pydantic import BaseModel, ValidationError

from praman import db, llm
from praman.events import EventSink, load_events, validate_event


def test_event_sink_numbers_masks_validates_and_stores():
    seen = []
    sink = EventSink(
        "R1", on_event=seen.append, mask=lambda d: {**d, "message": d["message"].upper()}
    )
    sink.emit("error", {"message": "plain words", "recoverable": True})
    sink.emit("error", {"message": "again", "recoverable": False})
    assert [e["seq"] for e in seen] == [1, 2]
    assert seen[0]["data"]["message"] == "PLAIN WORDS"
    stored = load_events("R1")
    assert stored == seen
    assert load_events("R1", after_seq=1) == seen[1:]


def test_bad_event_is_rejected():
    with pytest.raises(ValidationError):
        validate_event(
            {"seq": 1, "t_ms": 0, "type": "verdict", "run_id": "R", "data": {"label": "Great"}}
        )
    with pytest.raises(ValidationError):
        validate_event({"seq": 1, "t_ms": 0, "type": "nope", "run_id": "R", "data": {}})


def test_step_preview_is_capped():
    ok = {
        "run_id": "R",
        "claim_id": None,
        "n": 1,
        "phase": "act",
        "tool": "x",
        "summary": "s",
        "ms": 0,
    }
    validate_event(
        {
            "seq": 1,
            "t_ms": 0,
            "type": "step",
            "run_id": "R",
            "data": ok | {"payload_preview": "x" * 300},
        }
    )
    with pytest.raises(ValidationError):
        validate_event(
            {
                "seq": 1,
                "t_ms": 0,
                "type": "step",
                "run_id": "R",
                "data": ok | {"payload_preview": "x" * 301},
            }
        )


class Out(BaseModel):
    answer: str


def test_offline_miss_raises_and_replay_hit_serves(monkeypatch):
    with pytest.raises(llm.ReplayMiss):
        llm.call("plan_next", Out, variables={}, listing_id="T")
    key = llm.cache_key(llm.get_settings().praman_model, "plan_next", llm.render("plan_next"), [])
    llm.cache_put(key, "m", "plan_next", {"answer": "yes"}, 10, 2, "T")
    meter = llm.Meter()
    res = llm.call("plan_next", Out, variables={}, listing_id="T", meter=meter)
    assert res.data.answer == "yes" and res.cached
    assert meter.calls == 1 and meter.cached_calls == 1 and meter.tokens_in == 10
    assert key in llm.used_keys("T")


def test_cache_key_uses_image_ids_not_bytes(tmp_path):
    a = llm.image_ref("L14", 7, "https://cdn/7.jpg", None)
    b = llm.image_ref("L14", 7, "https://cdn/7.jpg", "data/cache/images/L14/7.jpg")
    assert a.ident == b.ident
    k1 = llm.cache_key("m", "t", "p", [a.ident])
    assert k1 == llm.cache_key("m", "t", "p", [b.ident]) != llm.cache_key("m", "t", "p", [])


def test_quota_errors_are_recognised():
    class E(Exception):
        code = 429

    assert llm._quota_exhausted(E("Quota exceeded ... Please retry in 16h17m53s."))
    assert not llm._quota_exhausted(E("Too many requests, retry in 30s"))
    db.close_all()


def test_trace_summaries_are_one_short_sentence():
    from praman.run import one_line

    s = one_line(
        "Backed: Both makers printed on the pack are on CPCB's certified list dated 26 Oct 2023 "
        "(S.No. 32: Greendotbiopak, Gujarat and S.No. 2: Sunshield Biotech Llp, Gujarat). More."
    )
    assert (
        s
        == "Backed: Both makers printed on the pack are on CPCB's certified list dated 26 Oct 2023."
    )
    assert one_line("S.No. 32 is listed. Then more.") == "S.No. 32 is listed."
    long = one_line("word " * 60)
    assert len(long) <= 110 and long.endswith("…")
