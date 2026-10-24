# CLAUDE.md: working in the Praman repo

Praman is an AI agent that checks green claims on product pages for proof under India's rules (CCPA greenwashing guidelines, Oct 2024; Plastic Waste Management Amendment Rules, Mar 2024). Built for AgentOps'26 (Sat 24 Oct 2026).

Read these before changing anything:
- `docs/PRD.md`: what we build and why (requirements FR-xx, verdicts, demo cases).
- `docs/TRD.md`: how it's built (models, tools, loop, verdict table, prompts, storage, API and event contract, tests, build plan).
- `docs/DESIGN.md`: how the web app looks and behaves (frontend work only), with `docs/design/case_mockup.html` as the reference look.
- `docs/STATUS.md` (core track) and `docs/FRONTEND_STATUS.md` (frontend track): what's done, what's next. **Update yours after every milestone.**

## Commands
```
uv sync                                   # install
uv run scripts/fetch_cache.py             # download seed listings + photos into data/cache
uv run scripts/build_cpcb_csv.py          # CPCB PDF -> data/cpcb_certified.csv
uv run scripts/photo_probe.py             # vision go/no-go on two box photos
uv run scripts/run_one.py L14 --mode agent    # run one listing, print the trace
uv run uvicorn praman.api:app --host 127.0.0.1 --port 8000   # API; also serves frontend/dist at /
uv run scripts/export_recordings.py       # real demo runs -> data/recordings/ (F5 copies them to frontend/public/demo/)
bash scripts/demo.sh                      # build the frontend, start the API, open the app
uv run pytest                             # tests (always offline)
uv run ruff check . && uv run ruff format .
uv run eval/run_eval.py                   # agent vs baseline -> eval/results.md

cd frontend && npm install                # frontend deps (Node 22)
cd frontend && npm run dev                # Vite on :5173, proxies /api to :8000
cd frontend && npm run typecheck && npm test && npm run build
cd frontend && npm run demo               # bundled recordings only, no Python needed
```
The desktop app's preview servers are defined in `.claude/launch.json` (api on 8000, web on 5173).

## Non-negotiables
1. **Read-only.** No tool may post, submit, buy, email or write to any external system.
2. **Fixed tool list.** The agent can only call tools registered in `praman/agent.py`; validate every call with Pydantic.
3. **Evidence or nothing.** Every verdict cites evidence IDs and rule IDs, or it becomes Needs review (TRD §9). Backed needs ≥1 evidence with covers_claim = yes from a required source.
4. **Code decides clear-cut rules.** Registry, label and certificate-scope checks are decided in `praman/verdict.py`, not by the model.
5. **Careful language.** Never write "illegal", "violation", "greenwashing", "fraud" or "lying" about a brand in any user-facing text, prompt output or report.
6. **Real brand names are allowed in public** (team decision, 24 Oct 2026). The repo is public and live checks show real names; rule 5 matters all the more. Anonymise mode stays as a switch (`PRAMAN_ANONYMISE`) for sharing reports outside the team.
7. **Secrets.** Never read, print or commit `.env`. Use `.env.example` for new keys.
8. **Tests never touch the network.** Tests run with `PRAMAN_LLM_MODE=offline` using the replay cache and fixtures.
9. **Model calls:** temperature 0, JSON schema output, retries with backoff, everything through `praman/llm.py` so the record/replay cache sees it.
10. **Fetching politely:** respect robots.txt, ≤ 1 request/second per domain, same-domain links only.
11. **Two sessions may share this folder.** Stage only your own paths; never `git add -A`, `git add .` or `git commit -a`. Core track: `praman/ scripts/ tests/ eval/ data/rules.json data/listings_seed.csv data/cpcb_certified.csv data/cache/listings/ data/recordings/ docs/STATUS.md docs/DECISIONS.md pyproject.toml uv.lock README.md .github/`. Frontend track: `frontend/ docs/FRONTEND_STATUS.md`. Either track may stage `docs/TRD.md` when it changes the event contract. Integration (F5) stages both sets. If a commit fails because `.git/index.lock` exists, wait 10 seconds and retry; never delete the lock.
12. **The event contract is TRD §15.3.** Change it only by editing the TRD table first, then both `praman/events.py` and `frontend/src/lib/events.ts`, and say so in both status files.

## Conventions
- Python 3.12, type hints everywhere, Pydantic v2 models in `praman/models.py`.
- One prompt per file in `praman/prompts/`, with its output schema named at the top.
- Small functions, no agent frameworks (no LangChain/LangGraph/CrewAI), no vector DB.
- Every step of a run is written to SQLite `steps` with a one-line human-readable summary (the trace panel shows it).
- Commit after each milestone with a message like `M2: agent loop, read_photos, verdict table` (core) or `F2: scan, ledger, threads, stamps` (frontend). Don't push; Savya pushes.
- Frontend: follow `docs/DESIGN.md`. Colours and fonts only through the tokens; no network calls except our own `/api`; no CDN fonts, scripts or icons; TypeScript strict, no `any` in `lib/`.
- Decisions you make without asking go in `docs/DECISIONS.md` (date, decision, why).

## Definition of done for any feature
- Code + tests (offline) + `ruff` clean.
- Works in replay mode for L14, L06, L08 and L21.
- Frontend changes: `npm run typecheck`, `npm test` and `npm run build` pass, and you've looked at the screen at 1280×720 (Browser pane or a Playwright screenshot).
- Your status file (`docs/STATUS.md` or `docs/FRONTEND_STATUS.md`) updated with what changed and what's next.
