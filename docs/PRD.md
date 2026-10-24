# Praman: Product Requirements Document

| | |
|---|---|
| Version | 1.0 (18 Oct 2026) |
| Build and product owner | Savya Raj (research, rules, agent, UI, evaluation) |
| Presenter | Taksh Sonigra (pitch and live demo) |
| Business domain | **Retail and Supply** (product-listing assurance for retail catalogues) |
| Target event | AgentOps'26, MIT Bengaluru, Saturday 24 Oct 2026, Track 04 (Agents for sustainable development) |
| Status | Approved for build. Organisers confirmed building may start before the event (save their message). |

---

## 1. Summary

Praman (Hindi for "proof") is an AI agent that reads a product page, finds every environmental ("green") claim, works out what proof India's rules require for each one, and then hunts for that proof in the page text, the product photos and government registries. It returns a verdict per claim with the evidence, the rule and a compliant rewrite. A person approves every report. Nothing is published or sent automatically.

One-liner: **Brands make green claims they can't prove. Praman finds the proof, or tells them it isn't there, before a regulator or a customer does.**

### 1.1 Business domain and process fit

Praman addresses **Retail and Supply**: a marketplace catalogue/quality team or a D2C compliance reviewer must assure product listings at volume, and the proof behind a listing's environmental claims usually sits outside the page text (on the pack, in a registry, or nowhere).

| Required stage | Praman's implementation |
|---|---|
| Data ingestion | `scripts/fetch_cache.py`, `praman/tools/fetch.py`, `praman/tools/page.py`, `praman/tools/qr.py`, `data/cpcb_certified.csv` |
| Intelligent decision-making | `praman/agent.py` (bounded plan → act → observe → decide loop), `praman/claims.py`, `praman/tools/*`, `praman/verdict.py` |
| Action execution | `praman/rewrite.py` (suggested wording), `praman/scan.py` (ranked catalogue triage), `praman/report.py` (approvable export); read-only by rule |
| Outcome reporting | evidence ledger + trace in the web app, printable dossier, `eval/` agent-vs-baseline results |

The buyer, measured value and judge Q&A are in `docs/HACKATHON_BRIEF.md`.

---

## 2. Problem

### 2.1 The rule
- **15 Oct 2024:** the Central Consumer Protection Authority (CCPA) issued the *Guidelines for Prevention and Regulation of Greenwashing or Misleading Environmental Claims, 2024*.
  - Vague terms (eco-friendly, green, sustainable, natural, carbon-neutral, organic, pure, and similar) need adequate, accurate and accessible qualifiers, substantiation and disclosures.
  - Specific claims (compostable, degradable, free-of, non-toxic, recyclable, renewable, climate-positive, net-zero) need credible certification or verifiable scientific evidence.
  - Material details should be reachable through a QR code or URL; the claim must state its scope (product, part, packaging, process, disposal).
- **14 Mar 2024:** the Plastic Waste Management (Amendment) Rules require a CPCB certificate before compostable or biodegradable plastic carry bags and commodities are sold, define "biodegradable plastic" as leaving no microplastics, and require specific labels.

### 2.2 The evidence that the problem is real
- ASCI processed 222 ads with green claims between 15 Feb 2024 and 31 Mar 2025; homecare was 47% of violations; most cases were vague terms in online ads.
- There is no public data on CCPA enforcement so far, so brands mostly police themselves.
- **Our own check (16 Oct 2026):** 2,152 products from 12 Indian D2C stores; 386 (18%) made a clear environmental claim. A hand check of 20 of them (text and every photo):

| Result | Listings |
|---|---|
| Product-specific proof for the main claim | 1 |
| A link to a general certificates page | 2 |
| A real certificate, but for something else | 5 |
| No evidence at all | 12 |
| Contradicted their own page, photo or pack (overlaps the rows above) | 5 |

