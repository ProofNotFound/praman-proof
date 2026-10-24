# STATUS (core track)

Last updated: 24 Oct 2026 (judging pass on branch `claude/judging`: J1–J14; see below)

## Judging pass (branch `claude/judging`, 23 Oct, not pushed)
Aimed at the five judging criteria; decisions J1–J4 in DECISIONS.md.
- **J1 governance (core):** `reviews` table; `POST /api/runs/{id}/reviews/{claim_id}` (reviewer role, change needs label + reason, closed after sign-off); `/approve` needs the reviewer role and refuses while a Needs review claim is undecided; `/api/runs/{id}` returns `reviews`; report.md/html show the final label, each human review and a Decision log. TRD §15.2 updated. Event contract unchanged.
- **J3 rule packs (core):** `data/rule_packs/food_labels.json` (4 FSSAI-based rules, clauses TODO), `rules.load_pack/list_packs`, `GET /api/rule-packs`, `scripts/export_rule_packs.py` → `frontend/public/demo/rule_packs.json`. The agent still runs only the green pack (see J3).
- Tests: `uv run pytest` all pass (new: role/gate/log API test, rule-pack endpoint and loader tests); ruff clean.
- **J5 hand-check (core):** `eval/hand_check.py` (a person keeps/changes each label; writes back with `(hand-checked)`); `run_eval.py` reports `hand_checked` per split. Run: `uv run eval/hand_check.py --name Savya --n 20`, then `uv run eval/run_eval.py` and copy `eval/results.json` to `frontend/public/demo/eval.json`.
- **J6 sharing (core):** `bash scripts/share.sh` serves this laptop at a free public link (Cloudflare quick tunnel) in replay + public mode, printing the link and an access code. Checked through the link: page 0.28 s, L14 streams all 66 events, live check without code 401, approve without reviewer role 403.
- **J9 rulebook (24 Oct):** 14 rules (R12 technical terms 5(b), R13 nature slogans/imagery Annexure 1 para 5, R14 full research disclosure 6(2)) and the missing CCPA trigger words for R01, R02, R05, R06, R10; checked against the official PDF clause by clause and against all 243 saved claims; demo cases unchanged; full offline suite passes.
- Next: Savya to fill the food pack's TODO clauses/URLs before showing them as citations; a live run on the hosted server to check the reviewer flow over the real API.

## Material fallback (24 Oct, J16)
- **No certificate → check the material:** new fixed tool `check_material` (`praman/tools/material.py`, prompt `check_material.md`): a web-search model (`llm.SEARCH_TEMPLATES`; Groq browser search only since J20) asks whether the material printed on the product has the claimed property. Run by code after the planner loop when the claim would end Partly backed / Not backed / Needs review; one call per property per run. New verdict row 4b (TRD §9): a grounded "yes" → **Backed** ("Backed on its material, not a certificate: …"), ahead of the off-site QR row. Never for pages under R07/R09, plastic or blend material lines, packaging scope, comparisons or future claims.
- **Event contract (TRD §15.3 edited first):** evidence `source` gains `web` (`kind: material_check`). `praman/events.py`, `frontend/src/lib/events.ts`, the evidence card header ("Material check · Google Search") and report labels updated. Recordings unchanged.
- Probe over all 46 cached pages: fires on paper, areca, bamboo, wood-pulp and similar items (L07/Uac502445 Pee Safe, L13, L16, U59bcda6c…); none of the four demo cases. Eval listings that fire will need a live call on their next replay run.
- Tests: `tests/test_material.py` (27; L07 end to end with a stubbed search answer, new fixture `tests/fixtures/replay/L07.json`); `uv run pytest` **286 passed**, ruff clean, demo replays identical.
- **Live (J17):** this Gemini key has no Google Search grounding quota (429 for grounded calls only), so `check_material` falls through to Groq gpt-oss-120b with `browser_search` (`llm._groq_search_call`). Pee Safe (Uac502445) live: both claims **Backed** on glassine paper (surepaperpak.com, jbmpackaging.com, plasticfree.com), ~7 s; answer saved in `data/praman_real.db`. Prompt judges the printed material; coatings go to the caveat unless the listing names one.
- **J20 (24 Oct):** the web search is Groq browser search only: `PRAMAN_SEARCH_MODELS` (comma list, in order; default `PRAMAN_LIVE_MODEL` when it is a gpt-oss model). The Gemini Google Search path (`_search_call`) is deleted; the Gemini key stays for photo reading and as the fallback for every other call. No search model or no Groq key → a plain error, the claim goes to Needs review. 298 tests pass.

## Judging hardening (24 Oct, J11–J14)
- **J11 seller text can't steer the model:** `praman/injection.py` finds sentences addressed to automated checkers (narrow patterns) in page text, tags, photo print and linked pages; removes them before any model call; an `observe` step lists them; `verdict.injection_guard` + `agent.injection_pass` turn that page's Backed/Partly backed into Needs review. No prompt changes; zero matches on all 46 cached listings. `tests/test_injection.py` (22): poisoned L14 page text and pack print replay offline, the model inputs never contain the planted line, no claim stays Backed.
- **J12 reviewer keys:** `PRAMAN_REVIEWERS="Name:key, …"` (`guard.require_reviewer`): key mode signs with the key's name; public server without keys refuses visitors' sign-off (`reviewer_access: off`), the presenter's laptop keeps the role switch. `/api/health` gains `reviewer_access`. Fixed: approving an approved report used to overwrite the signer; now 409.
- **J13 provenance + tamper evidence:** `praman/provenance.py`; `runs.provenance_json` (rulebook version/date, prompts hash, models, CPCB date, commit), `reviews.prev_hash/hash` (SHA-256 chain), `runs.approval_hash` (fingerprint of provenance, verdicts, chain, signer). `db._migrate` adds the columns to older databases. `/api/runs/{id}` gains `audit`; report.md/html gain an Audit section. `tests/test_audit.py`: editing a stored verdict or review after sign-off flips "matches" to "does NOT match".
- **J14 rule packs in the store scan:** `POST /api/scans {url, pack}`; `scan.triage(..., pack)`; `scans.pack` column; food certifiers (Jaivik Bharat, India Organic, NPOP, PGS-India) count as proof signals. Zero model calls, tested.
- TRD §15.2/§15.7/§18, DEPLOY.md (`PRAMAN_REVIEWERS`), render.yaml, README and HACKATHON_BRIEF Q&A updated. Event contract unchanged (the guard step uses the existing `observe` phase).
- Tests: `uv run pytest` **259 passed**, ruff clean; `tests/test_demo_unchanged.py` still passes (demo cases replay identically).
- **J18 (24 Oct):** a failed material check is now Needs review and isn't listed as searched; `Feature_Compostable`-style tags get a material check. 295 tests pass. Checked on the coir scrub and neem comb pages with a stubbed search: Backed on material where the page names a material; slogans stay Not backed. Live search was unavailable today (Groq and Gemini 3.8 Flash daily quota used up), so the real search path was not re-verified.
- Next: set `PRAMAN_REVIEWERS` on Render (until then Render visitors can read but not sign); redeploy Vercel from the final commit; Savya to hand-check the 33 holdout labels (`uv run eval/hand_check.py --name Savya --split holdout`), rerun `uv run eval/run_eval.py --holdout`, copy `eval/results.json` to `frontend/public/demo/eval.json`; fix the `labels_note` in `eval/results.json` once it's settled who labelled the dev set.

