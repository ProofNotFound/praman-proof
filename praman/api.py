"""Web API (TRD §15): REST + Server-Sent Events, and the built frontend at /.

Run: uv run uvicorn praman.api:app --host 127.0.0.1 --port 8000
Runs execute in worker threads; each event is stored, then pushed to every SSE subscriber's
asyncio queue with loop.call_soon_threadsafe. Everything leaving the API is anonymised when the
mode is on (the event sink masks events before they are stored).
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sse_starlette.sse import EventSourceResponse

from praman import __version__, anonymise, db, guard, memory, provenance, report, store
from praman import scan as scans
from praman.agent import run_listing
from praman.config import CPCB_LIST_DATE, RECORDINGS_DIR, ROOT, SEED_PATH, get_settings
from praman.events import load_events
from praman.models import VerdictLabel
from praman.recording import build_recording, photo_items
from praman.rules import list_packs, normalise
from praman.run import new_run_id
from praman.seeds import seed_for_url
from praman.tools.cpcb import certified_count, load_rows
from praman.tools.fetch import FetchError, cache_path, fetch_listing, load_cached

log = logging.getLogger(__name__)

FRONTEND_DIST = ROOT / "frontend" / "dist"
EVAL_RESULTS = ROOT / "eval" / "results.json"
HEARTBEAT_S = 15
TERMINAL = {"run_finished", "error"}


def _log_to_stderr() -> None:
    """Show Praman's own INFO lines (which model answered) next to uvicorn's, once."""
    lg = logging.getLogger("praman")
    if not lg.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    _log_to_stderr()
    st = get_settings()
    log.info(
        "models: live=%s vision=%s primary=%s fallback=%s; keys set: groq=%s gemini=%s; mode=%s",
        st.praman_live_model or "-",
        st.praman_live_vision_model or "-",
        st.praman_model,
        st.praman_fallback_model or "-",
        "yes" if st.has_groq_key else "NO",
        "yes" if st.has_api_key else "NO",
        st.praman_llm_mode,
    )
    db.conn()  # create the schema before the first request
    provenance.snapshot()  # hash the prompts once, before the first run row is written
    yield


app = FastAPI(
    title="Praman",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="praman-run")
# Fetching a page downloads and scans every photo: one page at a time, so a few visitors at once
# can't use up a small server's memory. The next visitor waits up to FETCH_WAIT_S, then is told.
_fetch_gate = threading.BoundedSemaphore(1)
FETCH_WAIT_S = 40.0
_scan_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="praman-scan")


class Bus:
    """Per-run subscribers: (event loop, queue) pairs fed from worker threads."""

    def __init__(self) -> None:
        self._subs: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.setdefault(run_id, []).append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs[run_id] = [s for s in self._subs.get(run_id, []) if s[1] is not q]

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs.get(event["run_id"], []))
        for loop, q in subs:
            with contextlib.suppress(RuntimeError):  # the subscriber's loop closed
                loop.call_soon_threadsafe(q.put_nowait, event)


bus = Bus()


# ---------------------------------------------------------------------------
# Helpers


def _seed_rows() -> list[dict[str, str]]:
    return list(csv.DictReader(SEED_PATH.open()))


def _not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")


def _listing_json(listing) -> dict[str, Any]:
    anonymise.register_listing(listing)
    data = {
        "id": listing.id,
        "title": listing.title,
        "store": listing.store,
        "url": listing.url,
        "body_text": listing.body_text,
        "tags": listing.tags,
        "photos": [
            {
                "index": p.index,
                "url": f"/api/photos/{listing.id}/{p.index}",
                "width": p.width,
                "height": p.height,
                "alt": p.alt,
            }
            for p in listing.photos
        ],
    }
    return anonymise.maybe_mask(data)


def _run_or_404(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise _not_found("Run")
    return run


# ---------------------------------------------------------------------------
# Endpoints


@app.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    s = get_settings()
    return {
        "ok": True,
        "llm_mode": s.praman_llm_mode,
        "anonymise": s.praman_anonymise,
        # A page that isn't a recorded case can be checked here (the app asks for the code first)
        "live_checks": guard.live_checks_enabled(s),
        "needs_access_code": s.praman_public_mode and not s.praman_open_access,
        # How this caller signs: "key" (named reviewer keys), "role" (demo switch) or "off"
        "reviewer_access": guard.reviewer_access(request),
        "cpcb_list_date": CPCB_LIST_DATE,
        "cpcb_rows": certified_count(),
        "cpcb_rows_uncertified": len(load_rows()) - certified_count(),
        "version": __version__,
    }


@app.get("/api/listings")
def listings() -> list[dict[str, Any]]:
    out = []
    roles = {"normal": 0, "failure": 1, "ambiguous": 2, "not_a_claim": 3}
    for r in _seed_rows():
        cached = cache_path(r["id"]).exists()
        title, photo_count = r["handle"].replace("-", " "), 0
        if cached:
            lst = load_cached(r["id"])
            title, photo_count = lst.title, len(lst.photos)
        out.append(
            {
                "id": r["id"],
                "title": title,
                "category": r["category"],
                "demo_role": r["demo_role"] or None,
                "photo_count": photo_count,
                "cached": cached,
            }
        )
    out.sort(key=lambda x: (roles.get(x["demo_role"] or "", 9), x["id"]))
    return anonymise.maybe_mask(out)


@app.get("/api/listings/{listing_id}")
def listing(listing_id: str) -> dict[str, Any]:
    try:
        return _listing_json(load_cached(listing_id))
    except FetchError as e:
        raise _not_found("Listing") from e


@app.get("/api/photos/{listing_id}/{n}")
def photo(listing_id: str, n: int) -> Response:
    try:
        lst = load_cached(listing_id)
    except FetchError as e:
        raise _not_found("Listing") from e
    p = next((p for p in lst.photos if p.index == n), None)
    headers = {"Cache-Control": "max-age=300"}
    if p and not p.local_path:
        # Photo files aren't in git: a fresh deploy serves the demo cases' masked recording photos
        rec = RECORDINGS_DIR / "photos" / listing_id / f"{n}.jpg"
        if rec.is_file():
            return FileResponse(rec, media_type="image/jpeg", headers=headers)
    if not p or not p.local_path:
        raise _not_found("Photo")
    if not get_settings().praman_anonymise:
        return FileResponse(ROOT / p.local_path, media_type="image/jpeg", headers=headers)
    read = photo_items(store.photo_reads(listing_id))  # any run of this page that read the photo
    if n not in read and not anonymise.has_mask_files(listing_id):
        # Nobody has read this photo's print yet, so a brand on the pack could still show: serve a
        # blurred copy, never cached; the app asks again once the photo has been read
        data = anonymise.pending_photo_bytes(ROOT / p.local_path)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    data = anonymise.masked_photo_bytes(lst, n, read.get(n, []), max_edge=2048)
    return Response(data, media_type="image/jpeg", headers=headers)


class RunRequest(BaseModel):
    listing_id: str | None = None
    url: str | None = None
    mode: Literal["agent", "baseline"] = "agent"
    # "Check this product" from a store scan: the scan and the product's position in it
    scan_id: str | None = None
    product: int | None = Field(default=None, ge=0)


def _fetch_one_at_a_time(url: str):
    if not _fetch_gate.acquire(timeout=FETCH_WAIT_S):
        raise HTTPException(503, "Praman is busy checking another page. Try again in a minute.")
    try:
        return fetch_listing(url=url)
    finally:
        memory.release()
        _fetch_gate.release()


def _run_and_release(*args: Any) -> None:
    try:
        run_listing(*args)
    finally:
        memory.release()


def _check_url(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or "." not in parts.netloc:
        raise HTTPException(422, "Enter a web address that starts with http:// or https://.")
    return url


def _gate_unrecorded(request: Request, listing_id: str) -> None:
    """Only the four demo cases have recorded answers; any other listing may call the model."""
    if get_settings().praman_public_mode and listing_id not in {
        r["id"] for r in _seed_rows() if r["demo_role"]
    }:
        guard.require_live_access(request)


@app.post("/api/runs")
def start_run(req: RunRequest, request: Request) -> dict[str, str]:
    s = get_settings()
    if req.scan_id is not None:
        sc = scans.get_scan(req.scan_id)
        row = next((r for r in sc.rows if r.product == req.product), None) if sc else None
        if not row or not row.url:
            raise _not_found("Product in that scan")
        req.url = row.url  # the real URL stays on the server; the app only sees it masked
    seed = seed_for_url(req.url) if req.url else None
    if req.url and seed and cache_path(seed).exists():
        lst = load_cached(seed)  # a seed listing: the cached copy, in any mode
        _gate_unrecorded(request, lst.id)
    elif req.url:
        url = _check_url(req.url)
        if not guard.live_checks_enabled(s):
            raise HTTPException(
                409,
                "This server only replays recorded answers, so it can't check a new page. "
                "Start it in live mode, or open a case file.",
            )
        guard.require_live_access(request)
        try:
            lst = _fetch_one_at_a_time(url)
        except HTTPException:
            raise
        except guard.BlockedAddress as e:
            raise HTTPException(400, str(e)) from e
        except FetchError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, "Couldn't fetch that product page.") from e
    elif req.listing_id:
        try:
            lst = load_cached(req.listing_id)
        except FetchError as e:
            raise _not_found("Listing") from e
        _gate_unrecorded(request, lst.id)
    else:
        raise HTTPException(422, "Give a listing_id or a url")
    run_id = new_run_id(lst.id, req.mode)
    _pool.submit(_run_and_release, lst, req.mode, bus.publish, run_id)
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    last = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    after = int(last) if last and last.isdigit() else 0
    # Wait briefly for the worker to create the run row
    for _ in range(50):
        if store.get_run(run_id):
            break
        await asyncio.sleep(0.05)
    else:
        raise _not_found("Run")
    q = bus.subscribe(run_id)

    async def stream():
        sent = after
        try:
            for ev in load_events(run_id, after):
                sent = ev["seq"]
                yield _sse(ev)
                if ev["type"] in TERMINAL:
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except TimeoutError:
                    run = store.get_run(run_id)
                    if run and run["status"] != "running":
                        # Finished between the stored read and the subscription: flush the rest
                        for ev2 in load_events(run_id, sent):
                            sent = ev2["seq"]
                            yield _sse(ev2)
                        return
                    continue
                if ev["seq"] <= sent:
                    continue
                # Fill any gap from storage so the order is never broken
                if ev["seq"] > sent + 1:
                    for ev2 in load_events(run_id, sent):
                        if ev2["seq"] >= ev["seq"]:
                            break
                        sent = ev2["seq"]
                        yield _sse(ev2)
                sent = ev["seq"]
                yield _sse(ev)
                if ev["type"] in TERMINAL:
                    return
        finally:
            bus.unsubscribe(run_id, q)

    return EventSourceResponse(stream(), ping=HEARTBEAT_S)


def _sse(ev: dict[str, Any]) -> dict[str, Any]:
    return {"event": ev["type"], "id": str(ev["seq"]), "data": json.dumps(ev, ensure_ascii=False)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    lst = store.run_listing_model(run)
    data = {
        "run": store.public_run(run),
        "listing": _listing_json(lst) if lst else None,
        "claims": [c.model_dump() for c in store.claims(run_id)],
        "evidence": [e.model_dump() for e in store.evidence(run_id)],
        "verdicts": [v.model_dump(mode="json") for v in store.verdicts(run_id).values()],
        "steps": [s.model_dump() for s in store.steps(run_id)],
        "reviews": store.reviews(run_id),
    }
    # Hashes and versions stay out of the masking (a run of hex digits isn't a phone number)
    return {**anonymise.maybe_mask(data), "audit": store.audit(run_id)}


@app.get("/api/runs/{run_id}/recording")
def run_recording(run_id: str) -> dict[str, Any]:
    rec = build_recording(run_id)
    if not rec:
        raise _not_found("Run")
    return rec


def _require_reviewer(request: Request) -> str | None:
    """Analysts run checks; only a reviewer may decide a claim or sign a report (guard.py). With
    reviewer keys set, the name signed is the key's, never one typed in the browser."""
    return guard.require_reviewer(request)


