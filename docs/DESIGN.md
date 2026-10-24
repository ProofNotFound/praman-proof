# Praman: frontend design

The visual and interaction spec for the Praman web app. Read with `docs/TRD.md` §15 (API and event contract) and `docs/design/case_mockup.html` (the reference look for the case screen; open it in a browser and match its feel, not its pixels).

---

## 1. The idea

Praman means *proof*. The app should feel like an **evidence dossier being assembled live**: a product page laid out like an exhibit, claims pinned to a board, proof cut out of pack photos and pulled from a government ledger, and each finding landing as an inked **verdict stamp**.

What makes it ours (and not a dashboard template):
- **Paper and ink, not dark glass.** Warm paper background, near-black ink, one registry green, stamp inks for verdicts. It reads as a document, which is what a compliance check produces. It's also the right call for a projector: dark UIs wash out on college projectors, paper doesn't.
- **Four signature moments** (§5): the Scan, the Ledger, the Threads and the Stamp. Each one shows the judges an agent *doing* something, not a spinner.
- **A compare split** (§5.5): drag a divider across the board to see what a text-only check concludes versus what the agent proved. This is the agentic advantage in one gesture.
- **Director controls** (§7): the presenter can pause, step and pace the run with the keyboard, so the story is told at the speed of speech.

Rule of thumb for every screen: *if it looks like it could be any SaaS dashboard, it's wrong.*

---

## 2. Tokens

Define these as CSS variables in `src/styles/tokens.css` and expose them to Tailwind v4 with `@theme`. Never hard-code colours in components.

### 2.1 Colour

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#F3EFE6` | App background |
| `--paper-sunk` | `#EAE4D7` | Recessed panels (trace, photo well) |
| `--card` | `#FBF9F4` | Cards, dossier page |
| `--ink` | `#1C1B17` | Primary text |
| `--ink-2` | `#4A473F` | Secondary text |
| `--ink-3` | `#7C776B` | Labels, metadata (large or mono only) |
| `--rule` | `#D6CFBF` | Hairlines, card borders |
| `--rule-strong` | `#B9B09C` | Dividers that must survive a projector |
| `--accent` | `#1F5C3F` | Registry green: brand, focus rings, active states |
| `--accent-wash` | `#1F5C3F14` | Hover and selected backgrounds |

Verdict inks (stamp colour; text and borders). Each has a `-wash` at ~10% alpha for highlights in the product text.

| Verdict | Token | Hex |
|---|---|---|
| Backed | `--v-backed` | `#1F7A4D` |
| Partly backed | `--v-partly` | `#A86A12` |
| Not backed | `--v-not` | `#5F5B51` |
| Contradicted | `--v-contra` | `#B3261E` |
| Needs review | `--v-review` | `#2457A6` |
| Not a claim | `--v-none` | `#A39E92` (outline stamp only) |

Contrast: body text on paper must be ≥ 4.5:1 (ink and ink-2 pass). Verdict inks are used at ≥ 18px bold or as borders. Check every pair you add.

### 2.2 Type

All fonts self-hosted through `@fontsource` packages. **No Google Fonts or CDN at runtime**: the demo must work with Wi-Fi off.

| Role | Family | Notes |
|---|---|---|
| Display | Fraunces (variable) | Headlines, listing title, dossier headings. Use the `opsz` axis; weight 500–600. Never below 22px |
| UI and body | IBM Plex Sans | 400/500/600 |
| Data | IBM Plex Mono | Trace, codes, rule IDs, labels, numbers; 500 for labels |
| Wordmark | Noto Serif Devanagari | Only for "प्रमाण" in the logo and on the dossier |

Scale (px): 13 mono caption · 15 trace · 16 body · 18 claim meta · 20 claim quote · 26 listing title · 34 section · 64 hero. Labels are uppercase Plex Mono, 12–13px, letter-spacing 0.08em, `--ink-3`. Nothing under 13px anywhere; on the projector, nothing under 15px that carries meaning.

### 2.3 Shape, line and texture

