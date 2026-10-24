"""Groq as the live model: routing, fallbacks and the replay cache (all offline, no keys)."""

import json

import pytest
from pydantic import BaseModel

from praman import llm
from praman.config import Settings


class Answer(BaseModel):
    verdict: str
    notes: list[str] = []


GROQ = "groq:openai/gpt-oss-120b"


BASE = {
    "praman_llm_mode": "live",
    "praman_model": "gemini-test",
    "praman_fallback_model": "",
    "praman_live_model": GROQ,
    "praman_live_vision_model": "",
    "groq_api_key": "gsk-test",
    "gemini_api_key": "gem-test",
}


@pytest.fixture
def use(monkeypatch):
    """use(**changes) swaps in settings built without .env, so the tests don't depend on it."""

    def _use(**changes):
        st = Settings(_env_file=None, **{**BASE, **changes})
        monkeypatch.setattr(llm, "get_settings", lambda: st)
        return st

    monkeypatch.setattr(llm, "render", lambda name, **v: f"prompt for {name}")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    llm._exhausted.clear()
    llm._groq_json_object_only.clear()
    llm._groq_no_reasoning_effort.clear()
    _use()
    return _use


def _reply(obj, usage=(11, 7)):
    return {
        "choices": [{"message": {"content": json.dumps(obj)}}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
    }


def test_text_calls_go_to_groq_and_cache_under_the_recorded_key(use, monkeypatch):
    sent = []

    def post(payload):
        sent.append(payload)
        return _reply({"verdict": "ok"})

    monkeypatch.setattr(llm, "_groq_post", post)
    out = llm.call("extract_claims", Answer, listing_id="Lx")
    assert (
        out.data.verdict == "ok"
        and out.model == GROQ
        and (out.tokens_in, out.tokens_out) == (11, 7)
    )
    p = sent[0]
    assert p["model"] == "openai/gpt-oss-120b" and p["temperature"] == 0
    assert p["response_format"]["type"] == "json_schema"
    assert p["messages"] == [{"role": "user", "content": "prompt for extract_claims"}]
    assert p["reasoning_effort"] == "medium"
    # The cache key is the one a Gemini-recorded run would use
    assert out.key == llm.cache_key(
        "gemini-test", "extract_claims", "prompt for extract_claims", []
    )
    use(praman_llm_mode="replay")
    monkeypatch.setattr(llm, "_groq_post", lambda payload: pytest.fail("a cached call went live"))
    again = llm.call("extract_claims", Answer, listing_id="Lx")
    assert again.cached and again.data.verdict == "ok"


def test_short_calls_ask_for_low_reasoning(use, monkeypatch):
    sent = []
    monkeypatch.setattr(llm, "_groq_post", lambda p: sent.append(p) or _reply({"verdict": "ok"}))
    llm.call("plan_next", Answer)
    llm.call("write_rewrite", Answer)
    assert [p["reasoning_effort"] for p in sent] == ["low", "low"]


def test_the_log_says_why_groq_failed(use, monkeypatch, caplog):
    from praman.llm import GroqError

    def fake_live(model, prompt, schema, images, template=""):
        if model == GROQ:
            raise GroqError(401, "Groq 401: invalid_api_key")
        return {"verdict": "ok"}, 1, 1

    monkeypatch.setattr(llm, "_live_call", fake_live)
    with caplog.at_level("WARNING", logger="praman.llm"):
        llm.call("extract_claims", Answer)
    assert "invalid_api_key" in caplog.text and "trying gemini-test" in caplog.text


def test_groq_failure_falls_back_to_gemini(use, monkeypatch):
    from praman.llm import GroqError

    def fake_live(model, prompt, schema, images, template=""):
        if model == GROQ:
            raise GroqError(503, "Groq 503: over capacity")
        return {"verdict": "from gemini"}, 5, 3

    monkeypatch.setattr(llm, "_live_call", fake_live)
    out = llm.call("extract_claims", Answer)
    assert out.data.verdict == "from gemini" and out.model == "gemini-test"


def test_groq_daily_limit_moves_on_without_retrying(use, monkeypatch):
    from praman.llm import GroqError

    calls = []

    def fake_live(model, prompt, schema, images, template=""):
        calls.append(model)
        if model == GROQ:
            raise GroqError(429, "Groq 429: Rate limit reached on tokens per day (TPD)")
        return {"verdict": "gemini"}, 1, 1

    monkeypatch.setattr(llm, "_live_call", fake_live)
    assert llm.call("extract_claims", Answer).model == "gemini-test"
    assert calls == [GROQ, "gemini-test"]  # a daily limit isn't retried
    assert GROQ in llm._exhausted


def test_schema_rejection_retries_in_json_mode_with_the_schema_in_the_prompt(use, monkeypatch):
    from praman.llm import GroqError

    sent = []

    def post(payload):
        sent.append(payload)
        if payload["response_format"]["type"] == "json_schema":
            raise GroqError(400, "Groq 400: json_schema is not supported by this model")
        return {"choices": [{"message": {"content": '```json\n{"verdict": "ok"}\n```'}}]}

    monkeypatch.setattr(llm, "_groq_post", post)
    out = llm.call("extract_claims", Answer)
    assert out.data.verdict == "ok"
    assert [p["response_format"]["type"] for p in sent] == ["json_schema", "json_object"]
    assert "JSON Schema" in sent[1]["messages"][0]["content"]
    sent.clear()
    llm.call("plan_next", Answer)  # remembered: no second schema attempt
    assert [p["response_format"]["type"] for p in sent] == ["json_object"]


def test_unsupported_reasoning_effort_is_dropped(use, monkeypatch):
    from praman.llm import GroqError

    sent = []

    def post(payload):
        sent.append(payload)
        if "reasoning_effort" in payload:
            raise GroqError(400, "Groq 400: unknown parameter reasoning_effort")
        return _reply({"verdict": "ok"})

    monkeypatch.setattr(llm, "_groq_post", post)
    assert llm.call("extract_claims", Answer).data.verdict == "ok"
    assert "reasoning_effort" not in sent[-1]


def test_photo_calls_stay_on_gemini_unless_a_vision_model_is_set(use, monkeypatch, tmp_path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")
    refs = [llm.ImageRef(f"L#{i}#u", img, f"Photo {i}:") for i in range(2)]
    assert llm._model_chain(refs) == ["gemini-test"]
    use(praman_live_vision_model="groq:qwen/qwen3.8-27b")
    assert llm._model_chain(refs) == ["groq:qwen/qwen3.8-27b", "gemini-test"]
    many = refs + [llm.ImageRef(f"L#{i}#u", img) for i in range(2, 5)]
    assert llm._model_chain(many) == ["gemini-test"]  # more photos than Groq accepts


def test_groq_sends_photos_as_data_urls(use, monkeypatch, tmp_path):
    from PIL import Image

    path = tmp_path / "p.jpg"
    Image.new("RGB", (40, 30), "white").save(path)
    use(praman_live_vision_model="groq:qwen/qwen3.8-27b")
    sent = []
    monkeypatch.setattr(llm, "_groq_post", lambda p: sent.append(p) or _reply({"verdict": "ok"}))
    llm.call("read_photos", Answer, images=[llm.ImageRef("L#1#u", path, "Photo 1:")])
    parts = sent[0]["messages"][0]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "text"]
    assert parts[0]["text"] == "Photo 1:"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_a_groq_model_without_a_key_is_skipped(use, monkeypatch):
    use(groq_api_key="")
    assert llm._model_chain([]) == ["gemini-test"]


def test_without_a_live_model_nothing_changes(use):
    use(praman_live_model="", praman_fallback_model="gemini-lite")
    assert llm._model_chain([]) == ["gemini-test", "gemini-lite"]
    assert llm._provider("gemini-test") == "gemini"


def test_reasoning_effort_can_be_turned_down(use, monkeypatch):
    use(praman_groq_reasoning="low")
    sent = []
    monkeypatch.setattr(llm, "_groq_post", lambda p: sent.append(p) or _reply({"verdict": "ok"}))
    llm.call("extract_claims", Answer)
    assert sent[0]["reasoning_effort"] == "low"


def test_judging_evidence_follows_the_reasoning_setting(use, monkeypatch):
    sent = []
    monkeypatch.setattr(llm, "_groq_post", lambda p: sent.append(p) or _reply({"verdict": "ok"}))
    use(praman_groq_reasoning="medium")
    llm.call("judge_evidence", Answer)
    use(praman_groq_reasoning="high")
    llm.call("judge_evidence", Answer)
    assert [p["reasoning_effort"] for p in sent] == ["medium", "high"]


class Pages(BaseModel):
    photos: list[str]


def _photo_files(tmp_path, n):
    from PIL import Image

    refs = []
    for i in range(1, n + 1):
        path = tmp_path / f"{i}.jpg"
        Image.new("RGB", (40, 30), "white").save(path)
        refs.append(llm.ImageRef(f"L#{i}#u", path, f"Photo {i}:"))
    return refs


def test_more_photos_than_groq_takes_are_split_into_groups_and_joined(use, monkeypatch, tmp_path):
    use(praman_live_vision_model="groq:qwen/qwen3.8-27b")
    sent = []

    def post(payload):
        parts = payload["messages"][0]["content"]
        labels = [p["text"] for p in parts if p["type"] == "text" and p["text"].startswith("Photo")]
        sent.append((len(labels), parts[-1]["text"]))
        return _reply({"photos": labels})

    monkeypatch.setattr(llm, "_groq_post", post)
    out = llm.call("read_photos", Pages, images=_photo_files(tmp_path, 5))
    assert out.model == "groq:qwen/qwen3.8-27b"
    assert sorted(out.data.photos) == [f"Photo {i}:" for i in range(1, 6)]  # all five, once each
    assert sorted(n for n, _ in sent) == [2, 3]
    assert all("shows only some of the photos" in text for _, text in sent)
    assert (out.tokens_in, out.tokens_out) == (22, 14)  # both requests are counted


def test_three_photos_or_fewer_are_one_request_without_the_note(use, monkeypatch, tmp_path):
    use(praman_live_vision_model="groq:qwen/qwen3.8-27b")
    sent = []
    monkeypatch.setattr(llm, "_groq_post", lambda p: sent.append(p) or _reply({"photos": ["a"]}))
    llm.call("read_photos", Pages, images=_photo_files(tmp_path, 3))
    assert len(sent) == 1
    assert "shows only some" not in sent[0]["messages"][0]["content"][-1]["text"]


def test_an_answer_that_cant_be_joined_stays_on_gemini_for_many_photos(use, tmp_path):
    use(praman_live_vision_model="groq:qwen/qwen3.8-27b")
    many = _photo_files(tmp_path, 5)
    assert llm._model_chain(many, "read_photos", Pages) == [
        "groq:qwen/qwen3.8-27b",
        "gemini-test",
    ]
    assert llm._model_chain(many, "read_photos", Answer) == ["gemini-test"]  # not all lists


def test_short_calls_use_the_short_model_then_the_main_one(use):
    short = "groq:llama-3.3-70b-versatile"
    use(praman_live_short_model=short)
    assert llm._model_chain([], "plan_next") == [short, GROQ, "gemini-test"]
    assert llm._model_chain([], "write_rewrite") == [short, GROQ, "gemini-test"]
    assert llm._model_chain([], "judge_evidence") == [GROQ, "gemini-test"]  # heavy calls stay


def test_retries_wait_as_long_as_the_provider_asks():
    msg = "Groq 429: Rate limit reached ... Please try again in 1.777499999s. Need more tokens?"
    assert llm._retry_delay(RuntimeError(msg), 0) == pytest.approx(2.03, abs=0.01)
    assert llm._retry_delay(RuntimeError("try again in 250ms"), 2) == pytest.approx(0.5)
    assert llm._retry_delay(RuntimeError("Please retry in 90s"), 0) == 12.0  # capped
    assert 2.0 <= llm._retry_delay(RuntimeError("boom"), 0) < 3.0  # no hint: backoff as before


def test_a_stuck_groq_call_gives_way_to_gemini_after_one_attempt(use, monkeypatch):
    import types

    import httpx

    clock = [0.0]
    monkeypatch.setattr(
        llm, "time", types.SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: None)
    )
    calls = []

    def fake_live(model, prompt, schema, images, template=""):
        calls.append(model)
        if model == GROQ:
            clock[0] += 20.0  # the request waited out its 20 s timeout
            raise httpx.ReadTimeout("no answer in 20 s")
        return {"verdict": "gemini"}, 1, 1

    monkeypatch.setattr(llm, "_live_call", fake_live)
    out = llm.call("extract_claims", Answer)
    assert out.model == "gemini-test"
    assert calls == [GROQ, "gemini-test"]  # a second 20 s attempt would have broken the 30 s budget