## Final summary: week 2 (branch `claude/week2`, 5 commits on top of main, not pushed)

**Milestones completed (all five):**
| Commit | Milestone |
|---|---|
| `W1: corrected seal, working URL box, quota-safe errors` | Seal reference files committed (the per-character seal was already on main; checked at 4×). URL box types and submits in every mode. A model quota/rate-limit error finishes the run with unchecked claims at Needs review ("Model quota reached …") and one calm line in the UI. |
| `W2: generic product pages via JSON-LD and HTML` | Shopify → JSON-LD → OpenGraph + readable text; timeouts, 5 MB, content type; "Couldn't read this page" for JavaScript-built pages; persisted anonymiser letters for new stores. |
| `W3: store scan triage with zero model calls` | `POST/GET /api/scans`, `/scan` screen, "Triage, not a verdict", recorded scan of an anonymised seed store for no-backend mode. |
| `W4: QR decoding on product photos` | `decode_qr` tool (OpenCV), same-site follow, other domains "not followed" → Needs review, QR card and Scan box. Only new dependency: `opencv-python-headless`. |
| `W5: evaluation splits, label checker, preflight` | `eval/run_eval.py` per split with confusion matrices and per-listing calls/time/cost; `eval/check_labels.py`; holdout never run without `--holdout`; `scripts/preflight.sh`; README. |

**Test results (19 Oct, last run):** `uv run ruff check .` clean, `ruff format --check` clean; `uv run pytest`: **160 passed** (was 109), all offline, including the golden traces and the new `tests/test_demo_unchanged.py`, which replays all eight demo runs (L14, L06, L08, L21 × agent/text-only) and finds every event identical to `data/recordings/`. Frontend: `npm run typecheck` clean, `npm test` **59 passed** (was 50), `npm run build` clean. `bash scripts/preflight.sh`: **13 passed, 0 failed** (API offline plays L14 to `run_finished`, 66 events; `npm run demo` serves every bundled file). Screens looked at 1280×720 and 1920×1080 (intake, scan, eval also in present mode; screenshots in `frontend/screenshots/`).

**Event contract changes (CLAUDE.md rule 12; TRD §15.3 edited first, then both event files):** optional `run_finished.quota_reached` (W1) and optional evidence `qr: {domain, followed, path?}` (W4). Nothing renamed or removed; the bundled recordings are unchanged and still validate.

**Needs a live run:**
- W2: done (21 Oct live run of non-Shopify product page `bambooproducts.in/product/bamboo-soap-dish/` end to end).
- W3: done (21 Oct store scan of `bambooproducts.in` and "Check this product" on row 9).
- W4: done (21 Oct live run of `Uac502445` with pack QR code, `decode_qr` executed and third-party domain gated).
- W5 dev evaluation: done (21 Oct, all 21 dev listings in both modes, results in `eval/results.md` and README). Holdout evaluation left for Savya to run once at the very end (`uv run eval/run_eval.py --holdout`).

**Known issues:**
- Your API on :8000 (pid started from main before this branch) runs the old code; restart it after merging. While anything listens on :8000, `npm run demo` proxies `/api` there (vite preview reuses the dev proxy), so it plays through that server instead of the bundled recordings; `preflight.sh` warns about it.
- L14's store answered `/products.json` with 429 (rate-limited), so the recorded scan came from its sitemap (50 pages at one request a second). Live Shopify scans fall back the same way and then take about a minute.
- QR decoding happens when photos are downloaded, so it applies to listings fetched from now on. L06 and L07 have QR codes on their packs but were cached before W4; don't re-fetch them with `scripts/fetch_cache.py --force` before the event, or L06's demo run changes.
- In anonymise mode the photo mask blurs QR codes that link to a store domain (their `photo_read` text names the masked domain). Only new listings have QR items.
- `eval/results.json` and `frontend/public/demo/eval.json` now say "Pending labels"; the template numbers moved to a dry run (`--labels eval/labels_template.csv` → gitignored `eval/results_template.*`).
- `docs/DESIGN.md` still describes the old seal (`textPath`, 28 px) and a 56 px top bar; the app follows `docs/design/praman_seal.svg` and a 72 px bar (noted by the frontend track; DESIGN.md is in neither track's paths, so it wasn't edited).

**Check by hand:**
- Intake: paste one demo listing's real URL with the server stopped (`cd frontend && npm run build && npm run demo`, nothing on :8000): its recorded case should open.
- `/scan` in live mode on a store you choose (it reads up to 100 products, or 50 pages at one per second).
- A live run of a page with a QR code, if you have one, to see the QR card and the Scan box with real boxes.
- The four demo cases on the projector, with and without the backend (they are unchanged; the new test proves the events match).

**Merge `claude/week2` into `main` after review (don't push until you've run the demo):**
```bash
git switch main
git merge --no-ff claude/week2 -m "Week 2: generic pages, store scan, QR codes, evaluation splits, preflight"
uv sync
cd frontend && npm ci && npm run build && cd ..
bash scripts/preflight.sh
```
If anything is off: `git merge --abort` during the merge, or `git reset --hard ORIG_HEAD` right after it (main is untouched until you merge).

## Week 2 (branch `claude/week2`, not merged; main is the known-good demo)
| Milestone | Status |
|---|---|
| W1 corrected seal, working URL box, quota-safe errors | Done |
| W2 generic product pages via JSON-LD and HTML | Done |
| W3 store scan triage with zero model calls | Done |
| W4 QR decoding on product photos | Done |
| W5 evaluation splits, label checker, preflight | Done |

