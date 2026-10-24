# Praman Demo Script (5-Minute Walkthrough)

A structured script for presenting Praman in 5 minutes. Praman audits e-commerce green claims against packaging photos, statutory rules, and the official CPCB registry.

**Business domain (say it first): Retail and Supply.** Praman is product-listing assurance for retail catalogues: a marketplace or D2C team needs to know which seller pages to check and whether the claims on them are backed by proof. The demo is the process: **ingestion** (page, photos, QR, CPCB registry) → **decision** (claims, rules, evidence, verdicts) → **action** (rewrites, ranked triage, report) → **reporting** (evidence ledger, dossier, evaluation). Full brief: `docs/HACKATHON_BRIEF.md`.

> **Copy & Presentation Rule**: Praman reports verifiable proof visible on product pages and packaging. Never use inflammatory language like "illegal", "violation", "greenwashing", "fraud", or "lying". Real brand names may be shown; say "the page doesn't show the proof", never that a brand is wrong. Present Praman as an objective, evidence-driven verification ledger.

---

## Quick Reference: Keyboard Shortcuts

| Key | Action |
|:---:|:---|
| <kbd>P</kbd> | Toggle **Present mode** (larger typography, high-contrast badges, step pacer controls) |
| <kbd>1</kbd> | Open **Case 1: L14** (Compostable garbage bags · CPCB registry match & rule contradiction) |
| <kbd>2</kbd> | Open **Case 2: L06** (Oxo-biodegradable garbage bags · photo resin check & oxo rule) |
| <kbd>3</kbd> | Open **Case 3: L08** (Bamboo toothbrush · scope ambiguity & material consistency) |
| <kbd>4</kbd> | Open **Case 4: L21** (Sustainability course · non-claim filtering with zero tool calls) |
| <kbd>Space</kbd> | Pause or resume event playback |
| <kbd>→</kbd> | Step forward release of exactly one event |
| <kbd>B</kbd> | Toggle **Compare mode** (side-by-side: Agent vs Text-only baseline) |
| <kbd>E</kbd> | Open **Evidence Report** (exportable verification dossier) |
| <kbd>R</kbd> | Restart the current case playback |
| <kbd>?</kbd> | Show the shortcut reference sheet |
| <kbd>Esc</kbd> | Close overlay or modal dialog |

---

## 5-Minute Presentation Timeline

```
0:00 - 0:45   Introduction & The Problem (Intake screen)
0:45 - 2:00   Case 1 (L14): Registry Discovery & The Power of Photos (Keys: 1, Space, B, E)
2:00 - 2:50   Case 2 (L06): Material Contradiction on Pack (Key: 2)
2:50 - 3:35   Case 3 (L08): Scope & Absolute Claims (Key: 3)
3:35 - 4:05   Case 4 (L21): Intelligent Filtering (Key: 4)
4:05 - 4:40   Store Scan: Bulk Triage Without Model Calls (/scan)
4:40 - 5:00   Architecture, Trust Boundaries & Fallback Plan
```

---

## Step-by-Step Presenter Script

### 0:00 – 0:45 · Introduction (Intake Screen)

1. **Setup**: Start on the intake screen (`/`). Press <kbd>P</kbd> to ensure **Present mode** is enabled.
2. **Narration**:
   > "Retail catalogues carry thousands of environmental claims, and the proof is usually not on the page — it is on the pack, in a registry, or nowhere. Manual review does not scale, and text-only AI checks miss both the proof and the contradictions printed on the box.
   >
   > This is Praman: product-listing assurance for retail. It ingests the listing, its pack photos, QR codes and the CPCB registry; extracts every claim; decides what proof the rules require; hunts for it with a small validated tool loop; and returns a verdict with the evidence, the rule and a suggested rewrite. Code applies the clear-cut rules, the model reads and reasons, and nothing leaves the tool without a named human approving it.
   >
   > Let's look at four distinct cases."

---

### 0:45 – 2:00 · Case 1: L14 (Compostable Garbage Bags)

1. **Action**: Press <kbd>1</kbd> to load **Case L14**. If paused, press <kbd>Space</kbd> to let the pacer play, or use <kbd>→</kbd> to step through key milestones.
2. **Visual Focus**:
   - The claims ledger populates: *"100% compostable garbage bags"*.
   - Watch the agent initiate `read_photos`: the UI crops and zooms directly into the packaging panel (Photo 7).
   - Point out the extracted manufacturer codes:
     - `CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443`
     - `CPCB-UPC-II/SUNSHIELD BIOTECH LLP/Gujarat/131`
   - Notice the next tool call: `cpcb_lookup`. The agent queries the local CPCB database (Central Pollution Control Board, 26 Oct 2023 certified list).
   - Both manufacturers match Table 1 (Gujarat). The compostable claim earns **Backed**.
   - Now look at the photo-derived claims: the back of the box also prints *"100% ecofriendly, 0% plastic"*.
   - Regulatory rule **R07** triggers: under statutory standards, certified compostable plastics are bio-polymers; claiming "0% plastic" while marketing certified compostable material is an absolute contradiction (**Contradicted**).
   - Rule **R08** also triggers: compostable items require an explicit label stating *"compostable only under industrial composting"*, which is absent (**Needs review**).
3. **Show Compare**: Press <kbd>B</kbd>.
   - Point out the side-by-side split:
     - *Agent (left)*: reads the packaging photo, verifies the CPCB codes, and flags the contradiction.
     - *Text-only baseline (right)*: sees only the web page text, cannot find the CPCB code, scores the claim **Not backed**, and completely misses the "0% plastic" contradiction printed on the physical box.
   - Press <kbd>B</kbd> or <kbd>Esc</kbd> to exit Compare.