- Radius 4px for cards and inputs, 2px for chips, 0 for the dossier page. No pill buttons except the verdict chips in tables.
- Borders 1px `--rule`; key dividers 1.5px `--rule-strong`.
- Shadows: none, except the dossier page (`0 1px 0 var(--rule), 0 12px 24px -16px #1C1B1726`) and a "stacked paper" offset on case folders.
- Paper grain: an inline SVG `feTurbulence` noise layer over the whole app at 3–4% opacity, `pointer-events: none`. No image files.
- Icons: `lucide-react`, 1.5px stroke, 16–18px, ink-2. Use sparingly; words first.

### 2.4 Layout

- 8px spacing grid. Gutters 24px.
- Case screen at ≥ 1440 wide: Exhibit 360px · Board (flex) · Trace 380px. At 1280: 300 · flex · 320. Below 1100: stack Exhibit, Board, Trace. Design for **1280×720 and 1920×1080 first** (the projector sizes); everything above the fold at 1280×720 in present mode.
- Top bar 72px (room for the 54px seal); wordmark "Praman" in Fraunces at 26px. Director bar 56px, fixed bottom, only during replay or in present mode.

---

## 3. Brand

- Logo: the **seal**, drawn from `docs/design/praman_seal.svg`. It is a 200-unit SVG: two concentric accent circles (outer r 90, stroke 5.3; inner r 56.9, stroke 3.3), "प्र" centred in Noto Serif Devanagari 700, and the ring "PRAMAN · PROOF CHECK ·" set as **one `<text>` per character at a fixed angle** (not a `textPath`), so spacing never depends on font metrics. The top bar uses it at **54px**, beside the wordmark "Praman" in Fraunces 26px; the report header uses the same 54px seal, and smaller sizes appear on the board and claim cards.
- The seal is also the working indicator: while the agent is working it rotates slowly (one turn per 6s, linear). It stops the moment a run finishes.
- Tagline: "Every green claim, checked for proof."
- Footer line on every screen: "Decision support, not legal advice · CPCB certified list dated 26 Oct 2023".

---

## 4. Screens

### 4.1 Intake (`/`)
- Left: hero in Fraunces 64: "Every green claim needs proof." Below in body: "Praman reads the product page, the pack photos and the government registry, and shows what's proven, what isn't, and what conflicts."
- A URL field ("Paste a product page URL") with a Run button that works in **every backend mode**, not just live: live starts a new check; with a replay/offline server or bundled recordings, a demo listing's URL (real or anonymised) opens its recorded case, while another URL gets one plain line and the case-file buttons. It is disabled only while the server connection is still being checked or a request is in flight. Present mode hides it (§7).
- "Or open a case file": four **case folders** (the demo listings from `/api/listings`, or the bundled recordings if the API is down). Each folder: a manila tab with the case number ("CASE L14"), product name (anonymised), a photo thumbnail, claim count, and the folder lifts 4px on hover. Keys 1–4 open them.
- Right: a quiet live teaser: four claim phrases from the demo cases in a column, each getting stamped in turn (loop every 6s, pauses on hover, off under reduced motion).

### 4.2 Case (`/case/:caseId`), the main screen
Top bar: 54px seal + wordmark · breadcrumb "CASES / L14" · segmented control **Agent | Text-only** · status chips (the model-answer mode when live; **RECORDING** when bundled, plus **SYNTHETIC** when tagged and **ANONYMISED**) · buttons **Compare** and **Report**.

**Exhibit (left).** Label "EXHIBIT · PRODUCT PAGE". Listing title in Fraunces 26. Store line (masked). A photo well showing the current photo large, a thumbnail strip underneath (photos the agent read get a small "READ" tick). Then the description, with every claim quote highlighted in place: a 2px underline plus a wash in the claim's verdict colour (grey dotted underline until decided) and a superscript claim ID (C1, C2…). Hovering a claim highlights its card on the board and vice versa.