def _finished_run(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    if run["status"] != "finished":
        raise HTTPException(409, "The run hasn't finished yet.")
    return run


class ReviewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    decision: Literal["agree", "change"]
    label: VerdictLabel | None = None
    reason: str = Field(default="", max_length=500)


@app.post("/api/runs/{run_id}/reviews/{claim_id}")
def review_claim(
    run_id: str, claim_id: str, req: ReviewRequest, request: Request
) -> dict[str, Any]:
    signer = _require_reviewer(request)
    run = _finished_run(run_id)
    if run.get("approved_by"):
        raise HTTPException(409, "This report is already approved.")
    v = store.verdicts(run_id).get(claim_id)
    if not v:
        raise _not_found("Verdict for that claim")
    if not req.name.strip():
        raise HTTPException(422, "Enter the reviewer's name.")
    label = v.label.value
    if req.decision == "change":
        if not req.label or req.label == v.label:
            raise HTTPException(422, "Pick a different verdict, or agree with this one.")
        if not req.reason.strip():
            raise HTTPException(422, "Say why the verdict changes.")
        label = req.label.value
    row = store.add_review(
        run_id, claim_id, req.decision, label, v.label.value, req.reason, signer or req.name
    )
    return anonymise.maybe_mask(row)


class ApproveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: str, req: ApproveRequest, request: Request) -> dict[str, Any]:
    signer = _require_reviewer(request)
    run = _finished_run(run_id)
    if run.get("approved_by"):
        raise HTTPException(409, "This report is already approved.")
    if not req.name.strip():
        raise HTTPException(422, "Enter the approver's name.")
    pending = store.pending_reviews(run_id)
    if pending:
        n = len(pending)
        raise HTTPException(
            409,
            f"{n} {'claim needs' if n == 1 else 'claims need'} a reviewer's decision first "
            f"({', '.join(pending)}).",
        )
    return anonymise.maybe_mask(store.public_run(store.approve(run_id, signer or req.name) or run))


