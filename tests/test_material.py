"""check_material: with no certificate, the material printed on the product can back a claim when
Google Search-grounded sources say it has the property. Code decides when it applies (never for
plastics) and what the answer is worth. Offline: the search answer is stubbed or faked."""

import pytest
from helpers import claim, ev, listing

from praman import agent, llm, store
from praman.agent import run_listing
from praman.models import MaterialCheckOut, WebSource
from praman.models import VerdictLabel as V
from praman.tools import material as m
from praman.tools.fetch import load_cached
from praman.verdict import ClaimState, decide_verdict

GLASSINE = [m.MaterialLine("COMPOSITION: Glassine paper", "photo 3", 3)]
SOURCES = [WebSource(title="wikipedia.org", url="https://en.wikipedia.org/wiki/Glassine")]


def decide(c, evidence, searched=("text", "photos", "material")):
    st = ClaimState(claim=c, rule_ids=c.rule_ids, evidence=list(evidence), searched=list(searched))
    return decide_verdict(st)


def mat_ev(covers="yes", claim_id="C1"):
    return ev(
        claim_id=claim_id,
        source="web",
        kind="material_check",
        covers_claim=covers,
        detail="Material: glassine paper — made from wood pulp. Sources: wikipedia.org.",
        note="Glassine paper (photo 3) is biodegradable according to public sources (wikipedia.org).",
    )


# -- the decision row ---------------------------------------------------------


def test_material_backs_a_vague_claim_without_a_certificate():
    c = claim("ECO FRIENDLY", "vague", rule_ids=["R01"])
    qual = ev(source="photo", kind="qualifier", covers_claim="partly", detail="Photo 3: Glassine")
    d = decide(c, [qual, mat_ev()])
    assert d.verdict.label == V.BACKED
    assert d.verdict.reason.startswith("Backed on its material, not a certificate: glassine paper")
    assert set(d.verdict.evidence_ids) == {qual.id, d.verdict.evidence_ids[-1]}
    assert d.verdict.missing is None


def test_material_wins_over_an_off_site_qr_code():
    c = claim("biodegradable paper substances", rule_ids=["R02"])
    qr = ev(source="photo", kind="qr_link", covers_claim="no", detail="QR code links to x.com")
    assert decide(c, [qr]).verdict.label == V.NEEDS_REVIEW
    assert decide(c, [qr, mat_ev()]).verdict.label == V.BACKED


@pytest.mark.parametrize("rule", ["R07", "R09", "R05", "R06"])
def test_material_never_stands_in_for_plastic_or_comparison_rules(rule):
    c = claim("compostable bag", rule_ids=["R02", rule])
    assert decide(c, [mat_ev()]).verdict.label != V.BACKED


def test_contradiction_still_wins():
    c = claim("plastic-free", rule_ids=["R02"])
    con = ev(source="photo", covers_claim="contradicts", note="Pack lists polyethylene.")
    assert decide(c, [mat_ev(), con]).verdict.label == V.CONTRADICTED


def test_partial_material_answer_is_only_partial_support():
    c = claim("biodegradable", rule_ids=["R02"])
    assert decide(c, [mat_ev("partly")]).verdict.label == V.PARTLY


def test_unclear_scope_isnt_backed_by_material():
    c = claim("biodegradable", scope="unclear", rule_ids=["R02"])
    assert decide(c, [mat_ev()]).verdict.label != V.BACKED


# -- when the check applies (code decides) -------------------------------------


def test_applies_to_a_paper_product():
    c = claim("biodegradable paper", rule_ids=["R02"])
    assert m.applies(c, c.rule_ids, GLASSINE, ["biodegradable"], [c]) == ""


@pytest.mark.parametrize(
    "text",
    [
        "Made from PLA and PBAT",
        "Made from non-woven laminated fabric",
        "Composition: paper with polyethylene lining",
        "Made from 30% wheat straw",
    ],
)
def test_plastic_and_blends_dont_qualify(text):
    c = claim("biodegradable", rule_ids=["R02"])
    lines = [m.MaterialLine(text, "description")]
    assert m.applies(c, c.rule_ids, lines, ["biodegradable"], [c]) != ""


