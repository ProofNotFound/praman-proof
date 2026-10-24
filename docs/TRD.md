# Praman: Technical Requirements and Design

| | |
|---|---|
| Version | 1.1 (18 Oct 2026): web app (FastAPI + React) replaces Streamlit |
| Companion | `docs/PRD.md` (what and why), `docs/DESIGN.md` (frontend look and behaviour), `CLAUDE.md` (how to work in this repo), `docs/STATUS.md` and `docs/FRONTEND_STATUS.md` (where we are) |
| Build window | Sun 18 – Thu 22 Oct 2026; feature freeze Thu night; event Sat 24 Oct |

---

## 1. Principles

1. **The model reads and reasons; code decides what rules make clear-cut.** Rule matching, registry lookups, limits and the final verdict for registry- or label-based rules are plain Python.
2. **Evidence or nothing.** Every verdict cites evidence IDs and rule IDs, or it is downgraded to Needs review.
3. **Read-only.** No tool writes to, posts to, or contacts any external system.
4. **Deterministic where possible.** Temperature 0, fixed tool list, schema-validated calls, and a record/replay cache for every model call.
5. **Offline-first demo.** Everything the demo needs runs from `data/cache/` and the replay cache with the network off.
6. **Small and visible.** Our own ~150-line agent loop, no agent framework, every step written to the trace.

---

## 2. Architecture

```
            ┌───────────────────────────────────────────────────┐
 INPUT      │ product URL │ pasted text + photos │ cached listing ID│
            └──────────────────────────┬────────────────────────┘
                                       ▼
            ┌───────────────────────────────────────────────────┐
 STAGE 1    │ fetch_listing → Listing (title, body, tags, photos) │
 (prepare)  │ extract_claims (LLM) → Claim[] (+ not-a-claim)      │
            │ match_rule (code) → rule IDs + proof required       │
            └──────────────────────────┬────────────────────────┘
                                       ▼  per claim
            ┌───────────────────────────────────────────────────┐
 STAGE 2    │ PLAN → ACT → OBSERVE → DECIDE   (≤ 2 follow-ups)    │
 (agent)    │   ▲                       │                         │
            │   └──── no proof yet ─────┘                         │
            │ tools: search_text · read_photos · decode_qr ·      │
            │        cpcb_lookup · fetch_linked_page ·            │
            │        check_consistency · rule_lookup ·            │
            │        check_material (fallback, code-triggered)    │
            └──────────────────────────┬────────────────────────┘
                                       ▼
            ┌───────────────────────────────────────────────────┐
 OUTPUT     │ decide_verdict (code) → Verdict per claim           │
            │ write_rewrite (LLM) → suggested wording             │
            │ Report → human approval → Markdown/HTML export      │
            └──────────────────────────┬────────────────────────┘
                                       ▼  every step emits an event
            ┌───────────────────────────────────────────────────┐
 WEB        │ FastAPI (praman/api.py): /api + SSE event stream    │
            │ React app (frontend/): scan · ledger · threads ·    │
            │ stamps · trace · compare · dossier report           │
            │ fallback: bundled recordings (frontend/public/demo) │
            └───────────────────────────────────────────────────┘
   all steps ──► SQLite (runs, steps, events, claims, evidence, verdicts, llm_cache)
```

---

## 3. Repository layout

```
praman/
  CLAUDE.md
  README.md
  pyproject.toml            # uv-managed
  .env.example
  .gitignore
  .claude/settings.json     # Claude Code permissions for the build
  .claude/launch.json       # preview servers for the desktop app (api :8000, web :5173)
  praman/
    __init__.py
    api.py                  # FastAPI app: /api routes, SSE, serves frontend/dist (§15)
    events.py               # event models + per-run event bus (§15.3)
    config.py               # pydantic-settings
    models.py               # Pydantic models (§5)
    db.py                   # SQLite schema + helpers (§12)
    llm.py                  # Gemini client, retries, record/replay cache, cost
    anonymise.py            # brand/domain masking (FR-16)
    rules.py                # load + match rules.json (§6)
    verdict.py              # decide_verdict decision table (§9)
    agent.py                # the loop (§8)
    baseline.py             # fixed pipeline (§8.4)
    report.py               # Markdown/HTML export
    prompts/                # one .md template per prompt (§10)
    tools/
      fetch.py              # fetch_listing, fetch_linked_page
      claims.py             # extract_claims
      text.py               # search_text
      photos.py             # read_photos (+ qr.py stretch)
      cpcb.py               # cpcb_lookup
      consistency.py        # check_consistency
  scripts/
    fetch_cache.py          # download listings + photos into data/cache
    build_cpcb_csv.py       # CPCB PDF → data/cpcb_certified.csv
    photo_probe.py          # go/no-go test for vision on two box photos
    run_one.py              # CLI: run a listing, print trace
    export_recordings.py    # demo runs → data/recordings/ (copied to frontend/public/demo/ in F5; §15.4)
    demo.sh                 # build frontend, start API, open the app
  frontend/                 # React app (§15.6, docs/DESIGN.md)
  eval/
    labels.csv              # claim-level labels (seed 21 + 10 blind holdout)
    run_eval.py             # agent vs baseline → eval/results.md
  data/
    rules.json
    listings_seed.csv       # PRIVATE: our 21 seed listings
    cpcb_certified.csv
    cache/listings/<id>.json
    cache/images/<id>/<n>.jpg
  tests/
    fixtures/
    test_rules.py  test_cpcb.py  test_verdict.py  test_tools_*.py
    test_golden_traces.py
```

---