4. **Show Dossier**: Press <kbd>E</kbd> to open the formal Evidence Report, showing the timestamped audit trail, photo crops, and registry citations. Press the back button or browser back to return.

---

### 2:00 – 2:50 · Case 2: L06 (Oxo-Biodegradable Bags)

1. **Action**: Press <kbd>2</kbd> to load **Case L06**.
2. **Narration**:
   > "Our second case highlights how packaging photos can reveal direct material contradictions.
   >
   > Here, the listing claims 'Oxo-biodegradable bags for eco-friendly disposal' and 'converts into biodegradable material via oxidation'.
   >
   > The agent reads Photo 3 of the packaging. The pack print explicitly specifies the material: *Carrier Resin: PE Virgin Grade with 5% Additive*.
   >
   > Under Plastic Waste Management rules (rule **R09**), conventional polyethylene with pro-oxidant additives fragments into microplastics rather than genuinely biodegrading. The claim is stamped **Contradicted** based on the manufacturer's own printed resin disclosure."

---

### 2:50 – 3:35 · Case 3: L08 (Bamboo Toothbrush)

1. **Action**: Press <kbd>3</kbd> to load **Case L08**.
2. **Narration**:
   > "Our third case tests nuance and scope.
   >
   > The listing advertises a 'Zero waste oral care' kit and 'fully compostable bamboo toothbrush'.
   >
   > When Praman examines the product composition, the handle is genuine bamboo—which is indeed compostable—but the bristles are nylon. The listing's own fine print acknowledges that nylon bristles must be removed with pliers before disposal.
   >
   > Under rule **R04**, broad environmental claims that conflate one recyclable part with an entire composite product cannot be stamped Backed. The absolute claim 'zero waste' is **Contradicted**, while the specific claim 'biodegradable bamboo handle' is correctly marked **Partly backed**."

---

### 3:35 – 4:05 · Case 4: L21 (Sustainability Course / Educational Non-Claim)

1. **Action**: Press <kbd>4</kbd> to load **Case L21**.
2. **Narration**:
   > "Our fourth case demonstrates efficiency and restraint.
   >
   > This page lists a workshop titled 'Building blocks of sustainability'.
   >
   > An unconstrained AI might attempt to audit the course syllabus. But Praman's claim extraction recognizes that this is an educational title, not an environmental product marketing claim.
   >
   > It classifies the text as **Not a claim**, terminates immediately, and spends zero tool calls and zero model tokens. Praman knows when to audit and when to stop."

---

### 4:05 – 4:40 · Store Scan: Rapid Bulk Triage (`/scan`)

1. **Action**: Click **Store scan** in the top navigation or navigate to `/scan`.
2. **Narration**:
   > "What happens when an enterprise or regulator needs to inspect an entire catalog? Running deep vision inspection on thousands of items would be expensive and slow.
   >
   > This is Praman's **Store Scan**: a rapid, zero-model-cost triage system.
   >
   > It scans up to 50 product pages using store sitemaps, strictly respecting robots.txt and server rate limits at one request per second.
   >
   > In plain Python—without any LLM calls—it scans the text for regulatory trigger terms (compostable, biodegradable, recycled) and evidence signals (CPCB codes, ISO certifications). It ranks the catalog into risk bands: High Attention, Medium, and Minimal.
   >
   > From this triage view, an auditor clicks 'Check this product' to dispatch our multimodal agent only on high-priority items."

---

### 4:40 – 5:00 · Architecture & Fallback Plan

1. **Wrap-up**:
   > "To summarize Praman:
   > - The LLM reads and extracts evidence; deterministic Python applies statutory rules and verdicts.
   > - Business value, measured: on our dev set the agent agrees with the labels on 63% of matched claims against 52% for a text-only baseline, finds eight pieces of proof the baseline cannot see, and never marks an unproven claim Backed. Store triage costs zero model calls; a deep check costs about ten model calls.
   > - Oversight is structural: read-only tools, evidence-or-nothing verdicts, careful wording that never accuses a brand, and a named human approval before any export.
   > - Reproducibility is baked in: all runs are recorded and replay offline with zero network dependence."
2. **Closing**: "Thank you. We are happy to take questions or dive into any case file."

---

## Presenter Contingency & Fallback Guide

If anything unexpected occurs during a live demonstration, follow this tiered fallback plan:

### 1. Model Quota or Network Slowdown
- **Symptom**: Model calls take >10 seconds or return quota alerts.
- **Remedy**: Switch the runtime mode to `replay` or `offline`:
  ```bash
  # In your terminal or .env
  PRAMAN_LLM_MODE=replay
  ```
  Praman will immediately serve the deterministic recorded cache without hitting external APIs.

### 2. Local Backend Service Failure
- **Symptom**: FastAPI server on port 8000 stops or crashes.
- **Remedy**: Switch the frontend to bundled recording demo mode:
  ```bash
  cd frontend
  npm run demo
  ```
  This serves the Vite application in pure standalone mode. The frontend automatically detects that `/api/health` is offline and seamlessly switches to the bundled recordings in `public/demo/` with full interactive playback, hotkeys, and comparison views.

### 3. Complete Local Machine Failure or Wi-Fi Outage
- **Symptom**: Laptop display failure, Node/Python environment issue, or local network cutoff.
- **Remedy**: Open the live production mirror on any device (phone, backup laptop, or tablet):
  **[https://praman-proof.vercel.app](https://praman-proof.vercel.app)**
  - This deployment is hosted on Vercel with all demo cases (L14, L06, L08, L21) and the store scan pre-bundled.
  - Deep links work directly: e.g. `https://praman-proof.vercel.app/case/L14.agent`.
