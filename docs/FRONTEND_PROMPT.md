# Week 1 build prompt: frontend track (Sun 18 – Thu 22 Oct)

**Claude Code mode: Accept edits** (the desktop app's name; the VS Code extension calls it "Edit automatically"). `.claude/settings.json` pre-approves the `npm`, `node`, `git` (no push) and file commands this track needs. If it still stops to ask, switch the session to **Auto**.

This is session 2 of 2. Start it right after session 1 (`docs/WEEK1_PROMPT.md`), in the **same folder**: Claude desktop app → **+ New session** → Environment **Local** → Project folder `praman` → mode **Accept edits** → paste the box below. Leave the worktree option off.

It needs no API key and makes no model calls. It builds the whole web app against synthetic recordings first, so it doesn't wait for the core. Integration with the real API (F5) is done by whichever session finishes second.

If it stops (usage limit or a long stretch), send it: *Continue from the next steps in docs/FRONTEND_STATUS.md. Same rules as before; don't ask me anything.*

Two sessions at once use your plan's limits about twice as fast. If you hit limits often, run this prompt after the core session reaches M2 instead.

---

## The prompt

```
You are building the web frontend of Praman, a hackathon project, in frontend/ of this repository. Another Claude Code session is building the Python core and API at the same time. Work fully autonomously: do not ask me questions or wait for confirmation. When something is ambiguous, choose the option most consistent with docs/DESIGN.md and docs/TRD.md §15, record it under a "Decisions" heading in docs/FRONTEND_STATUS.md (date, decision, why) and keep going.

First read CLAUDE.md, docs/DESIGN.md (the spec you build to), docs/design/case_mockup.html (open it in the browser preview and study it: it is the reference look for the case screen), docs/TRD.md §15 (the API, the event contract and the recording format), docs/PRD.md §7, §8 and §12 (verdicts, copy rules, the four demo cases), data/listings_seed.csv and docs/FRONTEND_STATUS.md. CLAUDE.md's non-negotiables override anything else.

Sharing the folder with the core session:
- Only create or edit files under frontend/ and docs/FRONTEND_STATUS.md. Read anything; never edit praman/, scripts/, tests/, data/, eval/ or the other docs (except F5 below).
- Stage only your own paths (CLAUDE.md rule 11): git add frontend docs/FRONTEND_STATUS.md. Never git add -A, git add . or git commit -a. If .git/index.lock exists, wait 10 seconds and retry.
- The event contract is TRD §15.3. If you find it can't express something DESIGN.md needs, add the smallest optional field you need to the TRD table, mirror it in frontend/src/lib/events.ts, and note it under "Notes for the core track" in docs/FRONTEND_STATUS.md. Never rename or remove a field.
- Brand names: the recordings and UI must never contain real brand or store names from data/listings_seed.csv. Use "Brand A", "Brand B"… and brand-a.example style domains.

How to look at your work: use the desktop app's preview servers (.claude/launch.json defines "web" on 5173) and its browser to check every screen you build. If that isn't available, run npx playwright install chromium once and take screenshots with a small node script. Check at 1280×720 and 1920×1080. Fix what looks wrong before moving on; DESIGN.md §9 lists what "wrong" means.

Build these milestones in order. After each one: run npm run typecheck, npm test and npm run build in frontend/, fix failures, look at the screens, update docs/FRONTEND_STATUS.md (what's done, what's next, any blockers) and commit with the message given. Never push.

F0 scaffold, tokens, recordings (commit "F0: frontend scaffold, tokens, synthetic recordings")
- Write the Vite + React + TypeScript scaffold by hand in frontend/ (index.html, package.json, vite.config.ts, tsconfig.json, src/main.tsx). Don't use interactive scaffolding commands.
- Install the current stable versions, pinned exactly (npm install --save-exact): react, react-dom, react-router, motion, lucide-react, @fontsource-variable/fraunces, @fontsource/ibm-plex-sans, @fontsource/ibm-plex-mono, @fontsource/noto-serif-devanagari; dev: vite, @vitejs/plugin-react, typescript, tailwindcss, @tailwindcss/vite, vitest, @types/react, @types/react-dom, @types/node. Commit package-lock.json.
- npm scripts per TRD §15.6: dev (port 5173, /api proxied to http://127.0.0.1:8000), build, typecheck, test, demo (vite preview --port 4173).
- src/styles/tokens.css with every token in DESIGN §2 exposed to Tailwind v4 through @theme; base typography; the paper grain layer; fonts imported from the @fontsource packages (no Google Fonts).
- src/lib/events.ts: TypeScript types for every event in TRD §15.3 and the recording format in §15.4, plus a runtime validator (hand-written type guards; no extra library).
- Synthetic recordings in frontend/public/demo/ following TRD §15.4 exactly, with "synthetic": true: L14, L06, L08 and L21 in agent mode, and L14, L06 and L08 in baseline mode. Base each one on PRD §12 (expected path and verdicts) and the evidence and notes columns of data/listings_seed.csv, with realistic t_ms gaps (a full agent run lasts 20–40 s). Include photo_read events with box_2d boxes and registry_lookup events, so every signature moment has data. Baseline runs use text only, so they never see claims printed only on photos (for L14 the text-only side never sees "0% plastic"). Photos: draw simple SVG placeholders in frontend/public/demo/photos/<id>/<n>.svg (box backs with the printed lines from the evidence column, in the style of the mockup). index.json lists every recording.
- A test that loads every recording and validates every event with the runtime validator.

F1 screens and data flow (commit "F1: intake and case screens, reducer, pacer, API client")
- src/lib/reducer.ts: one reducer that turns events into case state (listing, claims, evidence, verdicts, steps, registry lookups, photo reads, run summary). Pure, fully unit-tested, including events arriving for unknown claims.
- src/lib/pacer.ts: the release queue from DESIGN §7 (minimum gaps per event type at 1×, speeds 0.5×/1×/2×/instant, pause, step one event, restart). Pure logic with an injectable clock; unit-tested with fake timers.
- src/lib/api.ts: GET /api/health on load; if it fails or times out (1.5 s), switch to recording mode for the whole session. Live mode: REST calls from TRD §15.2 and EventSource for /api/runs/{id}/events with reconnect. Recording mode: load index.json and play recordings through the same pacer and reducer. Show a RECORDING chip in recording mode and a SYNTHETIC chip when the recording says so.
- Routes with react-router: / (Intake), /case/:caseId (Case), /case/:caseId/report (Report), /eval (Evaluation). In recording mode caseId is "<listing_id>.<mode>"; in live mode it is the run id.
- Intake per DESIGN §4.1 and Case per DESIGN §4.2 with static rendering of whatever state the reducer holds: TopBar with the Seal, Exhibit with claim highlights in place, Board with claim and evidence cards, Trace. Match the mockup's look.

F2 the signature moments (commit "F2: scan, ledger, threads, stamps, trace, director bar")
- Build DESIGN §5.1–5.4 exactly as specified (durations, easing, colours), driven by events from the pacer: the Scan on photo_read, the Ledger on registry_lookup, the Threads on evidence, the Stamp on verdict. The Exhibit highlight fills at the same moment as its stamp.
- The Trace per DESIGN §4.2: rows slide in, the active row pulses, PLAN rows show the agent's why sentence, auto-scroll with "Jump to latest".
- The Seal rotates while a run is working and stops when it finishes.
- The Director bar and every keyboard shortcut in DESIGN §7, and Present mode (P).
- prefers-reduced-motion and the "instant" speed must both skip all motion cleanly.

F3 compare, report, evaluation (commit "F3: compare split, dossier report, evaluation")
- Compare split per DESIGN §5.5 (live: GET /api/compare/{listing_id}; recording mode: the agent and baseline recordings of the same listing, played to their end).
- Report per DESIGN §4.3: the A4 dossier with print CSS, Approve (name) gating Export. Live mode: POST approve, then download Markdown from the API. Recording mode: approval stays in the page (say "Not saved: recording mode") and Markdown is generated in the browser from the reducer state. Include the exact disclaimer from PRD §8.
- Evaluation per DESIGN §4.4 with a hand-built SVG chart (live: GET /api/eval; recording mode: frontend/public/demo/eval.json, which you create with {"status": "pending"}). When pending, say "Pending labels" and show no numbers.

F4 polish and checks (commit "F4: projector polish, accessibility, offline")
- Go through DESIGN §10 point by point. Take screenshots of Intake, Case mid-run, Case finished, Compare, Report and Evaluation at 1280×720 and 1920×1080, in normal and present mode; save them in frontend/screenshots/ and fix everything that's clipped, too small, misaligned or generic-looking.
- Keyboard-only run of a whole case in present mode; visible focus rings in the accent colour; aria-live on the trace; every stamp also readable as text.
- npm run demo serves the built app and plays all four cases with no backend running.
- Log every network request while playing a case (browser preview network panel, or Playwright's request event) and remove any that isn't to our own /api or a relative path.
- Copy rules: search all UI strings for illegal, violation, greenwashing, fraud and lying; there must be none.

F5 integration (do this only when docs/STATUS.md shows M3 as done and the F5 lock in docs/FRONTEND_STATUS.md says "(free)")
- First replace "(free)" with "F5 in progress (frontend track)" and commit that one file. If the lock already names the core track, skip F5.
- Copy data/recordings/ into frontend/public/demo/ (replacing the synthetic files and index.json); keep eval.json only if the API has no results.
- Start the API (the "api" preview server in .claude/launch.json, which runs in replay mode by default) and the Vite dev server, and play all four cases in both modes through the real API, then with the API stopped (recording fallback). Fix whatever disagrees with TRD §15.3 on whichever side is wrong; keep edits to praman/ minimal and limited to praman/api.py and praman/events.py, and note them in docs/STATUS.md.
- bash scripts/demo.sh must open a working app at http://127.0.0.1:8000.
- Run npm run typecheck, npm test, npm run build and uv run pytest. Update both status files (mark F5 done in both) and commit both sets of paths with "F5: frontend wired to the real API and recordings".
- If M3 isn't done when you finish F4, don't wait: write "Frontend ready for F5" at the top of docs/FRONTEND_STATUS.md, commit it, and finish.

Rules for the whole run:
- No network requests at runtime except our own /api. No CDN fonts, scripts, icons or analytics.
- No chart or component libraries beyond the ones listed in F0. No Three.js.
- TypeScript strict; no any in src/lib/.
- Never invent results: synthetic recordings are marked synthetic on screen, and evaluation shows "Pending labels" until real results exist.

When everything is done, write a final summary at the top of docs/FRONTEND_STATUS.md: milestones completed, test results, screenshots taken, known issues, and the exact commands to run the demo (with and without the backend).
```