def test_quick_rate_limit_answers_are_still_retried(use, monkeypatch):
    from praman.llm import GroqError

    calls = []

    def fake_live(model, prompt, schema, images, template=""):
        calls.append(model)
        if len(calls) == 1:
            raise GroqError(429, "Groq 429: Rate limit ... Please try again in 1.5s.")
        return {"verdict": "ok"}, 1, 1

    monkeypatch.setattr(llm, "_live_call", fake_live)
    assert llm.call("extract_claims", Answer).model == GROQ  # retried once, then answered
    assert calls == [GROQ, GROQ]


def test_a_photo_call_falls_back_when_the_first_gemini_model_fails(use, monkeypatch, tmp_path):
    from praman.llm import LLMError

    use(praman_live_model="", praman_fallback_model="gemini-lite")
    calls = []

    def fake_live(model, prompt, schema, images, template=""):
        calls.append(model)
        if model == "gemini-test":
            raise LLMError("Model call failed: ServerError: 503")  # not a quota error
        return {"photos": ["ok"]}, 1, 1

    monkeypatch.setattr(llm, "_live_call", fake_live)
    out = llm.call("read_photos", Pages, images=_photo_files(tmp_path, 2))
    assert out.model == "gemini-lite" and calls == ["gemini-test", "gemini-lite"]