def test_plastic_free_wording_isnt_read_as_plastic():
    assert not m.is_plastic([m.MaterialLine("100% plastic-free kraft paper", "description")])


def test_a_page_under_the_plastic_rules_gets_no_material_fallback():
    vague = claim("eco friendly", "vague", rule_ids=["R01"])
    bag = claim("compostable bags", id_="C2", rule_ids=["R02", "R07"])
    lines = [m.MaterialLine("Made with 100% cornstarch", "photo 3", 3)]
    assert "plastic rules" in m.applies(vague, vague.rule_ids, lines, ["compostable"], [vague, bag])


def test_packaging_claims_arent_checked_against_the_product_material():
    c = claim("recyclable", scope="packaging", rule_ids=["R02"])
    assert m.applies(c, c.rule_ids, GLASSINE, ["recyclable"], [c]) != ""


def test_vague_claim_borrows_the_property_the_page_states():
    lst = listing(body="ECO FRIENDLY. Made from biodegradable paper substances.")
    vague = claim("ECO FRIENDLY", "vague", rule_ids=["R01"])
    assert m.claim_properties(vague, lst, [vague]) == ["biodegradable"]
    specific = claim("soft and strong", rule_ids=["R02"])
    assert m.claim_properties(specific, lst, [specific]) == []


def test_material_lines_skip_non_material_based_words():
    lst = listing(body="Works with oil-based removers. Made from areca palm leaves.")
    assert [ln.text for ln in m.material_lines(lst, None)] == ["Made from areca palm leaves."]


def test_a_yes_without_grounded_sources_counts_only_as_partly():
    out = MaterialCheckOut(material="x", property="biodegradable", answer="yes", summary="s")
    assert m.covers(out) == "partly"
    out.sources = SOURCES
    assert m.covers(out) == "yes"


# -- the web-search call -------------------------------------------------------


def _search_env(monkeypatch, live="groq:openai/gpt-oss-120b", search="", key="x"):
    """Settings built by hand, so the developer's own .env can't change what a test sees."""
    from praman.config import Settings

    st = Settings(
        _env_file=None,
        praman_live_model=live,
        praman_search_models=search,
        groq_api_key=key,
        praman_model="gemini-3.8-flash",
        praman_fallback_model="gemini-3.5-flash-lite",
    )
    monkeypatch.setattr(llm, "get_settings", lambda: st)


def test_web_search_is_groq_only_and_never_gemini(monkeypatch):
    _search_env(monkeypatch)
    assert llm._model_chain([], "check_material") == ["groq:openai/gpt-oss-120b"]
    with pytest.raises(llm.LLMError, match="Groq browser search only"):
        llm._live_call("gemini-3.8-flash", "p", MaterialCheckOut, [], "check_material")


def test_search_models_are_tried_in_the_order_listed(monkeypatch):
    _search_env(
        monkeypatch,
        search="groq:openai/gpt-oss-20b, groq:openai/gpt-oss-120b, groq:openai/gpt-oss-20b",
    )
    assert llm._model_chain([], "check_material") == [
        "groq:openai/gpt-oss-20b",
        "groq:openai/gpt-oss-120b",
    ]


@pytest.mark.parametrize(
    ("live", "key"),
    [("groq:llama-3.3-70b-versatile", "x"), ("", "x"), ("groq:openai/gpt-oss-120b", "")],
)
def test_no_search_model_or_key_is_a_plain_error_not_a_gemini_call(monkeypatch, live, key):
    _search_env(monkeypatch, live=live, key=key)
    with pytest.raises(llm.LLMError, match="needs a Groq model with browser search"):
        llm._model_chain([], "check_material")


def test_other_calls_keep_their_gemini_fallbacks(monkeypatch):
    _search_env(monkeypatch)
    chain = llm._model_chain([], "judge_evidence")
    assert chain[0] == "groq:openai/gpt-oss-120b" and any(not m.startswith("groq:") for m in chain)