## 4. Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12, `uv` |
| Model | Gemini current Flash model via `google-genai`; model name from env; temperature 0; structured JSON output via a response schema |
| Fallback model | Second model name from env (text-only steps) |
| Schemas | Pydantic v2; `pydantic-settings` for config |
| HTTP | `httpx` (timeouts, retries); `selectolax` for HTML fallback |
| Images | Pillow (resize/crop); OpenCV `QRCodeDetector` (stretch) |
| Registry | `pdfplumber` (one-off), `pandas`, `rapidfuzz` |
| Storage | SQLite (stdlib `sqlite3`) |
| Web API | FastAPI + uvicorn; Server-Sent Events via `sse-starlette` |
| Frontend | Vite + React + TypeScript (strict) + Tailwind CSS v4 + `motion` + `lucide-react` + `react-router`; fonts via `@fontsource`; Vitest. Node 22 LTS |
| Tests and quality | `pytest`, `ruff`; GitHub Actions (offline mode only) |

---

## 5. Data models (`praman/models.py`)

```python
class Photo(BaseModel):
    index: int                      # position in the listing (1-based)
    url: str
    local_path: str | None
    alt: str = ""

class Listing(BaseModel):
    id: str                         # e.g. "L14" for seed listings, or a hash for new URLs
    source: Literal["shopify_json", "json_ld", "html", "pasted", "cache"]
    url: str | None
    store: str | None               # domain; masked in anonymise mode
    title: str
    body_text: str                  # description with HTML stripped
    tags: list[str] = []
    photos: list[Photo] = []
    fetched_at: datetime

class Claim(BaseModel):
    id: str                         # "C1", "C2", … within a run
    quote: str                      # exact words as they appear
    normalised: str                 # lowercase, trimmed, for matching
    type: Literal["vague", "specific", "comparative", "future"]
    scope: Literal["product", "part", "packaging", "process", "disposal", "delivery", "brand", "unclear"]
    location: str                   # "title" | "description" | "tag" | "photo:3"
    is_claim: bool = True
    not_claim_reason: str | None = None
    rule_ids: list[str] = []

class Evidence(BaseModel):
    id: str                         # "E1", …
    claim_id: str
    source: Literal["text", "photo", "registry", "link", "consistency"]
    detail: str                     # quote, extracted print, registry row summary, URL
    photo_index: int | None = None
    crop_box: tuple[int, int, int, int] | None = None   # Gemini box_2d convention: [ymin, xmin, ymax, xmax], 0–1000
    covers_claim: Literal["yes", "partly", "no", "contradicts"]
    certifier: str | None = None    # e.g. "CPCB", "Ecocert", "B Corp", "IFRA"
    cert_scope: Literal["product", "material", "ingredient", "company", "other", "unknown"] | None = None

class Step(BaseModel):
    run_id: str
    claim_id: str | None
    n: int
    phase: Literal["plan", "act", "observe", "decide"]
    tool: str | None
    summary: str                    # one human-readable line for the trace panel
    payload: dict                   # tool input/output (truncated for display)
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0

class VerdictLabel(str, Enum):
    BACKED = "Backed"; PARTLY = "Partly backed"; NOT_BACKED = "Not backed"
    CONTRADICTED = "Contradicted"; NEEDS_REVIEW = "Needs review"; NOT_A_CLAIM = "Not a claim"

class Verdict(BaseModel):
    claim_id: str
    label: VerdictLabel
    evidence_ids: list[str]
    rule_ids: list[str]
    reason: str                     # one or two sentences, careful language (§10.7)
    missing: str | None = None      # what proof would change the verdict
    rewrite: str | None = None
    sources_searched: list[str]

class Run(BaseModel):
    id: str
    listing_id: str
    mode: Literal["agent", "baseline"]
    llm_mode: Literal["live", "replay", "offline"]
    started_at: datetime
    finished_at: datetime | None
    llm_calls: int; tokens_in: int; tokens_out: int; est_cost_inr: float
    approved_by: str | None = None
    approved_at: datetime | None = None
```

---

## 6. Rules engine (`data/rules.json`, `praman/rules.py`)

### 6.1 Schema
```json
{
  "id": "R07",
  "name": "Compostable plastic needs a CPCB certificate",
  "source": "PWM Amendment Rules 2024",
  "clause": "Rule 4(1)(ha); Rule 4(1)(h)",
  "citation_url": "https://…",
  "summary": "Plain-English rule shown in the UI",
  "triggers": {"terms": ["compostable"], "claim_types": ["specific"], "requires_plastic_context": true},
  "required_evidence": [{"kind": "registry_match", "registry": "cpcb_compostable"}],
  "contradiction_signals": [],
  "decides_in_code": true
}
```

### 6.2 `required_evidence.kind`
| Kind | Satisfied when |
|---|---|
| `qualifier` | The claim states which aspect it refers to and how (LLM judgement, recorded as evidence) |
| `certification` | A named certificate from a statutory or independent body that covers this claim and this product |
| `scientific_evidence` | A named standard or test (e.g. IS/ISO 17088, EN 13432) tied to this product |
| `registry_match` | `cpcb_lookup` finds the maker on the CPCB list |
| `label_text` | Required wording is visible (regex over text and photo print) |
| `disclosure_link` | A QR code or URL to details is present |
| `comparison_data` | Data stating what is compared |
| `plan` | A concrete plan for a future claim |

### 6.3 Matching
1. Lowercase and normalise the claim.
2. A rule applies when any trigger term matches **and** the claim type is in `claim_types`.
3. `requires_plastic_context`: only when the product or packaging is plastic-like (bags, film, cutlery, liners, pouches) per listing text or photo print.
4. Always attach R03 (disclosure), R04 (scope) and R10 (certificate scope) as cross-cutting checks when relevant.
5. Unit-test every rule with at least one positive and one negative example.

---

## 7. Tool contracts

All tools are pure functions `(input model) -> output model`, registered in a fixed allow-list. The planner may only name tools from this list; the loop validates the call with Pydantic before running it.

