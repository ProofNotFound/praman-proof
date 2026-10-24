# Week 1 build prompt: core track (Sun 18 – Thu 22 Oct)

**Claude Code mode: Accept edits** (the desktop app's name; the VS Code extension calls the same mode "Edit automatically"). The repo's `.claude/settings.json` sets this mode and pre-approves the `uv`, `npm`, `git` (no push) and file commands the build needs, so the run shouldn't stop for permissions. If it still stops to ask, switch the session to **Auto**; the deny rules (`.env`, `git push`) still apply there.

This is session 1 of 2. Session 2 runs `docs/FRONTEND_PROMPT.md` at the same time, in the same folder. The two prompts share files only through the event contract (TRD §15.3) and they never stage each other's paths.

## Before you paste (Savya, about 15 minutes)
1. Install `git`, `uv` and **Node 22 LTS** (`brew install node@22`, or the installer from nodejs.org). Check: `git --version && uv --version && node --version`.
2. Create a **private** GitHub repo `praman`, clone it, and copy every file from this kickoff pack into it, hidden ones included (`cp -R praman_kickoff/. praman/`), so `.claude/` comes along.
3. Copy `.env.example` to `.env`; fill in `GEMINI_API_KEY` and `PRAMAN_MODEL` (the current Gemini Flash model name from AI Studio) and, if you have one, `PRAMAN_FALLBACK_MODEL`.
4. `git add -A && git commit -m "M0: kickoff docs and seed data" && git push -u origin main`.
5. In the Claude desktop app: **+ New session** → Environment **Local** → Project folder `praman` → mode **Accept edits** → paste everything in the box below. Leave the worktree option off.
6. Start session 2 the same way with `docs/FRONTEND_PROMPT.md`.
7. Keep the Mac plugged in and awake (`caffeinate -dims` in the app's terminal). Push after each milestone yourself: `git push && git push --tags`.

If a session stops (usage limit or a long stretch), send it: *Continue from the next steps in your status file. Same rules as before; don't ask me anything.*

---

## The prompt

```
You are building the core of Praman, a hackathon project, in this repository: the agent, its tools, the evaluation and the web API. Another Claude Code session is building the React frontend in frontend/ at the same time. Work fully autonomously: do not ask me questions or wait for confirmation. When something is ambiguous, choose the option most consistent with docs/PRD.md and docs/TRD.md, record it in docs/DECISIONS.md (date, decision, why) and keep going.

First read CLAUDE.md, docs/PRD.md, docs/TRD.md, docs/STATUS.md, data/rules.json, data/listings_seed.csv and eval/labels_template.csv. CLAUDE.md's non-negotiables override anything else.

Sharing the folder with the frontend session:
- Never edit anything under frontend/ or docs/FRONTEND_STATUS.md, except during F5 below.
- Stage only your own paths (CLAUDE.md rule 11). Never git add -A, git add . or git commit -a. If .git/index.lock exists, wait 10 seconds and retry.
- The event contract is TRD §15.3. Don't change it unless you must; if you do, edit the TRD table first and add a line under "Notes for the core track" in docs/FRONTEND_STATUS.md saying what changed (that one line is the only edit you may make there before F5).

Build these milestones in order. After each one: run ruff and pytest (offline), fix failures, update docs/STATUS.md (what's done, what's next, any blockers), and commit with the message given. Never push. Never read or print .env.

M0 setup and data prep (commit "M0: project skeleton and data prep")
- pyproject.toml managed by uv (Python 3.12) with: google-genai, pydantic, pydantic-settings, httpx, selectolax, pillow, pdfplumber, pandas, rapidfuzz, pytest, ruff. Add fastapi, uvicorn[standard] and sse-starlette at M3, and opencv-python-headless only when you reach the QR stretch.
- The package layout from TRD §3, config from TRD §13, models from TRD §5, SQLite schema from TRD §12 (including the events table).
- scripts/fetch_cache.py: for every row of data/listings_seed.csv fetch <url>.json (Shopify), save data/cache/listings/<id>.json, download all photos to data/cache/images/<id>/<n>.jpg; robots.txt check; 1 request/second per domain; skip and log failures. Run it.
- scripts/build_cpcb_csv.py: download the CPCB PDF (URL in data/rules.json sources.CPCB_LIST), extract Table 1 (certified) and Table 2 (not certified) with pdfplumber into data/cpcb_certified.csv (columns: s_no, name, type, office_address, plant_address, validity, certificate, conditions, state, table) plus a normalised name column; record the list date 2023-10-26. Run it and spot-check that "Greendotbiopak" (S.No. 32) and "Sunshield Biotech Llp" (S.No. 2) exist.
- scripts/photo_probe.py: send L14 photo 7 and L06 photo 3 to the model with the read_photos prompt (exact strings plus box_2d per item, TRD §7.1); check the output contains "GREEN DOT BIOPAK", "SUNSHIELD" and "PE Virgin Grade" (case-insensitive) and whether boxes came back; print PASS/FAIL per check. Run it once in live mode and write the result at the top of docs/STATUS.md.

M1 core pipeline (commit "M1: core pipeline, L14 end to end")
- praman/llm.py exactly as TRD §11: temperature 0, JSON schema output from Pydantic models, retries with backoff, fallback model for text-only calls, record/replay cache with modes live, replay, offline; image identifiers (not bytes) in the cache key; token and cost tracking.
- Tools: fetch_listing, extract_claims, match_rule, search_text, cpcb_lookup, rule_lookup per TRD §7 (cpcb_lookup thresholds and normalisation per §7.2). Prompts in praman/prompts/ per TRD §10.
- praman/rules.py loading data/rules.json with matching per TRD §6.3. Unit tests: every rule gets at least one positive and one negative example.
- scripts/run_one.py <listing_id or URL> --mode agent|baseline prints claims, matched rules and each step. Done when L14 prints claims, rules, a text search with no proof, and cpcb_lookup matching both makers when given their names.

M2 the agent (commit "M2: agent loop, photos, verdicts, baseline, events")
- read_photos per TRD §7.1 (once per listing, box backs first, max 5 photos, exact strings, box_2d per item).
- praman/events.py: the event models from TRD §15.3 as a Pydantic discriminated union, and an emit callback type. The agent takes emit and calls it for every event in the order TRD §15.3 gives; emit defaults to a no-op so the CLI and tests work without the API. Every emitted event is also written to the events table.
- praman/agent.py: the loop in TRD §8 with plan_next, default_next fallback, budgets from §8.1, and every plan/act/observe/decide step written to SQLite steps with a one-line summary.
- praman/verdict.py: the decision table and both guards in TRD §9, in code.
- check_consistency and write_rewrite prompts and tools.
- praman/baseline.py per TRD §8.4 (it emits events too).
- Done when, in live or replay mode, L14 gives compostable = Backed, "0% plastic" = Contradicted, industrial-composting label = Needs review; L06 gives Contradicted; L08 gives plastic-free = Contradicted and zero waste = Contradicted; L21 gives Not a claim with no tool calls. If a case disagrees, fix prompts or the verdict table, not the expected results, and note what changed in docs/DECISIONS.md.
- Export the llm_cache rows used by these four runs to tests/fixtures/replay/*.json and make tests load them, so golden traces run offline in CI.

M3 the web API (commit "M3: API, SSE events, recordings, report, anonymise, offline")
- praman/api.py per TRD §15.1–15.2: every endpoint in the table, SSE with Last-Event-ID resume and a 15 s heartbeat, runs in a worker thread feeding a per-run asyncio queue, 127.0.0.1 only, CORS for the Vite dev origin only, serves frontend/dist at / with an SPA fallback when that folder exists.
- praman/anonymise.py: mask store domains and every brand and alias in data/listings_seed.csv as "Brand A", "Brand B"… consistently across events, API responses, reports and recordings; on by default. Photo masking per TRD §15.5.
- fetch_linked_page (same domain only) used for "View our Certificates" style links.
- praman/report.py: Markdown and HTML export with the PRD §8 disclaimer, the CPCB list date and the approver's name; the API returns 409 until a run is approved.
- scripts/export_recordings.py per TRD §15.4: run L14, L06, L08 and L21 in agent and baseline mode (replay), and write the recordings plus index.json and masked photos. Write them to data/recordings/ for now (a path you own); F5 copies them into frontend/public/demo/.
- scripts/demo.sh: if frontend/ exists, build it (npm ci && npm run build in frontend/), then start the API on 127.0.0.1:8000 with PRAMAN_LLM_MODE=replay and open http://127.0.0.1:8000.
- Tests: TestClient streams L14 events in offline mode in a valid order ending in run_finished; report 409 before approval and 200 after; every event in data/recordings/*.json validates against praman/events.py; and the same check for frontend/public/demo/*.json when that folder exists, skipping files marked "synthetic": true.
- Verify offline mode: with PRAMAN_LLM_MODE=offline the four demo listings run fully from cache and replay through the API.

M4 measure and freeze (commit "M4: golden tests, evaluation, README" then tag v1.0)
- tests/test_golden_traces.py for L14, L06, L08, L21: assert key verdicts and that L14's tool sequence includes read_photos then cpcb_lookup; offline only.
- eval/run_eval.py per TRD §17. If eval/labels.csv doesn't exist yet, run on eval/labels_template.csv and say so in docs/STATUS.md. Write eval/results.md and make GET /api/eval return it.
- GitHub Actions workflow per TRD §16: a Python job, and a Node 22 frontend job that runs only if frontend/package.json exists.
- README.md: what it does, architecture diagram (from TRD §2), how to run (bash scripts/demo.sh), results table (or "pending labels"), no brand names (use anonymised examples).
- Tag v1.0 with git tag.

F5 integration (do this only when docs/FRONTEND_STATUS.md shows F4 as done and its F5 lock line says "(free)")
- First replace "(free)" in the F5 lock with "F5 in progress (core track)" and commit that one file. If the lock already names the frontend track, skip F5.
- Copy data/recordings/ into frontend/public/demo/ (replacing the synthetic files and index.json).
- Start the API and the Vite dev server (the desktop app's preview servers from .claude/launch.json, or run them in the background), open the app, and play all four cases in both modes through the real API, then with the API stopped (recording fallback). Fix whatever disagrees with TRD §15.3, on whichever side is wrong; keep frontend edits minimal and inside frontend/src/lib/ where possible.
- bash scripts/demo.sh must open a working app at http://127.0.0.1:8000.
- Run npm run typecheck, npm test and npm run build in frontend/, and the full pytest suite. Update both status files (mark F5 done in docs/FRONTEND_STATUS.md) and commit both sets of paths with "F5: frontend wired to the real API and recordings".
- If F4 isn't done when you finish M4, don't wait: write "Core ready for F5" under "Notes for the core track" in docs/FRONTEND_STATUS.md, commit it, and finish.

Stretch, only if M4 is committed and time remains (separate commits, each with tests): QR decoding with OpenCV in photos → follow the link → search for proof; then a store scan that ranks a store's products by risk.

Limits for the whole run:
- Live model calls: at most 400 in total. Prefer replay; record each demo listing once in live mode, then work from replay.
- Don't fetch any site except the seed stores, the CPCB PDF URL, the model API and package registries.
- Never use the words illegal, violation, greenwashing, fraud or lying about a brand in prompts' outputs, UI text, events or reports.
- If the API key is missing or calls keep failing, build everything against hand-written fixture responses clearly marked as synthetic in tests/fixtures, finish the remaining milestones, and list exactly what needs a live run in docs/STATUS.md.

When everything is done, write a final summary at the top of docs/STATUS.md: milestones completed, photo probe result, test results, evaluation numbers (or what's pending), known issues, and the exact commands to run the demo offline.
```