def test_groq_search_takes_sources_from_executed_tools(monkeypatch):
    body = {
        "choices": [
            {
                "message": {
                    "content": 'Sure. {"material": "glassine paper", "material_line": 1, '
                    '"property": "biodegradable", "answer": "yes", "summary": "Uncoated glassine '
                    'is biodegradable【1†L14-L17】.", "caveat": null}',
                    "executed_tools": [
                        {
                            "type": "browser_search",
                            "arguments": '{"query": "glassine paper biodegradable"}',
                            "search_results": {
                                "results": [
                                    {
                                        "title": "What is Glassine?",
                                        "url": "https://www.ecoenclose.com/b",
                                    },
                                    {"title": "dup", "url": "https://www.ecoenclose.com/b"},
                                ]
                            },
                        },
                        {
                            "type": "browser.open",
                            "search_results": {"results": [{"url": "https://x"}]},
                        },
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    monkeypatch.setattr(llm, "_groq_post", lambda payload: body)
    data, tin, tout = llm._groq_search_call("groq:openai/gpt-oss-120b", "p", MaterialCheckOut)
    assert data["sources"] == [
        {"title": "What is Glassine?", "url": "https://www.ecoenclose.com/b"}
    ]
    assert data["queries"] == ["glassine paper biodegradable"]
    assert "【" not in data["summary"] and (tin, tout) == (7, 3)
    out = MaterialCheckOut.model_validate(data)
    assert m.source_domains(out) == ["ecoenclose.com"]


# -- end to end (L07: a paper toilet-seat cover; the pack prints "COMPOSITION: Glassine paper") --


def _stub(answer="yes", sources=SOURCES):
    calls = []

    def fake(lines, prop, lst, meter=None):
        calls.append((prop, [ln.text for ln in lines]))
        return MaterialCheckOut(
            material="glassine paper",
            material_line=1,
            property=prop,
            answer=answer,
            summary="Glassine paper is made from wood pulp and breaks down like ordinary paper.",
            sources=sources,
        )

    return fake, calls


def test_l07_claims_are_backed_on_their_material(monkeypatch):
    fake, calls = _stub()
    monkeypatch.setattr(agent, "check_material", fake)
    events: list[dict] = []
    ctx = run_listing(load_cached("L07"), "agent", on_event=events.append)
    assert {cid: v.label for cid, v in ctx.verdicts.items()} == {"C1": V.BACKED, "C2": V.BACKED}
    # one search for the whole page, shared by both claims
    assert len(calls) == 1 and calls[0][0] == "biodegradable"
    assert calls[0][1][0] == "COMPOSITION: Glassine paper"
    web = [e for e in ctx.evidence if e.source == "web"]
    assert {e.claim_id for e in web} == {"C1", "C2"}
    assert all(e.kind == "material_check" and "wikipedia.org" in e.detail for e in web)
    for v in ctx.verdicts.values():
        assert v.reason.startswith("Backed on its material, not a certificate")
        assert any(e.id in v.evidence_ids for e in web)
        assert "material" in v.sources_searched
    assert any(e["type"] == "evidence" and e["data"]["source"] == "web" for e in events)


def test_l07_without_sources_keeps_the_old_verdicts(monkeypatch):
    fake, _ = _stub(sources=[])
    monkeypatch.setattr(agent, "check_material", fake)
    ctx = run_listing(load_cached("L07"), "agent")
    assert V.BACKED not in {v.label for v in ctx.verdicts.values()}


def test_l07_when_search_is_unavailable(monkeypatch):
    def fail(*a, **kw):
        raise llm.LLMError("Google Search isn't enabled for this Gemini key (gemini-x)")

    monkeypatch.setattr(agent, "write_rewrites", lambda *a, **k: {})  # wording is live-only here
    monkeypatch.setattr(agent, "check_material", fail)
    ctx = run_listing(load_cached("L07"), "agent")
    assert not ctx.failed
    assert V.BACKED not in {v.label for v in ctx.verdicts.values()}
    # Nothing was searched, so no claim may say it was, or be called "not backed" for it
    for v in ctx.verdicts.values():
        assert "material" not in v.sources_searched
        assert "public sources" not in v.reason
        assert v.label in (V.NEEDS_REVIEW, V.PARTLY), (
            v
        )  # never "Not backed" for a search that didn't run
    open_ = [v for v in ctx.verdicts.values() if v.label == V.NEEDS_REVIEW]
    assert open_ and all(
        "couldn't run" in v.reason and "a person should confirm" in v.reason for v in open_
    )


def test_a_failed_material_check_is_tried_once_and_the_trace_says_so(monkeypatch):
    calls = []

    def fail(*a, **kw):
        calls.append(a)
        raise llm.LLMError("Daily quota used up for groq:openai/gpt-oss-120b")

    monkeypatch.setattr(agent, "write_rewrites", lambda *a, **k: {})  # wording is live-only here
    monkeypatch.setattr(agent, "check_material", fail)
    ctx = run_listing(load_cached("L07"), "agent")
    assert len(calls) == 1  # one failed search for the whole page, not one per claim
    steps = [
        s for s in store.steps(ctx.run_id) if s.tool == "check_material" and s.phase == "observe"
    ]
    assert steps and all(s.summary.startswith("Couldn't run the material check") for s in steps)


def test_baseline_mode_never_checks_material(monkeypatch):
    fake, calls = _stub()
    monkeypatch.setattr(agent, "check_material", fake)
    run_listing(load_cached("L07"), "baseline")
    assert calls == []


@pytest.mark.parametrize(
    ("quote", "prop"),
    [
        ("Feature_Compostable", "compostable"),
        ("Feature_Biodegradable", "biodegradable"),
        ("Compostable", "compostable"),
        ("completely biodegradable", "biodegradable"),
        ("Plastic-Free", "plastic-free"),
        ("plastic_free", "plastic-free"),
    ],
)
def test_tag_style_claims_name_their_property(quote, prop):
    from tests.helpers import claim, listing

    assert m.claim_properties(claim(quote), listing(), []) == [prop]


def test_a_model_timeout_in_the_last_steps_keeps_the_verdicts(monkeypatch):
    """Consistency and rewording run after every verdict is decided: a timeout there leaves the
    run finished (so the report can be signed), with the trace saying what didn't run."""

    def timeout(*a, **kw):
        raise llm.LLMError("Model call failed: ReadTimeout: The read operation timed out")

    fake, _ = _stub()
    monkeypatch.setattr(agent, "check_material", fake)
    monkeypatch.setattr(agent, "model_conflicts", timeout)
    monkeypatch.setattr(agent, "write_rewrites", timeout)
    events: list[dict] = []
    ctx = run_listing(load_cached("L07"), "agent", on_event=events.append)
    assert not ctx.failed and events[-1]["type"] == "run_finished"
    assert not any(e["type"] == "error" for e in events)
    steps = [s.summary for s in store.steps(ctx.run_id)]
    assert any("only the checks in code ran" in t for t in steps)
    assert any("no suggested wording" in t for t in steps)


def test_a_search_call_gets_a_longer_timeout_than_an_ordinary_groq_call(monkeypatch):
    """A browser search reads several pages (about 25 s); the 20 s limit for ordinary Groq calls
    made the second search model time out every time."""
    seen: dict = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": []}

    def post(url, json, headers, timeout):
        seen["timeout"] = timeout.read
        return Reply()

    _search_env(monkeypatch)
    monkeypatch.setattr(llm.httpx, "post", post)
    from praman.config import Settings

    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(_env_file=None, groq_api_key="x", praman_groq_timeout_s=20),
    )
    llm._groq_post({"model": "m", "messages": [], "tools": [{"type": "browser_search"}]})
    assert seen["timeout"] == llm.GROQ_SEARCH_TIMEOUT_S == 60.0
    llm._groq_post({"model": "m", "messages": []})
    assert seen["timeout"] == 20.0
    assert llm._request_timeout("groq:openai/gpt-oss-20b", "check_material") == 60.0
    assert llm._request_timeout("groq:openai/gpt-oss-20b", "judge_evidence") == 20.0
    assert llm._call_budget("groq:openai/gpt-oss-20b", "check_material") == 75.0