**Board (centre).** Claim cards in a column on the left half, evidence cards on the right half, threads between them (§5.3). A claim card shows: claim ID, the quote in Fraunces 20 inside curly quotes, its scope and type in mono, rule chips (`R07 · PWM 4(1)(ha)`), and the stamp area (top right). Below the quote, one line of reason once decided ("Both makers are on CPCB's certified list.") and, for non-Backed claims, a "Suggested wording" disclosure. Queued claims are dimmed to 45% with "Waiting"; the active claim has a 2px accent left border.

Evidence card types:
- **Text quote**: the quote in serif italic, location tag (DESCRIPTION / TITLE / FAQ).
- **Photo crop**: the cropped region of the photo with bracket corners, caption "PHOTO 7 · BOX", and the exact printed string in mono underneath (`CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443`).
- **QR code**: a crop of the code, then `→ domain/path` in mono and one status line: **"Opened · the store's own site"** when Praman followed a same-site link, or **"Not followed · another site"** otherwise. The evidence note explains that the code points elsewhere. The photo Scan lists and brackets QR items even when no claim cites them.
- **Registry row**: ledger styling: "CPCB CERTIFIED LIST · 26 OCT 2023" header, then S.No., name, state, validity in mono columns, and "name match 0.96".
- **Conflict**: two quotes side by side with a vertical rule and "≠", plus the rule that makes them conflict.
- **Certificate scope**: badge name, "covers: company", "claim needs: product".

**Trace (right).** Recessed panel. Header "TRACE" + mode + elapsed timer (mono, ticking). One row per step: step number, phase tag (PLAN / ACT / OBSERVE / DECIDE in mono, each phase with its own small glyph), tool name in mono, and the one-line summary; `ms` right-aligned in ink-3. PLAN rows show the agent's `why` sentence in body text: this is where the judges see it think. The newest row slides in; the active row has a pulsing 2px accent bar. Footer: steps · model calls · ₹ cost · LLM mode. Auto-scrolls unless the user has scrolled up ("Jump to latest" appears).

### 4.3 Report (`/case/:caseId/report`), the dossier
- An A4 sheet centred on paper, print-ready (`@page { size: A4; margin: 16mm }`).
- Header: seal, "प्रमाण · Proof report", case number, listing (anonymised), date and time, LLM mode.
- Summary: counts per verdict as small stamps in a row.
- One section per claim: quote, stamp, reason, evidence list (with photo crops and registry rows), rule citations, suggested wording.
- Approval block: "Reviewed and approved by" name field and an **Approve** button. **Export** (Print / Save as PDF, and Download Markdown from the API) stays disabled until approved; after approval the name and time print in a signature line.
- Disclaimer at the bottom (exact text in PRD §8).

### 4.4 Evaluation (`/eval`)
- Header: the evaluation id, generation time, model-answer mode and labels file in mono. The dev set and the blind holdout each get their own section.
- Three big numbers in Fraunces: verdict agreement (agent), the same for text-only, and false "Backed" (target 0). Each with its n.
- A paired horizontal bar chart per verdict (agent vs text-only), hand-built in SVG, no chart library.
- **Confusion matrices**, one per mode: rows are our labels, columns are the model's verdicts plus a "Not found" column; agreeing cells are green, off-diagonal cells red, zero cells a dot. The caption says "rows are our labels".
- **Per-listing table**: listing, agent and text-only, each with model calls, seconds and ₹ cost, plus an Average row. The listing id links to its case.
- "Proof only the agent found": a list of claims with the evidence type (photo / registry / link).
- Disagreements table: claim, our label, agent, text-only, link to the case.
- A holdout that has not run says **"not run yet"** and explains that it runs once with `uv run eval/run_eval.py --holdout`; it is never shown as an empty result. If labels are pending, the screen says **"Pending labels"** plainly, names `eval/labels.csv` and `eval/check_labels.py`, and shows no numbers. Never show targets as results.

### 4.5 Store scan (`/scan`, `/scan/:scanId`)
The store-level triage screen. It is **plain code, no model calls and no verdicts**: it ranks a store's product pages by the green-claim terms they use and the proof signals they show. A high place means "check this page first", not that a claim is wrong.

