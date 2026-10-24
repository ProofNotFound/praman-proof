"""Model client (Gemini, optionally Groq first) with retries, fallbacks and a record/replay cache
(TRD §11).

Every model call in Praman goes through `call()`. The cache key is the SHA-256 of
(model, template name, rendered prompt, image identifiers), where the model is always
`praman_model`, whichever provider answers a live call: recorded runs keep replaying when the
live model changes. Image bytes are never part of the key, so tests and CI replay without the
gitignored photo files.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import get_origin

import httpx
from PIL import Image
from pydantic import BaseModel, ValidationError

from praman import db
from praman.config import PROMPTS_DIR, REPLAY_DIR, ROOT, get_settings

log = logging.getLogger(__name__)


MAX_IMAGE_EDGE = 2048
RETRIES = 3
# Most one model gets for one call, retries included: a slow or stuck model gives way to the next
# one instead of keeping the check waiting for minutes.
GROQ_CALL_BUDGET_S = 30.0
# A browser-search call reads several web pages: about 25 s in practice, so it gets a longer
# request timeout and retry budget than an ordinary Groq call.
GROQ_SEARCH_TIMEOUT_S = 60.0
GROQ_SEARCH_BUDGET_S = 75.0
GEMINI_CALL_BUDGET_S = 75.0
GROQ_PREFIX = "groq:"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MAX_IMAGES = 3  # Groq's vision models take at most 3 images per request (5 on one preview)
GROQ_IMAGE_EDGE = 1600


class ReplayMiss(RuntimeError):
    """Offline mode and no recorded response for this exact call."""


class LLMError(RuntimeError):
    """The model call failed after retries (and the fallback, when allowed)."""


@dataclass
class ImageRef:
    """An image sent to the model. `ident` goes into the cache key; `path` is read only when live."""

    ident: str  # e.g. "L14#7#https://cdn…/7.jpg"
    path: Path | None
    label: str = ""  # text placed before the image, e.g. "Photo 7:"


@dataclass
class Meter:
    """Per-run usage counters."""

    calls: int = 0
    cached_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    ms: int = 0
    by_template: dict[str, int] = field(default_factory=dict)

    def cost_inr(self) -> float:
        s = get_settings()
        return round(
            self.tokens_in / 1e6 * s.praman_price_in_per_m_inr
            + self.tokens_out / 1e6 * s.praman_price_out_per_m_inr,
            4,
        )


@dataclass
class LLMResult[T]:
    data: T
    tokens_in: int
    tokens_out: int
    cached: bool
    model: str
    ms: int
    key: str


# ---------------------------------------------------------------------------
# Prompt templates


def load_template(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def render(name: str, **variables: object) -> str:
    text = load_template(name)
    # Drop the leading schema comment line from what the model sees
    lines = text.splitlines()
    if lines and lines[0].startswith("<!--"):
        text = "\n".join(lines[1:]).lstrip("\n")
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# ---------------------------------------------------------------------------
# Cache

_replay_lock = threading.Lock()
_replay_rows: dict[str, dict] | None = None
_used: dict[str, set[str]] = {}


def cache_key(model: str, template: str, prompt: str, image_ids: list[str]) -> str:
    blob = json.dumps([model, template, prompt, image_ids], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _replay_index() -> dict[str, dict]:
    global _replay_rows
    with _replay_lock:
        if _replay_rows is None:
            rows: dict[str, dict] = {}
            if REPLAY_DIR.exists():
                for f in sorted(REPLAY_DIR.glob("*.json")):
                    doc = json.loads(f.read_text())
                    for r in doc.get("entries", []):
                        rows[r["key"]] = r
            _replay_rows = rows
        return _replay_rows


def reset_replay_index() -> None:
    global _replay_rows
    with _replay_lock:
        _replay_rows = None


def cache_get(key: str) -> dict | None:
    row = db.query_one(
        "SELECT key, model, template, response_json, tokens_in, tokens_out, listing_id "
        "FROM llm_cache WHERE key = ?",
        (key,),
    )
    if row:
        return row
    return _replay_index().get(key)


def cache_put(
    key: str, model: str, template: str, response: dict, tin: int, tout: int, listing_id: str | None
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO llm_cache (key, model, template, response_json, tokens_in, "
        "tokens_out, created_at, listing_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            model,
            template,
            json.dumps(response, ensure_ascii=False),
            tin,
            tout,
            datetime.now(UTC).isoformat(),
            listing_id,
        ),
    )


def mark_used(listing_id: str | None, key: str) -> None:
    with _replay_lock:
        _used.setdefault(listing_id or "", set()).add(key)


def used_keys(listing_id: str) -> set[str]:
    with _replay_lock:
        return set(_used.get(listing_id, set()))


def export_replay(listing_id: str, path: Path | None = None) -> Path:
    """Write the cache rows this process used for a listing to tests/fixtures/replay/<id>.json."""
    keys = sorted(used_keys(listing_id))
    entries = []
    for k in keys:
        row = cache_get(k)
        if row:
            entries.append(
                {
                    "key": row["key"],
                    "model": row["model"],
                    "template": row["template"],
                    "response_json": row["response_json"],
                    "tokens_in": row["tokens_in"],
                    "tokens_out": row["tokens_out"],
                    "listing_id": row.get("listing_id") or listing_id,
                }
            )
    path = path or REPLAY_DIR / f"{listing_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"listing_id": listing_id, "model": get_settings().praman_model, "entries": entries}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    reset_replay_index()
    return path


# ---------------------------------------------------------------------------
# Live calls

_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            from google import genai

            s = get_settings()
            if not s.has_api_key:
                raise LLMError("No GEMINI_API_KEY configured")
            _client = genai.Client(api_key=s.gemini_api_key)
        return _client


def _image_part(path: Path):
    from google.genai import types

    img = Image.open(path)
    img = img.convert("RGB")
    if max(img.size) > MAX_IMAGE_EDGE:
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


class QuotaReached(LLMError):
    """The model kept answering with a quota or rate-limit error (HTTP 429) after every retry.
    The agent finishes the run cleanly: unchecked claims become Needs review."""


class QuotaExhausted(QuotaReached):
    """The model's daily quota is used up; retrying won't help until it resets."""


def _rate_limited(e: Exception | None) -> bool:
    if e is None:
        return False
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return code == 429 or bool(re.search(r"RESOURCE_EXHAUSTED|rate.?limit|quota", str(e), re.I))


_exhausted: set[str] = set()  # models whose daily quota ran out in this process


def _quota_exhausted(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    msg = str(e)
    return code == 429 and bool(re.search(r"retry in \d+h|PerDay|per day", msg, re.I))


def _retryable(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in (408, 429, 500, 502, 503, 504):
        return True
    name = type(e).__name__.lower()
    return any(s in name for s in ("timeout", "connect", "remoteprotocol", "readerror"))


# Short structured answers don't need long thinking; it only adds seconds. Not part of the key.
LOW_THINKING = {"plan_next", "judge_evidence", "write_rewrite"}
# Calls answered with a web search go to Groq's built-in browser search (gpt-oss models) and
# nowhere else: Gemini's Google Search needs a billed project for Gemini 3 models, which this
# key doesn't have. The sources come from what the search tool returned, never the model's text,
# and are stored with the answer, so replay shows the same sources.
SEARCH_TEMPLATES = {"check_material"}
GROQ_SEARCH_PREFIX = GROQ_PREFIX + "openai/gpt-oss"  # Groq models with the browser_search tool
_no_thinking_level: set[str] = set()  # models that rejected a thinking level


def _live_call(
    model: str, prompt: str, schema: type[BaseModel], images: list[ImageRef], template: str = ""
) -> tuple[dict, int, int]:
    if _provider(model) == "groq" and template in SEARCH_TEMPLATES:
        return _groq_search_call(model, prompt, schema)
    if _provider(model) == "groq":
        return _groq_call(model, prompt, schema, images, template)
    if template in SEARCH_TEMPLATES:
        raise LLMError(f"Web search runs on Groq browser search only, not on {model}")
    from google.genai import types

    s = get_settings()
    client = _get_client()
    contents: list = []
    for im in images:
        if im.label:
            contents.append(im.label)
        if im.path is None or not im.path.exists():
            raise LLMError(f"Image not available locally: {im.ident.split('#')[0]} photo")
        contents.append(_image_part(im.path))
    contents.append(prompt)
    thinking = None
    if template in LOW_THINKING and model not in _no_thinking_level:
        thinking = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=thinking,
        http_options=types.HttpOptions(timeout=s.praman_timeout_s * 1000),
    )
    try:
        resp = client.models.generate_content(model=model, contents=contents, config=config)
    except Exception as e:  # noqa: BLE001
        if thinking is None or "thinking" not in str(e).lower():
            raise
        _no_thinking_level.add(model)
        config.thinking_config = None
        resp = client.models.generate_content(model=model, contents=contents, config=config)
    text = resp.text or ""
    data = json.loads(text)
    schema.model_validate(data)  # raise early on a malformed answer
    um = resp.usage_metadata
    tin = (um.prompt_token_count or 0) if um else 0
    tout = ((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0
    return data, tin, tout


def _json_object(text: str) -> dict:
    """The JSON object in a reply that may have words or citation marks around it."""
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1] if 0 <= start < end else text)


CITATION_MARK = re.compile(r"【[^】]*】")


def _groq_search_call(model: str, prompt: str, schema: type[BaseModel]) -> tuple[dict, int, int]:
    """A Groq gpt-oss call with its built-in browser search. `sources` are the pages the search
    returned (executed_tools), `queries` what it searched for."""
    body = _groq_post(
        {
            "model": model.removeprefix(GROQ_PREFIX),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "tools": [{"type": "browser_search"}],
            "tool_choice": "required",
        }
    )
    msg = (body.get("choices") or [{}])[0].get("message", {})
    data = _json_object(CITATION_MARK.sub("", msg.get("content") or ""))
    sources: list[dict] = []
    queries: list[str] = []
    for tool in msg.get("executed_tools") or []:
        if tool.get("type") != "browser_search":
            continue
        args = tool.get("arguments") or ""
        try:
            q = json.loads(args).get("query") if args else None
        except (json.JSONDecodeError, AttributeError):
            q = None
        if q:
            queries.append(str(q))
        for r in (tool.get("search_results") or {}).get("results") or []:
            url = r.get("url") or ""
            if url and all(x["url"] != url for x in sources):
                sources.append({"title": r.get("title") or "", "url": url})
    data["sources"] = sources
    data["queries"] = queries
    schema.model_validate(data)  # raise early on a malformed answer
    usage = body.get("usage") or {}
    return data, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


# ---------------------------------------------------------------------------
# Groq (OpenAI-compatible chat completions over plain HTTP; no extra dependency)


class GroqError(RuntimeError):
    """An error answer from Groq; `status_code` lets the shared retry rules read it."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