**W1 (19 Oct):**
- Seal: already per-character from `docs/design/praman_seal.svg` on main; the reference SVG/PNGs are now committed in `docs/design/`; re-checked at 4× in the top bar (no overlap).
- Quota: a model 429/quota error after every retry raises `llm.QuotaReached`; the run finishes with `run_finished.quota_reached: true` (TRD §15.3, optional field, both event files) and every unchecked claim is Needs review ("Model quota reached; …"). The board, the on-screen report and both server reports say so in one line.
- URL box: types and submits in every mode. `POST /api/runs` opens a seed listing's URL (real or `brand-x.example/products/<handle>`) in any LLM mode; other URLs need live mode (409 with a plain line and the case files as buttons) and must be http(s) (422). Without a backend, `frontend/public/demo/urls.json` (hashes only, from `scripts/export_demo_urls.py`) lets a demo listing's URL open its recording.
- Tests: `tests/test_quota.py` (5), two API tests, a URL-keys contract test; frontend `tests/urls.test.ts` (4).

**W2 (19 Oct):**
- `fetch_listing` (`praman/tools/fetch.py`) tries Shopify `.json`, then any product page through `praman/tools/page.py`: schema.org Product JSON-LD (name, description, brand, images; `source = "json_ld"`), else OpenGraph tags plus the main readable text and large gallery images (`source = "html"`, ≤ 10 photos). 15 s timeouts, HTML content types only, 5 MB cap, same-site redirects only. JavaScript-built pages and pages without a product get a "Couldn't read this page…" line (400 from `POST /api/runs`, shown in the URL box), never an empty run.
- Anonymiser: stores outside the seed file get the next free letter (I, J, …) in SQLite `anon_names` (domain, stem and vendor), so the same store keeps its letter; generic words are never masked.
- Tests (offline): `tests/test_page.py` (10: JSON-LD, OpenGraph-only, no product, JavaScript shell, two anonymised seed pages L15/L09, and `fetch_listing` over a mock network: Shopify first, JSON-LD fallback, content type, 5 MB cap), two anonymiser tests. Fixtures in `tests/fixtures/html/`.

**W3 (19 Oct):**
- `praman/scan.py`: a store's products from Shopify `/products.json` (≤ 100) or its sitemap (≤ 50 product pages via the W2 parser), each triaged in code only: claim terms from `data/rules.json` with their rule, proof signals (CPCB codes, standards, certificate numbers, certifiers, company marks, certificate links), a score and a band. Labelled "Triage, not a verdict" everywhere; `model_calls` is always 0.
- API: `POST /api/scans`, `GET /api/scans/{id}` (TRD §15.7, new section; event contract unchanged); `POST /api/runs {scan_id, product}` for "Check this product". `praman/seeds.py` now holds the seed-URL lookup.
- Recording: `scripts/export_scan_demo.py` scanned L14's store once (its `/products.json` was rate-limited, so 50 sitemap pages at 1/s) → `scan_demo.json` in `data/recordings/` and `frontend/public/demo/` (anonymised, brand-free, L14 at rank 10).
- Tests: `tests/test_scan.py` (9: scoring, look-alike names, ranking, offline API with a fixture store, zero model calls, 404/409/422, sitemap path over a mock network); recording test for the scan.

**W4 (19 Oct):**
- New allow-listed tool `decode_qr` (`praman/tools/qr.py`, registered in `praman/agent.py`, validated by `ToolCall`, in the TRD tool list): OpenCV `QRCodeDetector` (multi-code, upscaled retry) at photo download time, stored per photo; same-site links are opened and searched for proof, other domains become "QR code links to <domain>; not followed" and keep the claim at Needs review. Planner option only after photos and only with stored codes; default order text → photos → QR → registry → link. Dependency added: `opencv-python-headless`.
- **Event contract (rule 12):** evidence may carry optional `qr: {domain, followed, path?}` (TRD §15.3 first, then `praman/events.py`, `frontend/src/lib/events.ts`). W1 added `run_finished.quota_reached`.
- Demo safety: `tests/test_demo_unchanged.py` replays all eight demo runs offline and compares every event with `data/recordings/` (only ids, timings and photo URLs ignored): identical.
- Tests: `tests/test_qr.py` (6: generated same-domain, other-domain, two-per-photo and unreadable codes; planner gating; follow/not-follow evidence and the Needs review verdict; text codes).

**W5 (19 Oct):**
- `eval/run_eval.py`: checks the labels first; runs dev listings only (holdout only with `--holdout`, reported as "not run" until then); per split and mode: agreement, confusion matrix, false Backed (target 0), proof only the agent found, model calls/time/cost in total, per listing and per-listing average; `eval/results.md` and `results.json` (TRD §17 updated). Without `eval/labels.csv`: "Pending labels" (now the committed state). Evaluation screen shows the confusion matrices, the per-listing table and a "not run yet" holdout section.
- `eval/check_labels.py`: columns, exact verdict spelling (with "did you mean"), known listing ids, split present and consistent, claim fields, rule IDs; one line per problem with its row; runs nothing.
- `scripts/preflight.sh`: tools, Python env, frontend build, recordings (both contracts + demo runs unchanged), offline API plays L14 to `run_finished`, `npm run demo` serves everything; PASS/FAIL per check.
- README: generic pages, store scan and QR codes, with anonymised examples; preflight and label commands; results now "Pending labels" with the template as a dry run.
- Tests: 7 more in `tests/test_eval.py` (label checker errors, header, holdout never run, summary metrics, pending).

### Next steps
1. Review the branch and merge it (commands in the final summary above), then restart your API.
2. Write `eval/labels.csv` (21 seed + 10 holdout; add the holdout listings to `data/listings_seed.csv` and cache them first), check it, run the dev evaluation; run `--holdout` once at the end.
3. Before the event: `bash scripts/preflight.sh`.

### Needs a live run
- W1: nothing (the quota path is tested with a simulated 429).
- W2: done (21 Oct live run of non-Shopify product page `bambooproducts.in/product/bamboo-soap-dish/` end to end).
- W3: done (21 Oct store scan of `bambooproducts.in` and "Check this product" on row 9).
- W4: done (21 Oct live run of `Uac502445` with pack QR code, `decode_qr` executed and third-party domain gated).
- W5 dev evaluation: done (21 Oct). Holdout set evaluation left for Savya at the very end (`--holdout`).

## Summary
- **Milestones:** M0–M4 done and tagged `v1.0` (one wording-polish commit on top). **F5 done (frontend track, 18 Oct):** the web app in `frontend/` plays all four cases in both modes through the API and from the bundled recordings; no changes to `praman/` were needed.
- **Photo probe (live, `gemini-3.8-flash`): PASS.** L14 photo 7 returned both CPCB codes exactly (`CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443`, `CPCB-UPC-II/SUNSHIELD BIOTECH LLP/Gujarat/131`) and "100% ecofriendly, 0% plastic."; L06 photo 3 returned "Carrier Resin- PE Virgin Grade … Additive(%)- 5". Boxes for every item (13/13), ~10 s per photo.
- **Demo verdicts (agent, replay), matching PRD §12:**
  - L14: compostable = Backed (both makers on the CPCB list); "0% plastic" = Contradicted; industrial-composting label = Needs review.
  - L06: eco-friendly and oxo-biodegradable = Contradicted (pack prints virgin PE + additive).
  - L08: plastic-free = Contradicted (nylon bristles); zero waste = Contradicted; bamboo handle = Partly backed (B Corp is company-level).
  - L21: Not a claim, no tool calls.