- Top bar: crumb "CASES / STORE SCAN", an Evaluation button, and the seal spinning while a scan runs.
- Label **"Store scan · triage, not a verdict"**; headline "Which product pages need checking first?"; a lede that repeats the no-model, no-verdict rule.
- Store address form with a **Scan store** button. Live: `POST /api/scans` and poll every second. Shopify stores read up to 100 products from `/products.json`; other stores read up to 50 product pages from the sitemap, one request a second. Without a backend, the screen shows the bundled recorded scan of an anonymised store, with a clear note.
- Status strip: store, product count, source (`/PRODUCTS.JSON` or `THE SITEMAP`), model calls (always 0), recorded date when applicable, and a label chip. While running: "Read X of Y product pages" and a progress bar. Then four band counts: **Check first / Check soon / Lower / No claim terms**.
- Ranked table: rank; product with up to three reasons; **Needs checking** (score, meter, neutral band word); claim terms as chips with the main rule (registry rules R07/R09 first); proof-signal chips (CPCB code, standard, certificate number, certifier, company mark, certificates link) or "None found"; action.
- Actions: **Check this product** for a live scan (a 409 or unreadable page is one plain line), **Open case L14** for a bundled demo case, otherwise "Needs the server" / "Scan the store to check it". Opening a case gives that one page a full check.
- Footer: "Triage ranks pages to check; only a full check gives verdicts." Band words and colours stay neutral; they never use verdict inks.

---

## 5. Signature moments

All animation uses `motion` (`import { motion } from "motion/react"`). All of it must respect `prefers-reduced-motion` (fall back to simple fades of ≤ 150ms) and the speed setting (§7).