| Tool | Input | Output | Model? | Timeout |
|---|---|---|---|---|
| `fetch_listing` | url or listing_id or pasted text+files | `Listing` (Shopify JSON, else JSON-LD, else OpenGraph + readable text; §14) | No | 15 s per request |
| `extract_claims` | `Listing` (+ photo print from `read_photos` if already run) | `list[Claim]` | Yes | 30 s |
| `match_rule` | `Claim`, `Listing` | rule IDs, proof required | No | 1 s |
| `search_text` | `Claim`, `Listing`, required kinds | `list[Evidence]` | Regex first; model only to judge `covers_claim` | 15 s |
| `read_photos` | `Listing`, max_photos=5 | `PhotoPrint[]`: per photo, all printed claims, certificate marks, codes, material/composition lines, label text, QR present | Yes (vision) | 45 s |
| `cpcb_lookup` | maker name, address or code fragments | best match row (S.No., name, state, certificate type, validity) + score, or none | No | 1 s |
| `fetch_linked_page` | URL (same domain only) | page text + list of certificate names found | No (+ model to judge coverage) | 15 s |
| `check_consistency` | `Listing`, `Claim[]`, photo print | `Evidence[]` with covers_claim = contradicts | Yes | 30 s |
| `rule_lookup` | rule_id | rule summary + clause + citation | No | 1 s |
| `decode_qr` | `Listing` (photos' stored QR codes) | evidence per code: a link on the listing's own site is opened (as `fetch_linked_page`) and searched for proof, plus a `disclosure_link` item; a link elsewhere becomes "QR code links to <domain>; not followed" (`qr_link`), which keeps the claim at Needs review | No (+ model to judge the page) | 15 s |
| `check_material` | the material lines on the product (photo composition print first, then "made from …" text) and the property the claim relies on (compostable, biodegradable, recyclable, plastic-free; a vague claim borrows the one the page states) | `MaterialCheckOut`: material, answer yes/partly/no/unclear, summary, caveat, and the sources the search returned; one `web` evidence item (`kind: material_check`) per claim, covers = yes only with ≥1 source | Yes (Groq gpt-oss with its built-in `browser_search`, the models in `PRAMAN_SEARCH_MODELS` in order, else `PRAMAN_LIVE_MODEL`; never Gemini; sources from the search tool's results) | 75 s |

`check_material` isn't offered to the planner: after the loop, code runs it once per property per run when the agent-mode verdict would be Partly backed, Not backed or Needs review, the claim is vague or specific about the product or a part, and the page names a material. It never runs when any claim on the page falls under R07/R09 (compostable/biodegradable plastic needs the CPCB certificate), when the material lines name plastic (PLA, PBAT, poly…, nylon, non-woven, laminated…), or when they give a blend percentage ("30% wheat straw"). If no Groq search model answers (quota, no key), the check is marked as not run: the claim goes to Needs review, and the verdict never lists the material search as searched (DECISIONS J18, J20). The model judges the material as printed: a coating or lining lowers the answer only when the listing names it (otherwise it goes in the caveat, shown on the evidence).

### 7.1 `read_photos` details
- Order photos so that likely box backs and labels come first: photos with text-heavy appearance (later indices, names containing "back", "label", "box", white backgrounds) before lifestyle images. If unsure, use the last 3 photos plus the first 2.
- Send each photo at full resolution up to 2,048 px on the long edge (Gemini accepts images inline).
- Run **once per listing**, cache the result, and let every claim reuse it.
- Return exact printed strings; never paraphrase codes (e.g. `CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443`).
- Ask for a bounding box per printed item in Gemini's `box_2d` format (`[ymin, xmin, ymax, xmax]`, normalised 0–1000). Boxes feed `Evidence.crop_box`, the Scan animation and photo masking. If the model omits a box, keep the item with `box_2d = null`.

### 7.2 `cpcb_lookup` details
- Source: CPCB "List of Certified manufacturers/sellers of compostable carry bags & commodities", as of 26.10.2023 (172 certified rows; a second table of uncertified units). No certificate-number column, so match on name and address.
- Normalise: lowercase; remove "m/s", "pvt", "ltd", "private limited", "llp", punctuation; collapse spaces.
- Score with `rapidfuzz.fuzz.token_set_ratio`; accept ≥ 90, or ≥ 80 when the state also matches. Return the best match and its score.
- Example to test: "Greendot Biopak Pvt Ltd, Ahmedabad, Gujarat" → S.No. 32 "Greendotbiopak", Gujarat; "Sunshield Biotech LLP" → S.No. 2.
- Every report states the list date.

---

## 8. The agent loop (`praman/agent.py`)

### 8.1 Budget
| Limit | Value |
|---|---|
| Follow-ups per claim (after the first search) | 2 |
| Photos per listing | 5 |
| Tool calls per listing | 30 |
| Model calls per listing | 12 |
| Wall time per listing | 90 s (then Needs review for unfinished claims) |

### 8.2 Algorithm
```text
run(listing, mode="agent"):
    claims = extract_claims(listing)                    # Stage 1
    for c in claims: c.rule_ids = match_rule(c, listing)
    photo_print = None
    for c in claims:
        if not c.is_claim: verdict(c) = NOT_A_CLAIM; continue
        state = State(claim=c, rules=rules_for(c), evidence=[], searched=[], followups=0)
        while True:
            action = plan_next(state)                   # LLM picks one tool, or STOP with reason
            if action.tool not in ALLOWED or invalid(action.args):
                action = default_next(state)            # text → photos → QR → registry → link
            if action is STOP: break
            if action.tool == "read_photos" and photo_print: result = photo_print   # reuse
            else: result = call(action)                 # ACT
            if action.tool == "read_photos": photo_print = result
            new_ev = observe(state, result)             # OBSERVE: convert to Evidence, judge covers_claim
            state.evidence += new_ev; state.searched += [action.tool]
            if sufficient(state) or contradicted(state): break      # DECIDE
            state.followups += 1
            if state.followups > MAX_FOLLOWUPS: break
        verdict(c) = decide_verdict(state)              # code, §9
    contradictions = check_consistency(listing, claims, photo_print)
    merge contradictions into verdicts (Contradicted wins over Backed for the same claim)
    rewrites for non-Backed claims
```

### 8.3 `plan_next`
- Input: claim, rule summaries and required evidence kinds, sources already searched, evidence so far (short), remaining budget.
- Output (JSON): `{"tool": "<one of allowed>" | "STOP", "args": {...}, "why": "<one sentence>"}`.
- The `why` sentence is what the trace panel shows on the Plan row.
- Hints in the prompt: registry checks only make sense when a maker name or code is known; photo reading is the place to look for codes, certificate marks, composition and labels; stop early when the listing contradicts the claim.

### 8.4 Baseline mode (`praman/baseline.py`)
Fixed pipeline, same models and prompts where shared:
`extract_claims (text only) → match_rule → search_text → decide_verdict`.
No photos, no registry, no linked pages, no re-planning. Used only for the comparison.

---

## 9. Verdict decision table (`praman/verdict.py`, code)

Evaluate in order; the first matching row wins.

| # | Condition | Verdict |
|---|---|---|
| 1 | `claim.is_claim` is false | Not a claim |
| 2 | Any evidence with covers_claim = contradicts | Contradicted |
| 3 | A rule with `decides_in_code` requires `registry_match` and a registry evidence item covers = yes | Backed (for that requirement) |
| 4 | All required kinds for all applicable rules have evidence with covers = yes, and every certificate evidence has cert_scope in {product, material} matching the claim | Backed |
| 4b | No certificate settled it, a `material_check` item covers = yes (public sources say the material printed on the product has the property), the claim's scope isn't unclear, and no rule among R05, R06, R07, R09 applies | Backed ("Backed on its material, not a certificate: …"); checked before the off-site QR row |
| 5 | Some required kind has evidence with covers = yes or partly, a `material_check` item covers = partly, or a certificate's scope is company/ingredient/other | Partly backed |
| 6 | A required `label_text` item is missing but the claim is otherwise backed | Backed for the claim + a separate Needs review item for the label |
| 7 | Budget exhausted while a source not yet searched could hold proof | Needs review |
| 8 | All sources searched, no evidence | Not backed |

Guards:
- **False-Backed guard:** Backed requires ≥1 evidence item with covers = yes from a required source (`material_check` counts). Otherwise downgrade to Partly backed or Needs review.
- **Citation guard:** any verdict except Not a claim without rule IDs, and any Backed / Partly backed / Contradicted without evidence IDs → Needs review.

---

## 10. Prompts (`praman/prompts/*.md`)

Shared rules for every prompt: return JSON matching the schema; quote exact words from the input; never invent certificates, numbers or codes; say "unknown" when unsure; temperature 0.

| Prompt | Purpose | Output |
|---|---|---|
| `extract_claims.md` | List environmental claims with quote, type, scope, location; mark non-claims with a reason | `Claim[]` |
| `read_photos.md` | For each photo: printed claims, certificate marks and names, codes and registration numbers (exact), composition/material lines, required label text, QR present | `PhotoPrint[]` |
| `plan_next.md` | Choose the next tool or STOP, with one sentence of why | `PlanAction` |
| `judge_evidence.md` | Does this evidence cover this claim and this product? yes / partly / no / contradicts, with cert_scope | `EvidenceJudgement` |
| `check_consistency.md` | Find conflicts between claims and the listing's own materials, numbers and statements | `Evidence[]` (contradicts) |
| `write_rewrite.md` | A compliant rewording: specific, scoped, and linked to proof, or the claim removed | `{"rewrite": str}` |

### 10.7 Language rules for any text shown to users
Never "illegal", "violation", "greenwashing", "fraud", "lying". Use "proof not found on this page", "this certificate covers X, not this claim", "conflicts with the definition in the plastic waste rules", "needs review".

---

## 11. Model client (`praman/llm.py`)

- SDK: `google-genai`. Model names from env: `PRAMAN_MODEL`, `PRAMAN_FALLBACK_MODEL`.
- Every call: temperature 0, JSON response schema from the Pydantic model, timeout, up to 3 retries with exponential backoff on rate limits and server errors; on final failure, try the fallback model for text-only calls.
- **Record/replay cache:** key = SHA-256 of (model, prompt template name, rendered prompt, image identifiers = listing ID + photo index + source URL). Image bytes are not part of the key, so tests and CI work without the gitignored image files. Modes:
  - `live`: call the API, store the response.
  - `replay`: return the stored response; on a miss, call the API and store it.
  - `offline`: return the stored response; on a miss, raise `ReplayMiss` (tests and demo use this).
- Record tokens in/out from usage metadata; estimate cost from per-million-token prices in config (₹).

---

## 12. Storage (`praman/db.py`, SQLite at `data/praman.db`)

| Table | Key columns |
|---|---|
| `runs` | id, listing_id, mode, llm_mode, started_at, finished_at, llm_calls, tokens_in, tokens_out, est_cost_inr, approved_by, approved_at |
| `steps` | run_id, n, claim_id, phase, tool, summary, payload_json, ms, tokens_in, tokens_out |
| `events` | run_id, seq, type, t_ms, data_json (every event sent to the frontend, in order; used for replay, recordings and SSE resume) |
| `claims` | run_id, claim_id, quote, type, scope, location, is_claim, rule_ids_json |
| `evidence` | run_id, evidence_id, claim_id, source, detail, photo_index, crop_box_json, covers_claim, certifier, cert_scope |
| `verdicts` | run_id, claim_id, label, evidence_ids_json, rule_ids_json, reason, missing, rewrite |
| `llm_cache` | key, model, template, response_json, tokens_in, tokens_out, created_at |
| `eval_results` | eval_id, listing_id, claim_ref, mode, predicted, expected, match |
| `anon_names` | key (registered domain or lowercased brand name), letter, kind (`domain`/`brand`), created_at: anonymiser letters for stores outside the seed file (§15.5) |

---

## 13. Configuration (`.env`, never committed)

```
GEMINI_API_KEY=
PRAMAN_MODEL=            # current Gemini Flash model name from AI Studio
PRAMAN_FALLBACK_MODEL=
PRAMAN_LLM_MODE=replay   # live | replay | offline
PRAMAN_MAX_PHOTOS=5
PRAMAN_MAX_FOLLOWUPS=2
PRAMAN_TIMEOUT_S=45
PRAMAN_DB_PATH=data/praman.db
PRAMAN_ANONYMISE=1
PRAMAN_PRICE_IN_PER_M_INR=
PRAMAN_PRICE_OUT_PER_M_INR=
```

---

## 14. Fetching rules

- Product URLs are tried in this order (`praman/tools/fetch.py`, `praman/tools/page.py`):
  1. Shopify: `https://<store>/products/<handle>.json` (title, body_html, tags, images).
  2. schema.org `Product` JSON-LD in the page (top level, lists or `@graph`): name, description, brand, images (`source = "json_ld"`).
  3. OpenGraph tags (`og:title`, `og:description`, `og:image`, `og:site_name`) plus the main readable text (`<main>`/`<article>`, else body; nav, header, footer, scripts dropped) and large gallery images (no icons, logos, data URIs or images under 300 px; at most 10 photos) (`source = "html"`), when the page looks like a product (`og:type` product, price meta, schema.org microdata or a `/products/` style path).
- Page fetches: 15 s timeout (10 s connect), HTML content types only, 5 MB cap (declared or streamed), redirects only within the same site. No JavaScript is run: a page whose text is built in the browser gets "Couldn't read this page: …" and no run starts; a page with no product gets "Couldn't read this page as a product: …".
- Check robots.txt once per domain; skip disallowed paths.
- ≤ 1 request per second per domain; user agent `PramanResearchBot/0.1 (student hackathon project)`.
- Images: download to `data/cache/images/<id>/<n>.jpg`, keep the original resolution, cap at 8 MB.
- `fetch_linked_page`: same registered domain as the listing only.

---

## 15. Web API, events and frontend

### 15.1 Shape
```
React app (frontend/) ──HTTP + SSE──► FastAPI (praman/api.py) ──► agent.run(listing, mode, emit=bus.emit)
      │                                      └──► SQLite events table (every event, in order)
      └── falls back to frontend/public/demo/*.json recordings when /api/health fails
```
- Demo: one process. `uv run uvicorn praman.api:app --host 127.0.0.1 --port 8000` serves `/api/*` and the built frontend (`frontend/dist`) at `/`, with an SPA fallback to `index.html`.
- Development: Vite on 5173 proxies `/api` to `http://127.0.0.1:8000`. Both servers are in `.claude/launch.json`.
- Bind to 127.0.0.1 only. CORS allows `http://localhost:5173` and `http://127.0.0.1:5173` only.
- Runs execute in a worker thread; the agent calls `emit(type, data)`; the bus appends to the `events` table and pushes to the run's asyncio queue with `loop.call_soon_threadsafe`. Anonymisation happens before emit.

### 15.2 Endpoints
| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{ok, llm_mode, anonymise, cpcb_list_date, version, live_checks, needs_access_code, reviewer_access}`; `reviewer_access` is `key` (named reviewer keys, `PRAMAN_REVIEWERS`), `role` (demo role switch: a local server or the presenter's own laptop) or `off` (a public server's visitors when no keys are set) |
| GET | `/api/listings` | seed listings (anonymised): `[{id, title, category, demo_role, photo_count, cached}]` |
| GET | `/api/listings/{id}` | listing (anonymised) with photo URLs |
| GET | `/api/photos/{listing_id}/{n}` | cached image (masked in anonymise mode, §15.5) |
| POST | `/api/runs` | body `{listing_id?, url?, mode}` (mode is `agent` or `baseline`) → `{run_id}`. Or `{scan_id, product}` to check a product from a store scan (§15.7; the real URL stays on the server). A `url` that names a seed listing (its store URL, or the anonymised `brand-x.example/products/<handle>` the app shows) runs the cached listing in any mode; any other `url` only in live mode (else 409 with a plain message); 422 unless http(s) |
| GET | `/api/runs/{id}/events` | SSE stream (§15.3); honours `Last-Event-ID`; heartbeat comment every 15 s; closes after `run_finished` or `error` |
| GET | `/api/runs/{id}` | `{run, listing, claims, evidence, verdicts, steps, reviews, audit}`; `audit` = `{provenance: {praman, commit, rules_version, rules_as_of, prompts, model, live_model, fallback_model, llm_mode, cpcb_list_date} or null, reviews, reviews_chained, reviews_intact, review_head, fingerprint, fingerprint_matches}` (`praman/provenance.py`; not masked) |
| GET | `/api/runs/{id}/recording` | recording (§15.4) |
| POST | `/api/runs/{id}/reviews/{claim_id}` | header `X-Reviewer-Key: <key>` when `reviewer_access` is `key` (the stored `reviewer` is the key's name, not the typed one), else `X-Praman-Role: reviewer`; body `{name, decision: agree or change, label?, reason?}` → the stored decision `{claim_id, decision, label, ai_label, reason, reviewer, at}`. 401 for a missing or wrong key; 403 without the reviewer role, or when `reviewer_access` is `off`; 422 if a change has no new label or no reason; 409 once approved. Each decision stores `prev_hash` and `hash` (a hash chain) |
| POST | `/api/runs/{id}/approve` | same headers as a review; body `{name}` → run with `approved_by` (the key's name in `key` mode), `approved_at`; stores `approval_hash`, the fingerprint of the provenance, every verdict with its evidence and rules, the review chain and the signer. 401/403 as for a review; 409 while a Needs review claim has no reviewer decision, and 409 once approved (the first signer stays) |
| GET | `/api/runs/{id}/report.md`, `/report.html` | report with the PRD §8 disclaimer and an Audit section (what the run was checked with, the review chain, the fingerprint and whether it still matches); 409 until approved |
| GET | `/api/compare/{listing_id}` | latest agent and baseline runs for the listing: verdicts side by side |
| GET | `/api/rule-packs` | every rule pack: `[{name, title, domain, status, status_note, version, as_of, sources, rules: [{id, name, summary, clause, source, terms, evidence}]}]` |
| GET | `/api/eval` | parsed evaluation results, or `{status: "pending"}` |
| POST | `/api/scans` | body `{url, pack?}` (a store address; `pack` is any rule pack name, default `green_claims`) → `{scan_id}`; 422 for an unknown pack; store scan, §15.7 |
| GET | `/api/scans/{id}` | scan progress and ranked results, §15.7 |

### 15.3 Events (the contract between core and frontend)
Every event is `{"seq": int, "t_ms": int, "type": str, "run_id": str, "data": {...}}`; `t_ms` counts from run start. Over SSE: `event: <type>`, `id: <seq>`, `data: <json>`. `praman/events.py` defines them as Pydantic models (a discriminated union on `type`); `frontend/src/lib/events.ts` mirrors them by hand. This table is the source of truth for both.

| type | data |
|---|---|
| `run_started` | `run_id, listing_id, mode, llm_mode, started_at` |
| `listing` | anonymised listing: `id, title, store, body_text, photos: [{index, url, width, height}]` (+ optional `tags`) |
| `claims` | `claims: Claim[]` (with `rule_ids`; not-a-claim items included). May be sent again mid-run with the **full** list when new claims appear (claims printed only on photos, or a required-label check split from a claim, which has optional `derived_from: <claim_id>` and `location: "n/a"`); upsert by `id` |
| `step` | `Step` fields except `payload`, plus `payload_preview` (≤ 300 chars) |
| `photo_read` | `photos: [{index, items: [{text, kind, box_2d}]}]`; `kind` ∈ code, certificate, composition, label, claim, other; `box_2d` may be null. Optional `claim_id` (the claim whose search triggered the read). Sent once per run; later claims reuse the print |
| `registry_lookup` | `claim_id, query, rows_scanned, list_date, match, score`; `rows_scanned` is the number of rows on the certified list (Table 1, 172), with optional `rows_uncertified` (Table 2, also checked); `match` is `{s_no, name, state, type, validity}` (+ optional `table`: 1 certified, 2 not certified, and `certificate`, e.g. "one time certificate") or null; `score` is name similarity **0–1**. No phone numbers, emails or addresses |
| `evidence` | `Evidence`, plus optional `kind` (the proof kind it speaks to), `rule_id` (rule behind a contradiction or label), `note` (one neutral sentence: why it does or doesn't cover the claim), on contradictions `conflict: {a, b, b_location}` (the claim's words vs the conflicting words and where they are), `source` is one of text, photo, registry, link, consistency or `web` (a `check_material` answer from a web search, `kind: material_check`, its sources named in `detail`), and on `decode_qr` evidence `qr: {domain, followed, path?}` (a QR code on the pack: the registered domain it links to, whether Praman opened it (same site only), and the path when it did; `kind` is `disclosure_link` when followed, `qr_link` when not) |
| `verdict` | `Verdict` (with `rule_ids`, plus `rules: [{id, name, summary, clause, source}]` for the chips). May be sent again for the same `claim_id` (after the end-of-run consistency check, or when the rewrite is ready); the latest one wins |
| `run_finished` | `llm_calls, tokens_in, tokens_out, est_cost_inr, elapsed_ms, counts: {label: n}` (+ optional `cached_calls`, `tool_calls`, and `quota_reached: true` when the model answered with a quota or rate-limit error after every retry: the run still finishes, and every claim not yet decided is Needs review with the reason "Model quota reached…") |
| `error` | `message` (plain words, no stack trace), `recoverable` |

Order within a claim: `step(plan)` → `step(act)` → tool-specific event (`photo_read`, `registry_lookup`) → `evidence`* → `step(observe)` … → `step(decide)` → `verdict`.

### 15.4 Recordings
`GET /api/runs/{id}/recording` and the files in `frontend/public/demo/` share one format:
```json
{"format": "praman-recording/1", "synthetic": false, "listing_id": "L14", "mode": "agent",
 "title": "…", "recorded_at": "…", "events": [ … every event in order … ]}
```
- `frontend/public/demo/index.json` lists the cases: `[{listing_id, mode, title, file, claim_count, synthetic}]`.
- Photo URLs inside recordings point to `demo/photos/<listing_id>/<n>.jpg` (copied, masked when anonymised).
- The frontend track starts with hand-written **synthetic** recordings (`"synthetic": true`, shown with a SYNTHETIC chip). `scripts/export_recordings.py` writes real ones for L14, L06, L08 and L21 in both modes to `data/recordings/` (same layout); F5 copies them into `frontend/public/demo/`, replacing the synthetic set.

### 15.5 Anonymising new stores and photo masking
Seed brands keep their letters from `data/listings_seed.csv` (A, B, … in file order). Any other store gets the next free letter the first time it is fetched or run (its registered domain, its domain stem and its vendor/brand name, unless generic such as "green" or "eco"), stored in `anon_names` so the same store keeps its letter across runs and processes.

Photo masking:
In anonymise mode, `/api/photos/...` and exported recording photos blur every `photo_read` item whose text matches a brand or alias from `data/listings_seed.csv` (Pillow `GaussianBlur(12)` on the box plus 6% padding). Logos without text aren't caught; the README says so.

### 15.6 Frontend
Look and behaviour: `docs/DESIGN.md`; reference look: `docs/design/case_mockup.html`.
```
frontend/
  index.html  package.json  vite.config.ts  tsconfig.json
  public/demo/              # index.json, recordings, photos
  src/
    main.tsx  App.tsx
    routes/                 # Intake, Case, Report, Eval
    styles/tokens.css       # DESIGN §2 tokens, exposed to Tailwind with @theme
    lib/events.ts           # TS types for §15.3
    lib/api.ts              # REST + EventSource; health check; fallback to recordings
    lib/reducer.ts          # one reducer for live and recorded events
    lib/pacer.ts            # release queue: speeds, pause, step (DESIGN §7)
    components/             # TopBar, Seal, Exhibit, Board, ClaimCard, EvidenceCard, Threads, Stamp,
                            # Scan, Ledger, Trace, DirectorBar, CompareSplit, Dossier, EvalChart …
  tests/                    # reducer.test.ts, pacer.test.ts, recordings.test.ts
```
- npm scripts: `dev` (Vite on 5173 with the `/api` proxy), `build`, `typecheck` (`tsc --noEmit`), `test` (`vitest run`), `demo` (`vite preview --port 4173`, recordings only).
- Pin exact dependency versions (`npm install --save-exact`); commit `package-lock.json`.

### 15.7 Store scan (W3)
Give a store's address, get its product pages ranked by how much their green claims need checking. **Triage, not a verdict**: plain code in `praman/scan.py`, zero model calls; every screen and response says so. It doesn't touch the event contract (§15.3).

- **Products:** Shopify stores via `GET <store>/products.json?limit=100` (at most 100); if that fails or isn't Shopify, product URLs (`/products/`, `/product/`, `/p/`, `/item/`, `/shop/` paths on the same site) from robots.txt's `Sitemap:` lines or `/sitemap.xml` (sitemap indexes followed, product sitemaps first; at most 50 pages, each read with the W2 page parser). Same fetching rules as §14 (robots.txt, ≤ 1 request/s per domain, 5 MB, HTML or XML only). The Shopify answer is cached in `data/cache/scans/` (gitignored) so an offline server can rescan it; otherwise offline scans get a 409.
- **Claim terms:** the trigger terms of `data/rules.json` in the title, description and tags: vague (R01, weight 2; "natural", "pure", "clean", "green", "conscious" weight 1), specific (R02, weight 3), compostable/biodegradable with a plastic-like product (R07/R09, weight 4: CPCB registration), comparative (R05) and future (R06, "by 20xx" only) weight 2. Everyday words that are triggers only in context ("only", "first", "free of", "will be") are skipped. One entry per term, with its rule IDs and the sentence it sits in.
- **Proof signals** (subtract from the score): a CPCB-style code (3), a named standard such as IS/ISO 17088 or EN 13432 (3), a certificate or registration number (3), an environmental certifier's name (2; names that are also ordinary words, such as COSMOS, only next to "certif…"), a company-level mark such as B Corp (1), a link to a certificates page (1). Non-environmental approvals (IFRA, FSSAI, PETA …) don't count.
- **Score** = claim-term weights − proof weights, floor 0. Bands: ≥ 8 "Check first", 4–7 "Check soon", 1–3 (or 0 with terms) "Lower", no terms "No claim terms". Ranked by score, then strongest term, then title; unreadable pages last.
- **API:** `POST /api/scans {url, pack?}` → `{scan_id}` (422 unless http(s); 409 offline without a cached store). `GET /api/scans/{id}` → `{id, status: running|finished|error, store, store_url, source: shopify|sitemap, total, done, started_at, finished_at, message, label: "Triage, not a verdict", model_calls: 0, pack, rows: [{product, rank, title, url, score, band: high|medium|low|none, terms: [{term, kind, rule_ids, weight, snippet}], proof: [{kind, text, weight}], reasons: [str], listing_id, error}]}`, anonymised like everything else (store and vendors get letters, §15.5). "Check this product" is `POST /api/runs {scan_id, product}`.
- **Recording:** `scripts/export_scan_demo.py` scans one seed store once and writes `data/recordings/scan_demo.json` and `frontend/public/demo/scan_demo.json` (`{"format": "praman-scan/1", "synthetic": false, "recorded_at", …the GET shape}`), which the `/scan` screen plays without a backend.

---

## 16. Testing

| Layer | What | Network |
|---|---|---|
| Unit | rules matching, CPCB normalisation and matching, verdict table, anonymiser, Shopify parsing from fixtures | None |
| Tool | each tool against fixtures; model calls served from the replay cache | None (`offline`) |
| Golden traces | L14, L06, L08, L21: assert the verdict per key claim and that the tool sequence contains the expected steps (e.g. L14 includes read_photos then cpcb_lookup) | None (`offline`) |
| Evaluation | `eval/run_eval.py` on all labelled listings, agent vs baseline | Replay (live on misses) |
| API | FastAPI `TestClient`: L14 in offline mode streams events in a valid order ending in `run_finished`; report is 409 before approval and 200 after | None (`offline`) |
| Contract | every event in `frontend/public/demo/*.json` validates against `praman/events.py` | None |
| Frontend | Vitest: reducer, pacer, recordings parse; `npm run typecheck`; `npm run build` | None |

CI (GitHub Actions): job 1: `uv sync`, `ruff check`, `pytest` with `PRAMAN_LLM_MODE=offline`. Job 2 (Node 22): `npm ci`, `npm run typecheck`, `npm test`, `npm run build` in `frontend/`. Golden-trace replay entries are committed (no secrets in them).

---

## 17. Evaluation protocol (`eval/run_eval.py`)

1. Load `eval/labels.csv` (claim-level labels; see `eval/labels_template.csv`) and check it with `eval/check_labels.py` (columns; verdicts spelt exactly; every listing id in `data/listings_seed.csv`; a `split` of `dev` or `holdout` per row, one split per listing; claim type, scope, location, rule IDs, covers_claim; unique claim refs). Any problem stops the evaluation with one line per row. Without `eval/labels.csv` the results are `{status: "pending", reason}` and the Evaluation screen says "Pending labels".
2. Run every labelled **dev** listing in agent mode and in baseline mode. **Holdout listings run only with `--holdout`**, once, for the final numbers; until then their split is reported as `{status: "not_run", listings, n_labelled}`. No prompt is ever tuned on them.
3. Align predicted claims to labelled claims: same listing, normalised quote similarity ≥ 0.8 (`rapidfuzz.fuzz.ratio`), else unmatched.
4. Metrics per split and mode: verdict agreement on matched claims and over all labelled claims, a confusion matrix (our label × the mode's verdict, "Not found" for unmatched claims), false Backed count (hard target 0), claims backed only via photo/registry/link, unmatched labelled claims (missed), and model calls, time and cost in total, per listing and as a per-listing average.
5. Report dev and holdout separately.
6. Write `eval/results.md` (tables + disagreements list with run IDs) and `eval_results` rows. A dry run on the template labels (`--labels eval/labels_template.csv`) writes `eval/results_template.*` (gitignored) instead.
7. Also write `eval/results.json`, which `GET /api/eval` returns: `{status: "done", eval_id, generated_at, llm_mode, labels_file, labels_note, splits: {dev|holdout: {status: "done", listings, modes: {agent|baseline: {n_labelled, matched, agree, agreement, agreement_all, false_backed, missed, model_calls, cost_inr, seconds, per_listing_avg: {model_calls, cost_inr, seconds}, by_verdict: {<label>: {expected, predicted, agree}}, confusion: {<label>: {<verdict or "Not found">: n}}}}, per_listing: [{listing_id, agent: {model_calls, cost_inr, seconds, failed}, baseline: {…}}], proof_only_agent: [{listing_id, claim_ref, quote, label, sources, run_id}], disagreements: [{listing_id, claim_ref, quote, expected, agent, baseline, agent_run_id, baseline_run_id}], rows} | {status: "not_run", listings, n_labelled}}}`, or `{status: "pending", reason}`.

---

## 18. Security, privacy, ethics

- `.env` ignored by git; Claude Code is denied reading it (see `.claude/settings.json`).
- No API keys or full prompts in logs, events or anything the frontend receives.
- API binds to 127.0.0.1; CORS limited to the Vite dev origin.
- The repo is public with real store and brand names (team decision, 24 Oct 2026, DECISIONS J10); the careful-language rules (§10.7) apply everywhere. The anonymise switch (`PRAMAN_ANONYMISE`) masks brands for reports shared outside the team.
- **Text addressed to automated checkers** (prompt injection, `praman/injection.py`): narrow patterns ("ignore previous instructions", "note to AI reviewers", "mark this claim as Backed", schema field names, chat-template tokens) are matched in the page text, tags, photo print and linked pages. The sentence holding a match is removed before any model reads it, the trace records it (an `observe` step with the removed lines), and `verdict.injection_guard` turns that page's Backed and Partly backed verdicts into Needs review. No prompt file changes, so clean pages replay as before; every cached listing is tested to match nothing.
- **Reviewer access:** named reviewer keys (`PRAMAN_REVIEWERS="Name:key, …"`, keys of 8+ characters, compared with `hmac.compare_digest`) sign with the key's name. A public server without keys refuses sign-off to visitors; the role switch remains for local runs and the presenter's own laptop. A signed report can't be signed again.
- **Provenance and tamper evidence** (`praman/provenance.py`): each run stores the rulebook version and date, a hash of the prompt files, the models, the CPCB list date and the code commit. Reviews form a SHA-256 hash chain; approval stores a fingerprint over the provenance, every verdict (label, evidence IDs, rule IDs, reason), the chain head and the signer. Reports print it and say whether it still matches. Tamper-evident, not tamper-proof: someone with database access could recompute, but an exported report keeps the original fingerprint.

---

## 19. Build plan

Two Claude Code sessions can run in parallel in the same folder: the **core track** (`docs/WEEK1_PROMPT.md`) and the **frontend track** (`docs/FRONTEND_PROMPT.md`). They meet at the event contract (§15.3) and the recording format (§15.4).

| Target day | Core track | Frontend track |
|---|---|---|
| Sun 18 | M0 setup, data prep, photo probe | F0 scaffold, tokens, fonts, synthetic recordings |
| Mon 19 | M1 core pipeline (L14 end to end in CLI) | F1 Intake and Case layout with the reducer and pacer |
| Tue 20 | M2 agent loop, photos, verdicts, baseline | F2 the four signature moments, trace, director bar |
| Wed 21 | M3 API, events, recordings, report, anonymise, offline | F3 compare, dossier report, evaluation; F4 polish and projector checks |
| Thu 22 | M4 golden tests, evaluation, README, tag `v1.0` | F5 integration with the real API and real recordings (whichever track finishes second does it) |

Stretch (only after `v1.0`): QR decoding, store scan.

---

## 20. Decisions

| ID | Decision | Why |
|---|---|---|
| D-001 | Own loop, no agent framework | Visible steps, easy debugging, easier to explain to judges |
| D-002 | FastAPI + React (Vite) web app; Streamlit dropped (changed 18 Oct) | The demo is judged on what the agent visibly does: a custom UI shows the scan, registry lookup and verdicts as they happen. The core package stays UI-independent, so the risk is contained to `frontend/` and `praman/api.py` |
| D-003 | Rules as data, no RAG | 10–25 rules; exact lookup beats retrieval |
| D-004 | Record/replay model cache | Deterministic demo and free, offline tests |
| D-005 | Code decides clear-cut verdicts | Trust: registry and label rules shouldn't depend on model judgement |
| D-006 | Gemini Flash as primary model | Reads images, structured output, free tier |
| D-007 | Photo reading once per listing | Saves calls; every claim reuses the same print |
| D-008 | Server-Sent Events, not WebSockets | One-way stream, built-in reconnect, simpler server |
| D-009 | Pacing happens in the frontend | Replay mode answers in about a second; the pacer makes runs watchable without slowing the agent |
| D-010 | Bundled recordings as a fallback | The demo still runs if the Python server fails |