- **CPCB list (18 Oct, from the PDF Savya saved):** 172 certified rows (Table 1) and 128 uncertified (Table 2) in `data/cpcb_certified.csv`; S.No. 32 Greendotbiopak and S.No. 2 Sunshield Biotech Llp both in Table 1 (Gujarat). No phone numbers, emails or websites in the CSV, so none in the API, events or recordings. The demo ledger reads "CPCB CERTIFIED LIST · 26 OCT 2023 · 172 ROWS" on L14.
- **Review fixes (18 Oct, evening):** no brand name, email, URL or phone number is readable in any of the 25 photos of the four demo listings (checked by eye, zoomed, plus an OCR read-back that finds none); photo masking now blurs contact data and brand text from `photo_read` items, a cached local OCR pass (upright and rotated) and three hand-reviewed boxes; emails and phone numbers are hidden in event text. Trace rows are one sentence (longest 109 characters), details in the step payload. CCPA clause numbers, official URL and file number are in `data/rules.json`. None of it touched a prompt: all eight demo runs replayed offline from the committed fixtures before the single re-export.
- **Tests (after the review fixes):** 109 Python tests passing offline; ruff clean; frontend typecheck, 46 tests and build pass; 32 screenshots retaken in `frontend/screenshots/`.
- **Tests (earlier):** 106 passing offline (`uv run pytest`), `ruff check` and `ruff format --check` clean; frontend `npm ci`, `npm run typecheck`, `npm test` (44) and `npm run build` pass. `bash scripts/demo.sh` served the app on :8000 and L14 played to its verdicts.
- **Evaluation (template labels only, 5 claims; real labels pending):** agent 5/5 agree, 0 false Backed; text-only 1/3 matched, 2 not found; proof only the agent found: 1 (L14 compostable, via photo + registry). See `eval/results.md`.
- **Known issues:**
  - Still the free tier: a live call to `gemini-3.8-flash` on 18 Oct hit the 20-requests-a-day quota again, so the fallback recordings (L08, L21, baselines, rewrites) stay; see the quota steps below.
  - Photo masking can miss very small print.
- **Run the demo offline:**
  ```bash
  uv sync
  PRAMAN_LLM_MODE=offline bash scripts/demo.sh
  ```
  It builds the frontend and opens http://127.0.0.1:<port>. `PRAMAN_MODEL` now defaults to `gemini-3.8-flash`, so a fresh checkout replays the committed fixtures without `.env`. Without Python: `cd frontend && npm run build && npm run demo` plays the 8 bundled recordings. Terminal version, no web app:
  ```bash
  PRAMAN_LLM_MODE=offline uv run scripts/run_one.py L14
  ```
  (also L06, L08, L21; add `--mode baseline` for text-only).

## Done
- **M0** setup and data prep:
  - uv project, package layout, config, models, SQLite schema (incl. `events`).
  - Gemini client with record/replay cache (`praman/llm.py`): fails over to the fallback model on quota, low thinking for short calls.
  - Polite fetcher and Shopify parser.
  - 21 seed listings and 151 photos cached; photo scores kept in the listing JSON.
- **M1** core pipeline:
  - Rules engine (`praman/rules.py`) and tools: `extract_claims` (incl. photo alt text), `search_text` with the evidence judge, `read_photos`, `cpcb_lookup`, `fetch_linked_page`, `rule_lookup`, `check_consistency` (code signals + model pass), `write_rewrite`.
  - Verdict table with both guards (`praman/verdict.py`).
  - `scripts/run_one.py`.
- **M2** agent:
  - Agent loop (`praman/agent.py`): plan → act → observe → decide; follow-up and model budgets; claims printed only on photos join the queue; required-label checks as derived claims.
  - Baseline (`praman/baseline.py`); event models and sink (`praman/events.py`); anonymiser (`praman/anonymise.py`).
  - `scripts/export_recordings.py` writes `data/recordings/` and `tests/fixtures/replay/`; golden traces in `tests/test_golden_traces.py`.
- **M3** web API:
  - `praman/api.py` covers every TRD §15.2 endpoint: SSE with `Last-Event-ID` resume and a 15 s ping; photos with brand text and logos blurred; compare with claim pairs; eval.
  - Serves `frontend/dist` with an SPA fallback; CORS for the Vite origin only; binds to 127.0.0.1.
  - `praman/report.py`: Markdown and HTML dossier, 409 until approved, PRD §8 disclaimer.
  - `scripts/demo.sh`, with a port fallback.
- **M4** release:
  - `eval/run_eval.py` writes `eval/results.md` and `eval/results.json`, which `GET /api/eval` serves.
  - README (anonymised examples only); GitHub Actions CI (Python job offline; Node 22 job runs once `frontend/package.json` exists).

## Milestones (core track)
| Milestone | Target | Status |
|---|---|---|
| M0 setup + data prep | Sun 18 | Done (full CPCB list built 18 Oct) |
| M1 core pipeline (L14 end to end in CLI) | Mon 19 | Done |
| M2 agent loop, photos, verdicts, baseline | Tue 20 | Done |
| M3 API, events, recordings, report, anonymise, offline | Wed 21 | Done |
| M4 golden tests, evaluation, README, tag v1.0 | Thu 22 | Done (`v1.0`) |
| F5 integration | Thu 22 | Done by the frontend track (see `docs/FRONTEND_STATUS.md`) |

The frontend track's milestones (F0–F5) are in `docs/FRONTEND_STATUS.md`.

## Blockers / open questions (Savya)
- **Model quota:** the free tier allows **20 requests per day** for `gemini-3.8-flash`; it ran out on 18 Oct after L14 and most of L06. Since then the fallback `gemini-3.5-flash-lite` answers. L08, L21 and the baselines were recorded with it; its answers are cached under the primary model's key. For final recordings with the primary model:
  1. Enable billing on the key.
  2. Delete the fallback's cached rows:
     ```bash
     sqlite3 data/praman.db "delete from llm_cache where model='gemini-3.5-flash-lite'"
     ```
  3. Re-record:
     ```bash
     uv run scripts/export_recordings.py
     ```
  4. Then `uv run eval/run_eval.py` and `uv run pytest`.