### 5.1 The Scan (when `read_photos` runs)
1. The photo well's photo scales up into an overlay centred on the board (320ms, ease-out).
2. A scan line (1px accent line with a 24px soft green glow above it) sweeps top to bottom over 1.4s, linear.
3. As it passes each text item (from the `photo_read` event's boxes), the item's box outlines faintly, and its text types into a mono column beside the photo (about 40 chars/s).
4. For items that become evidence, four bracket corners fly from the photo edges to the item's box (spring: stiffness 260, damping 24) and lock with a 1-frame flash.
5. The cropped region then lifts out and becomes the photo-crop evidence card on the board (shared `layoutId`).
If the event has no boxes, skip steps 3–4 and glow the whole photo.

### 5.2 The Ledger (when `cpcb_lookup` runs)
A ledger panel slides in over the evidence column: header "CPCB CERTIFIED LIST · 26 OCT 2023 · 172 ROWS". Rows scroll past fast and decelerate (900ms, ease-out) to stop on the matched row, which gets a green wash sweep left to right and the match score. If no match: rows run to the end, "No match for <query>" in ink-2, and the panel closes. The matched row then becomes the registry evidence card.

### 5.3 The Threads
SVG cubic Bézier curves from the right edge of a claim card to the left edge of each evidence card that cites it. They draw in with `stroke-dashoffset` (500ms) when the evidence appears. Colour by `covers_claim`: yes → `--v-backed`, partly → `--v-partly`, no → `--v-not` dashed, contradicts → `--v-contra`. 1.5px, round caps, a 3px dot at each end. Recompute on resize and scroll (ResizeObserver). Hovering a thread or card dims everything not connected to it to 30%.

### 5.4 The Stamp (when a `verdict` event arrives)
A rectangle with a double border, uppercase Plex Mono 600, letter-spacing 0.12em, in the verdict ink, with an ink texture (SVG mask from `feTurbulence` so edges look printed). It lands: scale 1.6 → 1, rotate −8° → −3°, opacity 0 → 1 over 260ms with a slight overshoot (`cubic-bezier(.2,.9,.3,1.2)`), then the card jolts 1px down and back (80ms). The claim's highlight in the Exhibit fills with the verdict wash at the same moment. Not a claim: outline-only stamp, no jolt.

### 5.5 Compare split (agent vs text-only)
Press **Compare** (or B). The board shows the latest agent run and the latest text-only run for the same listing, overlaid; a vertical divider with a grab handle splits them. Left of the divider renders the text-only side (its stamps and the little evidence it found), right renders the agent side. Labels on the handle: "TEXT-ONLY" | "AGENT". Drag, or use ← → in 10% steps; B again closes it. Where the two disagree, the claim card shows a small "differs" tick on both sides. Data comes from `GET /api/compare/{listing_id}` (or both bundled recordings).

---

## 6. States and copy

- Loading: ruled skeleton lines on paper, never grey blobs.
- Errors in plain words with what to do next ("Can't reach the Praman server. Playing the recorded case instead.").
- Empty board before claims arrive: "Reading the page…" next to the spinning seal.
- **Quota line:** if the model's quota runs out mid-run, the run still finishes with `run_finished.quota_reached`; unchecked claims are **Needs review** and the board, the dossier and the downloaded Markdown all carry one calm line: **"Model quota reached: claims not yet checked are marked Needs review."** If no claims were listed at all, the empty board says "The model's quota ran out before the claims were listed."
- Copy rules from PRD §8 apply to every string: never "illegal", "violation", "greenwashing", "fraud" or "lying". Use "Proof not found on this page", "This certificate covers the company, not this claim", "Conflicts with the definition in the plastic waste rules".
- Brand names never appear when anonymise is on (the API masks them; the frontend never unmasks).

---

## 7. Pacing, director controls and present mode

The same reducer handles live runs and recordings. Between the event source and the reducer sits a **pacer**: a queue that releases events at a readable pace even when the backend replies instantly (replay mode finishes in about a second).

- Minimum gaps at 1×: step 500ms, claims 700ms, photo_read 2600ms (the Scan), registry_lookup 1500ms (the Ledger), evidence 450ms, verdict 900ms (the Stamp). Speeds 0.5× / 1× / 2× / instant.
- **Space** pauses or resumes. **→** releases exactly one event (step mode). **R** restarts the case. **1–4** open the demo cases. **B** compare. **E** report. **P** present mode. **?** shows the shortcut sheet.
- Director bar (bottom): play/pause, step, speed, and a row of ticks, one per event, filled as they play.
- **Present mode (P):** hides the URL field, the LLM-mode chips and the cost footer, scales type by 1.12, shows the director bar, and starts each case paused at the first event so the presenter begins when ready.

---

## 8. Offline and resilience

- If `GET /api/health` fails, the app switches to **recording mode**: it reads `public/demo/index.json` and plays the bundled recordings (`public/demo/<listing_id>.<mode>.json`, format in TRD §15.4). A small "RECORDING" chip shows this.
- The `/scan` screen has its own fallback: without a backend it shows `public/demo/scan_demo.json`, a recorded scan of an anonymised store; a live scan id that cannot be reached falls back to the same scan with one plain line.
- `npm run demo` serves the built app with no Python at all. So the demo has three layers: live backend → bundled recordings → backup video.
- No network requests except to our own API. No analytics, no fonts or icons from CDNs.

---

## 9. Don'ts

- No dark theme for the demo. No purple or blue gradients, glassmorphism, neon glows, or emoji.
- No default component-library look (shadcn cards, rounded-2xl, soft drop shadows everywhere).
- No chart library; the one chart is hand-built SVG.
- No Three.js or 3D. Every animation must show the agent doing something real; nothing decorative that loops while nothing is happening (except the seal while working and the intake teaser).
- No lorem ipsum or invented numbers. Synthetic recordings are marked synthetic in a visible chip.
- Don't block the demo on an animation: everything is skippable with "instant" speed.

---

## 10. Quality bar (check before calling the frontend done)

- Screenshots at 1280×720 and 1920×1080 of Intake, Case (mid-run and finished), Report, Evaluation; nothing clipped, nothing under 13px, the four signature moments visible.
- Keyboard-only run of a whole case in present mode.
- `prefers-reduced-motion` run: no sweeps, no spring motion, still clear.
- Wi-Fi off: `npm run demo` plays all four cases.
- If Lighthouse is available, accessibility ≥ 90 on Case and Report; otherwise check contrast, focus order and labels by hand.