# Calls that only pick a tool or reword a sentence think briefly. Judging evidence follows
# PRAMAN_GROQ_REASONING: at "low" the model called unrelated facts partial proof.
GROQ_LOW_REASONING = {"plan_next", "write_rewrite"}
_groq_json_object_only: set[str] = set()  # models that rejected a JSON schema
_groq_no_reasoning_effort: set[str] = set()  # models that rejected reasoning_effort


def _provider(model: str) -> str:
    return "groq" if model.startswith(GROQ_PREFIX) else "gemini"


def _uses_search(payload: dict) -> bool:
    return any(t.get("type") == "browser_search" for t in payload.get("tools") or [])


def _groq_post(payload: dict) -> dict:
    """One chat completions request. Tests replace this."""
    s = get_settings()
    if not s.has_groq_key:
        raise LLMError("No GROQ_API_KEY configured")
    r = httpx.post(
        GROQ_URL,
        json=payload,
        headers={"Authorization": f"Bearer {s.groq_api_key.strip()}"},
        timeout=httpx.Timeout(
            GROQ_SEARCH_TIMEOUT_S if _uses_search(payload) else float(s.praman_groq_timeout_s),
            connect=10.0,
        ),
    )
    if r.status_code >= 400:
        raise GroqError(r.status_code, f"Groq {r.status_code}: {r.text[:300]}")
    return r.json()