- **CPCB list:** rebuild with `uv run scripts/build_cpcb_csv.py` if CPCB publishes a newer PDF (save it by hand; robots.txt disallows automated download). The PDF stays out of git (contact data).
- **Labels:** `eval/labels.csv` (21 seed + 10 blind holdout) doesn't exist yet. Evaluation numbers come from the 5-claim template and say so.
- **Port 8000:** was free on 18 Oct afternoon; if OrbStack holds it again, `scripts/demo.sh` picks the next free port (Vite's dev proxy expects 8000).
- **Rule clauses:** all CCPA clauses are now filled in (R01–R06, R10, R11); R07–R09 cite the PWM rules.
- **Timing:** live runs take 30–90 s depending on model latency, and the 90 s wall budget turns unfinished claims into Needs review. Replay runs take under a second.

## Next
1. F5 follow-ups done: `PRAMAN_MODEL` default matches the fixtures; `data/praman.db-shm`, `-wal` and `.claude/settings.local.json` are gitignored.
2. Stretch is held for the event-day slot (PRD §11, v1.1 on a branch). QR codes decode on only 2 seed photos, both to a third-party shortener we may not fetch, so a store scan is the better candidate (see DECISIONS).

## Handoff log

### 20 Oct 2026 · opencode · evaluation labels draft (task 1)
- Added `eval/labels_draft.csv`: 81 claim rows for seed listings L01–L21, all split `dev`, with the template's 14 columns and a note on every row. `uv run eval/check_labels.py --labels eval/labels_draft.csv` prints `dev: 21 listings, 81 labelled claims` and `OK: labels are valid.` No agent was run and no model was called.
- Claims come from the cached listing text, tags and photos; photo-only wording was checked with local OCR on the cached images (L11, L13, L14, L18, L19, L20). Expected verdicts follow the seed notes, `docs/STATUS.md` expectations and the TRD §9 table.
- Could not verify: the L13 conflicting figures (seed notes say 200 uses and 2.5x absorbency elsewhere, but the cached page and photos show 100 uses and 5x). Those two rows are marked `Contradicted` with a note asking Savya to confirm; if the figures are not on the page, change them to `Not backed`.
- Judgment calls left for Savya: L08 `eco-friendly` and L14 `GREEN MATERIAL` are stricter (`Not backed`) than the recorded agent runs (`Partly backed`); L15/L16 vague eco-friendly claims are `Partly backed` because the general certificates page gives partial disclosure.
- Files: `eval/labels_draft.csv`, `docs/STATUS.md`, `docs/DECISIONS.md`. Branch: `opencode/eval-labels-draft`. Committed as `a3c6a9b`; not pushed.

### 20 Oct 2026 · opencode · reviewed evaluation labels saved as `eval/labels.csv` (task 1)
- Applied Savya's review: removed `L06-C3`; changed `L10-C4` to `Contradicted`; changed `L18-C1` to `Not backed`; set `labeller` to `Savya` on all 80 rows; saved the reviewed file as `eval/labels.csv`.
- L13: no `200 uses` or `2.5x` figure appears in the cached listing or photos, so `L13-C2` and `L13-C3` are now `Not backed`; their quotes were narrowed to the exact photo wording (`REUSABLE UPTO 100 TIMES`, `5X MORE ABSORBENT`).
- Checked every quote against `data/cache/listings/` and `data/recordings/`, plus local OCR/visual checks for photo-only claims. Removed ellipses and fixed photo wording (for example `TAKES ONLY 180 DAYS TO DECOMPOSE`, `CERTIFIED PLASTIC NEUTRAL PRODUCT`, `OUR FIRST 3 BLADE ECO FRIENDLY RAZOR IN INDIA`, `Tested at 'Govt approved Laboratory'`).
- Could not confirm `L14-C4` word-for-word: it is the derived required-label row (`compostable only under industrial composting (required label)`), not a listing quote; no such label is visible in the page text or photos. It stays `Needs review`.
- `uv run eval/check_labels.py` prints `dev: 21 listings, 80 labelled claims` and `OK: labels are valid.` Ruff, 160 Python tests, frontend typecheck/59 tests/build, and `bash scripts/preflight.sh` (`PREFLIGHT PASS`) all pass. No agent was run and no model was called.
- Files: `eval/labels.csv`, `docs/STATUS.md`, `docs/DECISIONS.md`. Branch: `opencode/eval-labels-draft`. Not pushed.

### 20 Oct 2026 · opencode · 10 holdout listings added and cached (task 2)
- Added `L22`–`L31` to `data/listings_seed.csv`, one page each from the eight seed stores and none of the existing 21. `L24` uses `biodegradable-tampons-super-plus-16-tampons-byoc` (the page without the `-copy` suffix).
- Cached all 10 with `uv run scripts/fetch_cache.py L22 L23 L24 L25 L26 L27 L28 L29 L30 L31`: `10 cached, 0 failed`; image counts are 7, 3, 3, 3, 9, 4, 8, 1, 7 and 7. The cached image files stay gitignored.
- No labels were written and no agent was run on these pages: `expected_main_verdict` and `contradiction` are blank in the seed rows, and each note says the holdout is left for Savya to label.
- Checks after adding them: `uv run eval/check_labels.py` still passes (`dev: 21 listings, 80 labelled claims`); ruff, 160 Python tests, frontend typecheck/59 tests/build, and `bash scripts/preflight.sh` (`PREFLIGHT PASS`) all pass.
- Files: `data/listings_seed.csv`, `data/cache/listings/L22.json`–`L31.json`, `docs/STATUS.md`, `docs/DECISIONS.md`. Branch: `opencode/eval-labels-draft`. Not pushed.

### 20 Oct 2026 · opencode · DESIGN.md matched to the week-2 app (task 3)
- Updated `docs/DESIGN.md` only: per-character seal from `docs/design/praman_seal.svg`, 72px top bar with the 54px seal and 26px wordmark, URL box usable in every backend mode, `/scan` screen ("Triage, not a verdict"), QR evidence card, evaluation confusion matrices and per-listing table with "Pending labels", and the quota line.
- No code, prompts, recordings, fixtures or labels changed. `ruff`, 160 Python tests, frontend typecheck/59 tests/build, and `bash scripts/preflight.sh` (`PREFLIGHT PASS`) all pass.
- Files: `docs/DESIGN.md`, `docs/STATUS.md`. Branch: `opencode/eval-labels-draft`. Not pushed.

### 21 Oct 2026 · opencode · dev evaluation and live checks
- Committed `eval/spot_check.md` (15-row dev label spot-check).
- Verified `eval/labels.csv` with `uv run eval/check_labels.py` (21 dev listings, 80 labelled claims, OK).
- Ran dev evaluation: `uv run eval/run_eval.py` (dev only, no `--holdout`). Completed cleanly across all 21 dev listings in both modes, generating `eval/results.md` and `eval/results.json`. Dev agent: agreement 34/62 (55%) matched, 42% overall, 0 false Backed, 18 missed, 8 pieces of proof found only by the agent; text-only baseline: 26/54 (48%) matched, 32% overall, 0 false Backed, 26 missed.
- Updated `README.md` Results section with the real dev evaluation metrics. Note: Preliminary: 6 of 42 runs were cut short by the model quota, and most answers came from the fallback model (6 runs hit the Gemini quota—L03, L05, L09, L12, L17 agent and L09 baseline; 21 verdicts say “Model quota reached”, and almost all answers came from fallback model `gemini-3.5-flash-lite`).
- Live checks (report only, no code changed):
  - (a) Non-Shopify product page: Tested `https://bambooproducts.in/product/bamboo-soap-dish/` (WooCommerce, schema.org Product JSON-LD, store outside seed listings) end-to-end through `POST /api/runs` in live mode (Run ID `U8128dc3d-a-0e9893`). Completed in 25 steps to `finished` status (C1 Partly backed, C2 Not a claim, C3 Contradicted due to material mismatch between title and photo print). Primary model hit daily free-tier quota (429), and fallback `gemini-3.5-flash-lite` completed the run cleanly.
  - (b) Store scan of that store and "Check this product": Ran `POST /api/scans` on `https://bambooproducts.in` (Scan ID `S203ed79c`). The sitemap crawler triaged all 21 products in 36 seconds with zero model calls (found 4 to check first/soon). Called "Check this product" on row 9 (`Natural Lofah - Pack of 2`, Rank 1) via `POST /api/runs` (Run ID `Ue6e292ce-a-343af2`), which completed in 18 seconds to `finished` status (C1 Not backed, C2 Not a claim, C3 Contradicted).
  - (c) Pack photo carrying a QR code: Tested `https://peesafe.com/products/disposable-toilet-seat-cover-pack-of-10` (Listing ID `Uac502445`), whose Photo 3 carries a QR code (`https://me-qr.com/I8rgLVJD`). At fetch/download time, OpenCV decoded the code into `photo.qr`. During the agent live run (`Uac502445-a-9f4b92`), the planner selected `decode_qr` after photo reading; `act_decode_qr` detected that the target domain was outside the store (`me-qr.com`), added polite-crawl evidence `QR code links to me-qr.com; not followed`, and the verdict for that claim correctly became `Needs review`.
- What worked: All three live checks completed end-to-end to `finished` status. JSON-LD parsing, sitemap discovery, store scan triage, scan-to-product-run handoff, and photo QR code detection with third-party domain gating all functioned as designed.
- What failed / noted: The primary model `gemini-3.8-flash` free-tier daily quota is exhausted (429 RESOURCE_EXHAUSTED); the existing fallback `gemini-3.5-flash-lite` transparently answered and completed all live calls.
- Files: `eval/spot_check.md`, `README.md`, `eval/results.md`, `eval/results.json`, `docs/STATUS.md`. Branch: `opencode/eval-labels-draft`. Not pushed.

### 21 Oct 2026 · opencode · dev evaluation re-run without quota cutoffs
- Re-ran dev evaluation on main (`uv run eval/run_eval.py`, dev only): 0 of 42 runs hit `quota_reached` in `run_finished` (0 quota cutoffs, down from 6; 0 quota-truncated verdicts).
- Updated dev metrics: agent agreement 39/62 (63%) matched, 49% overall, 0 false Backed, 18 missed, 8 proof only agent found; text-only baseline 28/54 (52%) matched, 35% overall, 0 false Backed, 26 missed.
- Set `labels_note` in `eval/results.json` and blockquote callout in `eval/results.md` to "Most model answers came from the fallback model gemini-3.5-flash-lite", and updated the README Results note accordingly.
- Files: `eval/results.json`, `eval/results.md`, `README.md`, `docs/STATUS.md`. Branch: `main`. Not pushed.

### 21 Oct 2026 · ai · holdout evaluation, demo script, and backup video setup
- Branch: `ai/holdout-and-demo`.
- Holdout labels for `L22`–`L31`: added 33 rows to `eval/labels.csv` with `split = holdout`, exact quotes from cached listings (`data/cache/listings/`) and pack photos (`data/cache/images/`) via local OCR (no agent run, no recordings opened), `labeller = "AI (not hand-checked)"`. Strict criteria applied: Backed only with product-specific visible proof. `uv run eval/check_labels.py` passed (`dev: 21 listings, 80 labelled claims; holdout: 10 listings, 33 labelled claims; OK: labels are valid.`).
- Ran holdout evaluation once (`uv run eval/run_eval.py --holdout`): 0 of 20 holdout runs hit `quota_reached` in `run_finished` (0 quota cutoffs across dev and holdout; 0 verdicts mentioning "Model quota reached"). Fallback model `gemini-3.5-flash-lite` successfully answered all live calls.
- Holdout results:
  - Agent: agreement 18/26 (69%) matched, 55% overall, 0 false Backed, 7 missed, 2 proof only agent found (L29-C1 via link, L30-C4 via photo), 109 calls (10.9 avg), ₹8.90 (0.89 avg), 434.6s (43.5s avg).
  - Text-only: agreement 21/25 (84%) matched, 64% overall, 0 false Backed, 8 missed, 40 calls (4.0 avg), ₹2.94 (0.29 avg), 27.2s (2.7s avg).
- Updated `README.md` Results section with holdout numbers, explicitly stating that both dev and holdout labels were generated by AI, not by hand, and that most model answers came from fallback model `gemini-3.5-flash-lite`. Updated `eval/results.json` (`labels_note`) and `eval/results.md`.
- Presenter demo script: created `docs/DEMO_SCRIPT.md` detailing the 5-minute presenter walkthrough of the 4 cases (L14, L06, L08, L21), keyboard controls (1–4, P, Space, →, B, E), narration for each step, store scan triage explanation, and tiered fallback plans (replay mode, `npm run demo` offline bundled recordings, and live Vercel mirror at `https://praman-rho.vercel.app`).
- Backup video: built frontend, created `scripts/record_demo.cjs` to automate Playwright recording of all 4 cases in present mode at 1× speed with Compare mode on L14 and Store Scan triage, saved 1920×1080 video to `demo-video/praman_demo_1080p.webm`, and added `demo-video/` to `.gitignore` (uncommitted).
- Files: `eval/labels.csv`, `eval/results.json`, `eval/results.md`, `README.md`, `docs/DEMO_SCRIPT.md`, `scripts/record_demo.cjs`, `.gitignore`, `docs/STATUS.md`. Branch: `ai/holdout-and-demo`. Not pushed.


### 22 Oct 2026 · opencode · hackathon framing for Retail and Supply
- Reframed the submission for the organisers' domain requirement without touching the product: added the domain and the four-stage process map to `README.md` and `docs/PRD.md` (§1.1 plus a header row), added a business-framing block and a value-aware opener/closer to `docs/DEMO_SCRIPT.md`, and wrote `docs/HACKATHON_BRIEF.md` (domain fit, measured value, responsible-AI controls, judge Q&A, 60-second pitch, submission checklist).
- Every figure comes from `README.md` and `eval/results.md`. The brief discloses the holdout result (baseline 84% vs agent 69% on matched claims) and the AI-assisted labels in the same table, rather than in a footnote.
- No code, prompts, recordings, fixtures or labels changed; the demo cases and their events are untouched. Could not verify: anything about the judging rubric (not published) or a live projector run; the brief tells the presenter to rehearse both the online and offline paths.
- Files: `README.md`, `docs/PRD.md`, `docs/DEMO_SCRIPT.md`, `docs/HACKATHON_BRIEF.md`, `docs/DECISIONS.md`, `docs/STATUS.md`. Branch: `opencode/hackathon-framing`. Not pushed.
- Housekeeping: `graphify-out/` (generated knowledge-graph output from the hackathon prep run) is now in `.gitignore` and in ruff's `extend-exclude`, so `ruff check .` and `git status` stay clean without touching the generated files.

### 23 Oct 2026 · claude · hosted deployment (public mode, access code, Render blueprint)
- New `praman/guard.py` and `PRAMAN_PUBLIC_MODE` (off by default, on in the `Dockerfile`): every outgoing request, redirects included, must resolve to a public address on port 80/443 (`PoliteClient` request hook); checks beyond the four demo cases (new URL, new store scan, non-demo seed listing) need `X-Access-Code` = `PRAMAN_ACCESS_CODE`, a per-address hourly limit (6) and a daily cap (20). No code configured = live checks off (403). Settings added in `praman/config.py`; `/api/health` gains `live_checks` and `needs_access_code` (additive, not part of the event contract).
- `GET /api/photos/{id}/{n}` falls back to the masked photos in `data/recordings/photos/` when the downloaded photo files are missing (they are gitignored, so a fresh deploy has none). `POST /api/runs` and `POST /api/scans` take the request for the gate; the 409 "needs live mode" answer is unchanged for servers that can't check new pages.
- Frontend: `components/AccessCode.tsx` (password field on the URL box and store scan, shown only when the server asks; kept in `sessionStorage`), `accessHeaders()` on run/scan requests, `canCheckNewPages()` replaces the `llm_mode === "live"` test on the intake screen.
- Deploy files: `render.yaml` (Render blueprint), `Dockerfile` (PRAMAN_PUBLIC_MODE=1), `.dockerignore`, `docs/DEPLOY.md` (runbook, settings, limits).
- Verified: ruff clean; `uv run pytest` all pass, offline (18 new tests in `tests/test_guard.py`); frontend typecheck, 59 tests and build pass. Ran the API locally with `PRAMAN_LLM_MODE=replay PRAMAN_PUBLIC_MODE=1` and a dummy key: L14 replayed 66 events to the recorded verdicts with no model call, the SPA deep link and a photo served, and `127.0.0.1` / `169.254.169.254` were refused with the code.
- **Docker (verified later the same day):** `docker build --platform linux/amd64 .` first failed (the image lacked `README.md`, which `pyproject.toml` names as the readme); fixed in the Dockerfile. The rebuilt image ran with `PRAMAN_ACCESS_CODE` and a dummy key: health OK, a new URL without the code refused, `169.254.169.254` refused with the code, and with `data/cache/images` deleted inside the container all four demo cases ran to their recorded verdicts (L14 66 events, L06 48, L08 131, L21 8) and the demo photos served. About 256 MiB in use after the runs.
- **Not verified:** an actual Render deploy, a live Gemini call from the hosted server (new pages' photos will likely not display there: the OCR masking package is dev-only and not in the image), and the access-code field on screen at 1280×720 (no browser pass yet). Do these before the event.
- Files: `praman/guard.py`, `praman/api.py`, `praman/config.py`, `praman/tools/fetch.py`, `tests/test_guard.py`, `frontend/src/{lib/api.ts,lib/scan.ts,components/AccessCode.tsx,routes/Intake.tsx,routes/Scan.tsx,styles/app.css}`, `Dockerfile`, `.dockerignore`, `render.yaml`, `docs/DEPLOY.md`, `docs/DECISIONS.md`, `docs/STATUS.md`. Branch: `claude/deploy`. Not pushed.

### 23 Oct 2026 · claude · Groq as the main live model
- `praman/llm.py`: Groq provider over plain HTTP (OpenAI-compatible chat completions; `httpx`, no new dependency), selected by a `groq:` model prefix. New settings `GROQ_API_KEY`, `PRAMAN_LIVE_MODEL`, `PRAMAN_LIVE_VISION_MODEL` (`praman/config.py`). A live call tries the live model, then `PRAMAN_MODEL`, then `PRAMAN_FALLBACK_MODEL`; a Groq model without a key or with more than 3 photos is skipped. The cache key is unchanged (still `PRAMAN_MODEL`), so the eight recorded demo runs replay as before. With `PRAMAN_LIVE_MODEL` empty the behaviour is exactly the old one (tested).
- Request: temperature 0, `json_schema` (non-strict) with a JSON-mode retry (schema in the prompt) if the model rejects it, `reasoning_effort` low/medium for `openai/gpt-oss-*` (dropped if rejected). A 429 "per day" marks the model exhausted and moves on.
- `praman/guard.py`: a Groq key alone now enables live checks. `render.yaml` and `docs/DEPLOY.md` list the new variables.
- Verified: ruff clean; full offline `uv run pytest` passes, including 10 new tests in `tests/test_groq.py` (mocked HTTP, no keys). **Not verified: any real Groq call** (no key available to me; I don't read `.env`). Model ids come from Groq's docs page read today; check the first live run on Render. Photo reading still uses Gemini, so Gemini's 503s can still hit those calls.
- Files: `praman/llm.py`, `praman/config.py`, `praman/guard.py`, `tests/test_groq.py`, `tests/test_guard.py`, `render.yaml`, `docs/DEPLOY.md`, `docs/DECISIONS.md`, `docs/STATUS.md`. Branch: `claude/deploy`. Not pushed.

### 23 Oct 2026 · claude · hosted run findings and a masking fix
- First hosted live runs: Groq answered nothing. Render logs (with failure reasons, `3d0bf47`) show `Groq 403: The model openai/gpt-oss-120b is blocked at the project level`: a Groq console setting, not the key or the code. Gemini's primary model (`gemini-3.8-flash`) is out of its daily free quota, so every call ran on `gemini-3.5-flash-lite` (about 51 s of model time per check). Fix is on the Groq side (enable the model for the project) or `PRAMAN_LIVE_MODEL` set to a model the project allows.
- **Masking bug found in a hosted report:** the title of a new store's product kept the short brand ("Plum Color Affair…" for vendor "Plum Goodness" at plumgoodness.com), because only the vendor and the domain stem were registered. `anonymise.listing_brand_names` now also registers a vendor word or the title's first word that begins the store's domain name. Material words (bamboo, cotton, jute, wood, paper, steel, glass, coconut, neem, herbal, vegan) joined `GENERIC_NAMES` so "Bamboo Soap Dish" stays readable. Seed stores and the recordings are unchanged (full offline suite passes). Photos of already-registered stores need a fresh registration to pick it up.
- Known: the report header says "Model answers: replay" on the hosted server even for a live call, because it shows the server setting.

### 23 Oct 2026 · claude · Groq verified on the hosted server; consistency guard
- Hosted run of a 3-photo page (`Uac502445`): text calls answered by `groq:openai/gpt-oss-120b` in 0.4–1.3 s, photo read by `groq:qwen/qwen3.8-27b` in 10.7 s, about 39 s in all. Remaining slowness is Groq's free-tier limit (8,000 tokens a minute on `gpt-oss-120b`): four 429s, the consistency check waited 17 s. The Developer tier (higher limits) is the fix; price not verified.
- `praman/tools/consistency.py`: a model-found conflict whose explanation leans on general knowledge ("typically", "usually", "generally", "commonly", "often", "normally", "tends to", "in general") is dropped: evidence or nothing. Prompted by a hosted report that marked "biodegradable paper substances" Contradicted because the photo prints "Glassine paper", which "is typically coated and not biodegradable" (not in the listing). The claim now falls back to its proof-based verdict. Code only: no prompt changed, and the replayed demo runs are identical (full suite passes, 3 new assertions in `tests/test_tools_consistency.py`). The eight recorded demo runs contain no such explanations.

### 23 Oct 2026 · claude · evidence judging follows the Groq reasoning setting
- A hosted run of a 13-photo page marked "Recyclable Outer Packaging" Partly backed on evidence whose own note said it concerned the product's material, not the packaging. Cause: `judge_evidence` ran with Groq reasoning forced to `low` and the model answered "partly" for unrelated facts (the code turns any "partly" into Partly backed). `praman/llm.py`: only `plan_next` and `write_rewrite` stay at `low` on Groq (`GROQ_LOW_REASONING`); the rest, judging included, use `PRAMAN_GROQ_REASONING` (default `medium`). `render.yaml` now says `medium`; **the existing Render service still has `low` and needs the variable changed by hand.** No prompt changed; the demo replays are unaffected (full suite passes). Not re-verified on the hosted page yet. Trade-off: more thinking tokens per judged claim, so more chance of Groq's 8,000-tokens-a-minute limit on the free tier.

### 23 Oct 2026 · claude · faster live checks on Groq
- Hosted run of a 13-photo page took about 93 s: a 5-photo read went to Gemini (Groq takes 3 photos a request) and took 56 s; short Groq calls waited 16 s on the free tier's 8,000-tokens-a-minute limit.
- `praman/llm.py`: (1) a photo call with more than 3 photos is split into groups of 3, sent to Groq in parallel and joined, when its answer is all lists (`read_photos`, brand marks); each group's prompt says it shows only some photos, and token counts are summed; (2) a Groq 429 "try again in Ns" is waited out for N s (max 12) instead of the exponential backoff; (3) `PRAMAN_LIVE_SHORT_MODEL` routes `plan_next` and `write_rewrite` to a second Groq model (token limits are per model), then the main model, then Gemini. All three are inactive unless the settings are present, and the cache key is unchanged.
- Verified offline (5 new tests, full suite passes, demo replays unchanged). **Not verified on the hosted server:** whether `qwen/qwen3.8-27b` reads packs as well as Gemini, and the timing. Render needs `PRAMAN_LIVE_SHORT_MODEL` and `PRAMAN_GROQ_REASONING=medium` set by hand if the sync doesn't add them.

### 23 Oct 2026 · claude · photo brand leak on new pages; stuck model calls
- **Leak (non-negotiable 6):** on a hosted live check of a non-seed page the exhibit photo showed the real brand on the pack. Photos of new pages were blurred only from what the agent's photo read found; until then (and for the 5 minutes the browser cached it) the raw photo was served. `GET /api/photos` now serves a small heavily blurred copy, `Cache-Control: no-store`, for any photo whose print the run hasn't read and that has no mask file (`anonymise.pending_photo_bytes`, `has_mask_files`); the exhibit (`Exhibit.tsx`) asks again with `?read=1` once the photo is read (`Img.tsx` fallback regex allows the query). Demo cases are unchanged (mask files exist). **Known limit:** a page only run in text-only mode never reads its photos, so its photos stay blurred.
- **Stuck calls:** a hosted run sat 2+ minutes on `read_photos`. A model now gets at most 30 s (Groq, 20 s per request via `PRAMAN_GROQ_TIMEOUT_S`) or 75 s (Gemini) for one call, retries included, then the next model answers (`GROQ_CALL_BUDGET_S`, `GEMINI_CALL_BUDGET_S` in `praman/llm.py`). Before, 4 attempts of 45 s could run to 3 minutes. Quick failures (rate limits with a short hint) are still retried. The cause of that specific hang is unknown; the log lines for it were not seen.
- Verified offline: ruff clean, full suite passes (new tests: stuck call, quick retry, pending photo), frontend typecheck, 59 tests, build. Not verified on the hosted server.

### 23 Oct 2026 · claude · blank evidence photos (side effect of the unread-photo blur)
- Evidence crops of a hosted case showed smooth grey gradients: they were crops of the 320 px blurred placeholder. `GET /api/photos` decided "has this photo been read" from the newest agent run of the listing only, so starting a second run of the same page (no photo_read yet) put every photo of the older case back to the placeholder. It now asks `store.photo_reads(listing_id)`: the photo_read events of every agent run of the listing. Test: `test_a_newer_run_that_has_not_read_the_photos_...` in `tests/test_api.py`. Full suite and ruff pass; not yet looked at on the hosted server. Still true: a page only run in text-only mode never reads its photos, so they stay blurred.

