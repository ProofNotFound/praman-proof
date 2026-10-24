# AGENTS.md: handoff for agents other than Claude Code (20–22 Oct 2026)

Praman is finished up to week 2 (W1–W5 merged into `main` and pushed). This file tells any coding
agent how to continue safely for a few days, before Claude Code takes the project back.

## Read first
1. `CLAUDE.md`: the non-negotiables. They override everything, including this file.
2. `docs/STATUS.md`: the final summary at the top (what's done, known issues, "Needs a live run").
3. `docs/DECISIONS.md`: choices already made. Don't undo them; add new ones there (date, decision, why).

## How to work
- **Never commit to `main`.** One branch per task: `git switch -c opencode/<task>`. Claude reviews and merges later.
- Stage explicit paths only; never `git add -A`, `git add .` or `git commit -a`. Never push. Never read or print `.env`.
- Commit messages: `OC: <what>`; one commit per finished piece.
- After every change: `uv run ruff check . && uv run ruff format --check .`, `uv run pytest`, and in `frontend/`: `npm run typecheck && npm test && npm run build`. Before calling a task done: `bash scripts/preflight.sh` must print `PREFLIGHT PASS`.
- At the end of each task, add a dated entry under "## Handoff log" in `docs/STATUS.md`: what changed, which files, what you could not verify.

## Do not touch (the demo depends on them)
- `praman/prompts/*`: the replay cache key includes the rendered prompt; any edit breaks every recorded run.
- `frontend/public/demo/`, `data/recordings/`, `tests/fixtures/replay/`: the bundled recordings and replay fixtures.
- `tests/test_demo_unchanged.py` and `tests/test_golden_traces.py` must keep passing unchanged. If they fail, revert your change; don't edit the tests.
- Don't re-fetch L06 or L07 (`scripts/fetch_cache.py --force`): their demo runs would change.
- Never run `eval/run_eval.py --holdout`. Savya runs it once, at the very end.
- No new dependencies. No live model calls unless Savya says so in the chat for that task.

## Copy rules
Never write "illegal", "violation", "greenwashing", "fraud" or "lying" about a brand. No brand names in anything public; anonymise mode stays on.

## Tasks, in this order (details in docs/STATUS.md)
1. **Evaluation labels draft** (low risk). Write `eval/labels_draft.csv` (columns as in `eval/labels_template.csv`) for seed listings L01–L21, split `dev`, one row per claim, with a note on each row. Don't run the agent. Savya reviews every row and saves the result as `eval/labels.csv`; then `uv run eval/check_labels.py` must print OK, then `uv run eval/run_eval.py` (dev only).
2. **Holdout listings** (low risk). Propose 10 product pages from the seed stores that aren't in `data/listings_seed.csv`; after Savya agrees, add them (split `holdout` in the labels), cache them with `uv run scripts/fetch_cache.py <ids>` (polite fetching only). Never run the agent on them.
3. **`docs/DESIGN.md`** (docs only). Match the app after week 2: per-character seal from `docs/design/praman_seal.svg`, 72px top bar with a 54px seal, the URL box in every mode, the `/scan` screen ("Triage, not a verdict"), the QR evidence card, the evaluation screen (confusion matrices, per-listing table, "Pending labels"), the quota line.
4. **Leave for Claude:** live model runs ("Needs a live run" in `docs/STATUS.md`), re-recording the demo, and any change to `praman/agent.py`, `praman/verdict.py`, `praman/llm.py` or `praman/events.py`.