def _approved_report(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    if not run.get("approved_by"):
        raise HTTPException(409, "Approve the report before exporting it.")
    data = report.report_data(run_id)
    assert data is not None
    return data


@app.get("/api/runs/{run_id}/report.md")
def report_md(run_id: str) -> PlainTextResponse:
    md = report.to_markdown(_approved_report(run_id))
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="praman-{run_id}.md"'},
    )


@app.get("/api/runs/{run_id}/report.html")
def report_html(run_id: str) -> HTMLResponse:
    return HTMLResponse(report.to_html(_approved_report(run_id)))


class ScanRequest(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    pack: str = Field(default="green_claims", max_length=60)  # any rule pack (GET /api/rule-packs)


@app.post("/api/scans")
def start_scan(req: ScanRequest, request: Request) -> dict[str, str]:
    """Triage a whole store (W3, TRD §15.7): code only, no model calls."""
    try:
        base = scans.store_base(req.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    host = urlparse(base).netloc.lower().removeprefix("www.")
    if not scans._cache_file(host).exists():
        guard.require_live_access(request)  # a crawl of someone else's site: code and limits
    if get_settings().praman_llm_mode == "offline" and not scans._cache_file(host).exists():
        raise HTTPException(
            409,
            "Store scans need the network, and this server is in offline mode. "
            "Start it in replay or live mode.",
        )
    try:
        sc = scans.new_scan(base, req.pack)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _scan_pool.submit(scans.run_scan, sc)
    return {"scan_id": sc.id}


@app.get("/api/scans/{scan_id}")
def scan_detail(scan_id: str) -> dict[str, Any]:
    sc = scans.get_scan(scan_id)
    if not sc:
        raise _not_found("Scan")
    return scans.public(sc)


@app.get("/api/compare/{listing_id}")
def compare(listing_id: str) -> dict[str, Any]:
    sides: dict[str, Any] = {}
    for mode in ("agent", "baseline"):
        run = store.latest_run(listing_id, mode)
        if not run:
            sides[mode] = None
            continue
        claims = store.claims(run["id"])
        verdicts = store.verdicts(run["id"])
        sides[mode] = {
            "run_id": run["id"],
            "claims": [c.model_dump() for c in claims],
            "verdicts": [v.model_dump(mode="json") for v in verdicts.values()],
        }
    pairs = []
    if sides.get("agent") and sides.get("baseline"):
        b_claims = sides["baseline"]["claims"]
        b_verdicts = {v["claim_id"]: v for v in sides["baseline"]["verdicts"]}
        a_verdicts = {v["claim_id"]: v for v in sides["agent"]["verdicts"]}
        for c in sides["agent"]["claims"]:
            best = max(
                b_claims,
                key=lambda b: fuzz.ratio(normalise(c["quote"]), normalise(b["quote"])),
                default=None,
            )
            match = (
                best
                if best and fuzz.ratio(normalise(c["quote"]), normalise(best["quote"])) >= 80
                else None
            )
            a_label = a_verdicts.get(c["id"], {}).get("label")
            b_label = b_verdicts.get(match["id"], {}).get("label") if match else None
            pairs.append(
                {
                    "agent_claim_id": c["id"],
                    "baseline_claim_id": match["id"] if match else None,
                    "quote": c["quote"],
                    "agent": a_label,
                    "baseline": b_label,
                    "differs": a_label != b_label,
                }
            )
    return anonymise.maybe_mask({"listing_id": listing_id, **sides, "pairs": pairs})


@app.get("/api/rule-packs")
def rule_packs() -> list[dict[str, Any]]:
    return list_packs()


@app.get("/api/eval")
def eval_results() -> dict[str, Any]:
    if not EVAL_RESULTS.exists():
        return {"status": "pending"}
    return anonymise.maybe_mask(json.loads(EVAL_RESULTS.read_text()))


@app.get("/api/{rest:path}")
def api_404(rest: str) -> JSONResponse:
    return JSONResponse({"detail": "Not found"}, status_code=404)


# ---------------------------------------------------------------------------
# The built frontend, with an SPA fallback to index.html


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> Response:
    if not FRONTEND_DIST.exists():
        return PlainTextResponse(
            "Praman API is running. The web app isn't built yet (cd frontend && npm run build).",
            status_code=200,
        )
    target = (FRONTEND_DIST / path).resolve()
    if path and target.is_file() and FRONTEND_DIST.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(FRONTEND_DIST / "index.html")