### 2.3 Why existing approaches fall short
- Manual legal review is slow and rarely done for every product page (our hypothesis; not yet validated with interviews).
- Existing AI scanners (for example GreenClaims Scanner, Clifford Chance's scanner) target EU rules and judge wording. They don't verify proof.
- A keyword checker misfires both ways: in our scan it counted a candle named "Cosmos" as a COSMOS certification and missed CPCB codes printed only on a box photo.

---

## 3. Users

| Persona | Situation | What they need from Praman |
|---|---|---|
| **Primary: brand marketing or compliance reviewer** at a D2C or FMCG brand | Approving product pages and ads before launch | Which claims are backed, which aren't, why, and how to reword them |
| D2C founder with no legal team | Writes listings themselves, copies competitors' wording | A fast pre-launch check in plain language |
| Marketplace or agency team (later) | Onboarding many sellers or writing listings at volume | Store-wide scans ranked by risk |

**Not a user:** anyone wanting to publicly accuse brands. Praman's output is a fix list, not a name-and-shame report.

---

## 4. Goals and non-goals

### Goals (hackathon v1.0)
1. Check one product listing end to end: claims → rules → evidence → verdicts → report.
2. Show genuine agency: the agent decides where to look next and changes course on what it finds.
3. Prove it with numbers: agent vs a fixed text-only baseline, against hand labels.
4. Demo reliably: offline from cache, deterministic, with a backup video.

### Non-goals (v1.0)
- Legal advice or legal conclusions ("illegal", "violation").
- Checking whether a claim is *true* in the physical world. Praman checks whether proof is **visible and adequate**.
- Amazon or Flipkart scraping.
- User accounts, payments, multi-tenant hosting.
- Fine-tuning models.

---

## 5. User stories

| ID | Story | Acceptance criteria | Priority |
|---|---|---|---|
| US-01 | As a reviewer, I paste a product URL and get a report | Shopify product URLs work; a run finishes in under 60 s live (target) and under 3 s in replay mode | P0 |
| US-02 | As a reviewer, I see every green claim on the page, including ones printed only in photos | Each claim shows its exact quote, type, scope and where it was found | P0 |
| US-03 | As a reviewer, I see which rule applies to each claim | Each claim lists rule IDs with a plain-English summary and the citation | P0 |
| US-04 | As a reviewer, I see the evidence behind each verdict | Each verdict links to evidence items (text quote, photo crop, registry row, link) | P0 |
| US-05 | As a reviewer, I see how the agent reached its verdict | A trace panel shows each plan → act → observe → decide step | P0 |
| US-06 | As a reviewer, I get a compliant rewrite for weak claims | Every Not backed, Partly backed or Contradicted claim has a suggested rewrite | P1 |
| US-07 | As a reviewer, I approve the report before export | Export is disabled until "Approve" is clicked; the approver's name is recorded | P0 |
| US-08 | As the team, we compare the agent with a fixed baseline | One command runs both modes on all labelled listings and writes a results table | P0 |
| US-09 | As a presenter, I can hide brand names during a demo | Anonymise mode masks store names and brand words in all screens and exports | P0 |
| US-10 | As a presenter, the demo works without Wi-Fi | Offline/replay mode runs the 4 demo listings from cache with no network | P0 |
| US-11 | As a reviewer, I see cost and time per report | Report footer shows model calls, tokens, estimated cost and seconds | P1 |
| US-12 | As a reviewer, the agent follows a QR code on the pack | QR codes in photos are decoded and the linked page searched for proof | P2 |
| US-13 | As a brand, I scan my whole store | A store URL produces a ranked list of risky product pages | P2 |

---

## 6. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | **Input:** product URL (fetch `<store>/products/<handle>.json`), pasted text plus uploaded photos, or a cached listing ID | P0 |
| FR-02 | **Claim extraction:** find each environmental claim with exact quote, type (vague, specific, comparative, future), scope (product, part, packaging, process, disposal, delivery, brand) and location (title, description, tag, photo N) | P0 |
| FR-03 | **Not-a-claim filter:** skip puffery, mission statements not tied to a product, and words used as a subject (for example a course titled "Sustainability") | P0 |
| FR-04 | **Rule matching** from `data/rules.json` by trigger terms and claim type; returns the proof each rule needs | P0 |
| FR-05 | **Evidence search** in this default order: page text → product photos (up to 5, box backs first) → CPCB registry → linked certificate page on the same site | P0 (linked page P1) |
| FR-06 | **Agent loop:** plan → act → observe → decide per claim; re-plan when proof is missing; at most 2 follow-ups; stop with Needs review when out of budget | P0 |
| FR-07 | **Consistency check:** detect conflicts inside the listing (e.g. "plastic-free" vs "nylon bristles"; "100 times" vs "200 times"; "0% plastic" on compostable plastic) | P1 |
| FR-08 | **Verdicts:** Backed, Partly backed, Not backed, Contradicted, Needs review, Not a claim (definitions in §7). A verdict without cited evidence and rule IDs is downgraded to Needs review | P0 |
| FR-09 | **Rewrite:** suggest a compliant rewording for every claim that isn't Backed | P1 |
| FR-10 | **Trace panel:** every step with tool name, input summary, result summary, time and cost | P0 |
| FR-11 | **Report export:** Markdown and HTML with claims, verdicts, evidence, rule summaries, rewrites, CPCB list date and disclaimer | P0 |
| FR-12 | **Human approval:** export only after approval; approver name and time stored | P0 |
| FR-13 | **Baseline mode:** the same pipeline with photos, registry and re-planning switched off | P0 |
| FR-14 | **Evaluation:** run agent and baseline on labelled listings; output agreement, false Backed, proof-missed-by-baseline, cost and time | P0 |
| FR-15 | **Offline/replay mode:** cached listings and recorded model responses; no network | P0 |
| FR-16 | **Anonymise mode:** mask store domains and brand names in UI and exports | P0 |
| FR-17 | **Cost and time** per run | P1 |
| FR-18 | **QR decoding** in photos (stretch) | P2 |
| FR-19 | **Store scan** (stretch) | P2 |

---

## 7. Verdicts

| Verdict | Meaning | Must include |
|---|---|---|
| **Backed** | The proof the rule requires was found and verified, and it covers this claim and this product | ≥1 evidence item with covers_claim = yes from a required source; rule IDs |
| **Partly backed** | Some proof, but it covers part of the claim, or isn't tied to this product | Evidence items; rule IDs; what's missing |
| **Not backed** | No proof found in text, photos, registry or linked pages | Rule IDs; list of sources searched |
| **Contradicted** | The listing's own text, photo or pack conflicts with the claim | The conflicting evidence item(s); rule IDs |
| **Needs review** | Undecided within the step budget, or a required item may exist offline | Reason; sources searched |
| **Not a claim** | Puffery, mission statement, or not environmental | Reason |

---

## 8. UX requirements

### Screens (web app; full spec in `docs/DESIGN.md`)
1. **Intake:** URL box (live mode only) and four case folders for the demo listings.
2. **Case:** three columns. Left, the exhibit: listing title, photos, description with every claim highlighted in place. Centre, the board: claim cards, evidence cards (photo crops, CPCB ledger rows, quotes, conflicts) joined by threads, and a verdict stamp on each claim. Right, the live trace, one row per plan → act → observe → decide step. Mode switch (Agent / Text-only), Compare split, director controls for pacing.
3. **Claim detail** (on the card): exact quote, rule summary and citation, evidence, verdict reason, suggested rewrite.
4. **Report:** a printable dossier: summary counts, all claims, CPCB list date, disclaimer, Approve (name field) gating Export (PDF via print, Markdown).
5. **Evaluation:** agent vs text-only agreement, false "Backed" count, proof only the agent found, disagreements with links to their cases.

### Copy rules
- Never write "illegal", "violation", "greenwashing" or "fraud" about a brand.
- Use: "Proof not found on this page", "This certificate covers X, not this claim", "Conflicts with the definition in the plastic waste rules".
- Every report ends with: "Decision support, not legal advice. Based on what is visible on the listing on <date>. CPCB list dated 26 Oct 2023."

---

## 9. Success metrics (targets until measured on Thu 22 Oct)

| Metric | Definition | Target |
|---|---|---|
| Verdict agreement | Share of claims whose verdict matches the hand label | ≥ 80% for the agent, clearly above the baseline |
| False Backed | Claims marked Backed that the hand label says aren't | 0 |
| Proof the baseline missed | Claims backed only through photos or the registry | ≥ 2 |
| Run time | Live run on a demo listing | ≤ 60 s |
| Cost | Model cost per listing | Shown; no target |

Hold out 10 labelled listings that prompts are never tuned on; report them separately.

---

## 10. Constraints

- **Legal and ethical:** public pages only; respect robots.txt; at most 1 request per second per domain; same-site links only; no brand names in public artefacts (deck, README examples, posts); not legal advice.
- **Data:** no personal data. The repo stays **private** until listing data is anonymised.
- **Time:** v1.0 frozen Thu 22 Oct night; event-day work on a separate branch.
- **Rules:** the hackathon site still says pre-built projects aren't allowed; keep the organisers' written permission and commit history from 18 Oct.

---

## 11. Release plan

| Version | Day | Contents |
|---|---|---|
| v0.1 | Mon 19 Oct | CLI: compostable-bags listing runs end to end (text + CPCB path) |
| v0.5 | Tue 20 Oct | Photo reading, agent loop, verdicts, baseline mode; 4 demo listings get verdicts in both modes |
| v0.9 | Wed 21 Oct | Web app (FastAPI + React): live trace, photo scan, registry ledger, verdict stamps, compare split, dossier report with approval, anonymise mode, offline replay and bundled recordings |
| v1.0 | Thu 22 Oct | Evaluation run, golden-trace tests, prompt fixes; feature freeze |
| v1.1 | Sat 24 Oct | One event-day addition (QR decoding or store scan) on a branch, merged only if tests pass |
| v2 | After the event | Portfolio: 150-listing evaluation set, store scan, more registries, deployment |

---

## 12. Demo cases

| Role | Listing | Expected path | Expected verdicts |
|---|---|---|---|
| Normal | L14 compostable garbage bags | text: no proof → photos: two CPCB codes → registry: both makers listed → consistency: "0% plastic" | compostable: Backed; "0% plastic": Contradicted; industrial-composting label: Needs review |
| Failure | L06 oxo-biodegradable disposal bags | text: no proof → photos: "PE Virgin Grade" + 5% additive → stop early | eco-friendly / biodegradable: Contradicted |
| Ambiguous | L08 bamboo toothbrush | text: B Corp badge → certificate scope check → consistency: nylon vs plastic-free; "Almost" vs zero waste | plastic-free: Contradicted; zero waste: Contradicted; compostable handle: Partly backed |
| Not a claim | L21 "Building Blocks of Sustainability" course | extraction marks it not a claim | Not a claim, no tool calls |

---

## 13. Open questions

| Question | Owner | Due |
|---|---|---|
| Demo format and time limit | Taksh (from the 10:30 briefing) | 24 Oct |
| Judging criteria and weights | Organisers | Unannounced |
| Exact CCPA clause numbers for each rule | Savya (from the official notification) | Mon 19 Oct |
| Gemini model name and free-tier limits on our keys | Savya | Sun 18 Oct |
| Does the vision model read the CPCB codes on the bags box? | Savya (photo probe) | Sun 18 Oct |