def _groq_image_url(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    if max(img.size) > GROQ_IMAGE_EDGE:
        img.thumbnail((GROQ_IMAGE_EDGE, GROQ_IMAGE_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _groq_messages(prompt: str, images: list[ImageRef]) -> list[dict]:
    if not images:
        return [{"role": "user", "content": prompt}]
    parts: list[dict] = []
    for im in images:
        if im.label:
            parts.append({"type": "text", "text": im.label})
        if im.path is None or not im.path.exists():
            raise LLMError(f"Image not available locally: {im.ident.split('#')[0]} photo")
        parts.append({"type": "image_url", "image_url": {"url": _groq_image_url(im.path)}})
    parts.append({"type": "text", "text": prompt})
    return [{"role": "user", "content": parts}]


def _json_from_text(text: str) -> dict:
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


def _all_lists(schema: type[BaseModel]) -> bool:
    """True when every field is a list, so answers for separate photo groups can be joined."""
    fields = schema.model_fields.values()
    return bool(fields) and all(get_origin(f.annotation) is list for f in fields)


def _merge_chunks(parts: list[dict]) -> dict:
    merged = dict(parts[0])
    for part in parts[1:]:
        for key, value in part.items():
            if isinstance(value, list):
                merged[key] = merged.get(key, []) + value
    return merged


def _groq_call(
    model: str, prompt: str, schema: type[BaseModel], images: list[ImageRef], template: str = ""
) -> tuple[dict, int, int]:
    """One request, or, for more photos than Groq accepts, one per group of 3 photos in parallel,
    joined afterwards (each photo is labelled with its own number)."""
    if len(images) <= GROQ_MAX_IMAGES:
        return _groq_single(model, prompt, schema, images, template)
    groups = [images[i : i + GROQ_MAX_IMAGES] for i in range(0, len(images), GROQ_MAX_IMAGES)]
    note = "\n\nThis request shows only some of the photos (the ones labelled above): answer only for them."
    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        results = list(
            pool.map(lambda g: _groq_single(model, prompt + note, schema, g, template), groups)
        )
    data = _merge_chunks([r[0] for r in results])
    schema.model_validate(data)
    return data, sum(r[1] for r in results), sum(r[2] for r in results)


def _groq_single(
    model: str, prompt: str, schema: type[BaseModel], images: list[ImageRef], template: str = ""
) -> tuple[dict, int, int]:
    name = model.removeprefix(GROQ_PREFIX)
    json_schema = schema.model_json_schema()
    body: dict = {}
    for _ in range(3):  # each rejection below removes one option, so this always ends
        as_object = name in _groq_json_object_only
        text = prompt
        if as_object:  # JSON mode only guarantees valid JSON: put the schema in the prompt
            text += "\n\nReply with one JSON object that follows this JSON Schema:\n" + json.dumps(
                json_schema
            )
        payload: dict = {
            "model": name,
            "messages": _groq_messages(text, images),
            "temperature": 0,
            "response_format": (
                {"type": "json_object"}
                if as_object
                else {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "strict": False, "schema": json_schema},
                }
            ),
        }
        if name.startswith("openai/gpt-oss") and name not in _groq_no_reasoning_effort:
            payload["reasoning_effort"] = (
                "low" if template in GROQ_LOW_REASONING else get_settings().praman_groq_reasoning
            )
        try:
            body = _groq_post(payload)
            break
        except GroqError as e:
            msg = str(e).lower()
            if e.status_code != 400:
                raise
            if "reasoning" in msg and "reasoning_effort" in payload:
                _groq_no_reasoning_effort.add(name)
            elif not as_object:
                _groq_json_object_only.add(name)
            else:
                raise
    else:
        raise LLMError("Groq rejected the request")
    content = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    data = _json_from_text(content)
    schema.model_validate(data)  # raise early on a malformed answer
    usage = body.get("usage") or {}
    return data, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def _model_chain(
    images: list[ImageRef], template: str = "", schema: type[BaseModel] | None = None
) -> list[str]:
    """Models to try for a live call, in order. With no live model set this is exactly
    [praman_model, praman_fallback_model]. A Groq model is skipped without a key, or when the call
    has more photos than one request takes and its answer can't be joined from several."""
    s = get_settings()
    short = s.praman_live_short_model if template in GROQ_LOW_REASONING else ""
    first = s.praman_live_vision_model if images else (short or s.praman_live_model)
    candidates = [first]
    if not images and short:
        candidates.append(s.praman_live_model)  # the short model's own limit ran out: use the main
    candidates += [s.praman_model, s.praman_fallback_model]
    too_many = len(images) > GROQ_MAX_IMAGES and not (schema is not None and _all_lists(schema))
    search = template in SEARCH_TEMPLATES
    if search:
        return _search_chain(s)
    chain: list[str] = []
    for m in candidates:
        m = (m or "").strip()
        if not m or m in chain:
            continue
        if _provider(m) == "groq" and (not s.has_groq_key or too_many):
            continue
        chain.append(m)
    return chain or [s.praman_model]


def _search_chain(s) -> list[str]:
    """Groq models to try, in order, for a web-search call: PRAMAN_SEARCH_MODELS ("a, b"), else the
    live model when it has browser search. Never Gemini. Models in PRAMAN_SEARCH_MODELS are
    trusted to have the tool; a model that rejects it just hands over to the next one."""
    listed = [m.strip() for m in s.praman_search_models.split(",") if m.strip()]
    models = listed or [
        m for m in [s.praman_live_model.strip()] if m.startswith(GROQ_SEARCH_PREFIX)
    ]
    chain = [m for m in dict.fromkeys(models) if _provider(m) == "groq"]
    if not chain or not s.has_groq_key:
        raise LLMError(
            "The web search needs a Groq model with browser search: set GROQ_API_KEY and "
            "PRAMAN_LIVE_MODEL (groq:openai/gpt-oss-120b) or PRAMAN_SEARCH_MODELS."
        )
    return chain


def _request_timeout(model: str, template: str = "") -> float:
    s = get_settings()
    if template in SEARCH_TEMPLATES:
        return GROQ_SEARCH_TIMEOUT_S
    return float(s.praman_groq_timeout_s if _provider(model) == "groq" else s.praman_timeout_s)


def _call_budget(model: str, template: str = "") -> float:
    if template in SEARCH_TEMPLATES:
        return GROQ_SEARCH_BUDGET_S
    return GROQ_CALL_BUDGET_S if _provider(model) == "groq" else GEMINI_CALL_BUDGET_S


def _retry_delay(e: Exception | None, attempt: int) -> float:
    """Seconds to wait: what the provider asked for ("Please try again in 1.8s"), else backoff."""
    m = re.search(r"(?:try again|retry) in ([\d.]+)\s*(ms|s)\b", str(e or ""), re.I)
    if m:
        secs = float(m.group(1)) / (1000 if m.group(2).lower() == "ms" else 1)
        return min(12.0, secs + 0.25)
    return min(30.0, (2**attempt) * 2 + random.random())


def _call_with_retries(
    model: str, prompt: str, schema: type[BaseModel], images: list[ImageRef], template: str = ""
) -> tuple[dict, int, int]:
    last: Exception | None = None
    started = time.monotonic()
    if model in _exhausted:
        raise QuotaExhausted(f"Daily quota used up for {model}")
    for attempt in range(RETRIES + 1):
        try:
            return _live_call(model, prompt, schema, images, template)
        except (ValidationError, json.JSONDecodeError) as e:
            last = e  # malformed JSON: one more try is cheap
            log.warning("model returned malformed JSON (attempt %d): %s", attempt + 1, e)
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001 - SDK raises several types
            last = e
            if _quota_exhausted(e):
                _exhausted.add(model)
                log.warning("daily quota used up for %s", model)
                raise QuotaExhausted(f"Daily quota used up for {model}") from e
            if not _retryable(e):
                break
            log.warning(
                "model call failed (attempt %d): %s %s",
                attempt + 1,
                type(e).__name__,
                str(e)[:300],
            )
        if attempt < RETRIES:
            delay = _retry_delay(last, attempt)
            if time.monotonic() - started + delay + _request_timeout(
                model, template
            ) > _call_budget(model, template):
                break  # another attempt could outlast the budget: let the next model answer
            time.sleep(delay)
    if _rate_limited(last):
        raise QuotaReached(f"Rate limit or quota reached for {model}") from last
    raise LLMError(f"Model call failed: {type(last).__name__}: {str(last)[:200]}")


_meter_lock = threading.Lock()


def call[T: BaseModel](
    template: str,
    schema: type[T],
    *,
    variables: dict[str, object] | None = None,
    images: list[ImageRef] | None = None,
    listing_id: str | None = None,
    meter: Meter | None = None,
) -> LLMResult[T]:
    """Render a prompt, then answer it from the cache or the model, per PRAMAN_LLM_MODE."""
    s = get_settings()
    images = images or []
    prompt = render(template, **(variables or {}))
    model = s.praman_model
    key = cache_key(model, template, prompt, [im.ident for im in images])
    t0 = time.monotonic()

    cached = cache_get(key) if s.praman_llm_mode in ("replay", "offline") else None
    if cached:
        data = json.loads(cached["response_json"])
        tin, tout, used_model, was_cached = (
            cached["tokens_in"] or 0,
            cached["tokens_out"] or 0,
            cached["model"],
            True,
        )
    else:
        if s.praman_llm_mode == "offline":
            raise ReplayMiss(f"No recorded response for {template} ({key[:12]}) in offline mode")
        chain = _model_chain(images, template, schema)
        used_model = chain[0]
        for i, used_model in enumerate(chain):
            try:
                data, tin, tout = _call_with_retries(used_model, prompt, schema, images, template)
                break
            except LLMError as e:
                if i + 1 == len(chain):
                    raise
                # Every call falls back, photo calls included (TRD §11 said text-only; with a time
                # limit per model, a failed photo read is better answered by the next model than
                # by stopping the check).
                log.warning(
                    "%s failed for %s (%s); trying %s",
                    used_model,
                    template,
                    str(e)[:200],
                    chain[i + 1],
                )
        cache_put(key, used_model, template, data, tin, tout, listing_id)
        was_cached = False
        log.info(
            "model call %s answered by %s in %d ms",
            template,
            used_model,
            int((time.monotonic() - t0) * 1000),
        )

    mark_used(listing_id, key)
    ms = int((time.monotonic() - t0) * 1000)
    if meter is not None:
        with _meter_lock:
            meter.calls += 1
            meter.cached_calls += int(was_cached)
            meter.tokens_in += tin
            meter.tokens_out += tout
            meter.ms += ms
            meter.by_template[template] = meter.by_template.get(template, 0) + 1
    return LLMResult(
        data=schema.model_validate(data),
        tokens_in=tin,
        tokens_out=tout,
        cached=was_cached,
        model=used_model,
        ms=ms,
        key=key,
    )


def image_ref(listing_id: str, index: int, url: str, local_path: str | None) -> ImageRef:
    return ImageRef(
        ident=f"{listing_id}#{index}#{url}",
        path=(ROOT / local_path) if local_path else None,
        label=f"Photo {index}:",
    )
