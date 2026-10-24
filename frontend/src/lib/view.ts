// Pure view helpers: verdict styling keys, evidence cards built from evidence events, claim
// highlights in the listing text, and formatting. Kept out of components so they can be tested.

import type { Box, Claim, CoversClaim, Evidence, PhotoItem, RuleChip, VerdictLabel } from "./events";
import type { CaseState, RegistryRow } from "./reducer";

export type VerdictKey = "backed" | "partly" | "not" | "contra" | "review" | "none";

export const VERDICT_KEY: Record<VerdictLabel, VerdictKey> = {
  Backed: "backed",
  "Partly backed": "partly",
  "Not backed": "not",
  Contradicted: "contra",
  "Needs review": "review",
  "Not a claim": "none",
};

export const verdictVar = (label: VerdictLabel): string => `var(--v-${VERDICT_KEY[label]})`;
export const verdictWash = (label: VerdictLabel): string => `var(--v-${VERDICT_KEY[label]}-wash)`;

export const COVER_VAR: Record<CoversClaim, string> = {
  yes: "var(--v-backed)",
  partly: "var(--v-partly)",
  no: "var(--v-not)",
  contradicts: "var(--v-contra)",
};

const COVER_RANK: Record<CoversClaim, number> = { contradicts: 3, yes: 2, partly: 1, no: 0 };

// ---------------------------------------------------------------------------
// Claims

/** "description" → "DESCRIPTION", "photo:7" → "PHOTO 7", "n/a" → "LABEL CHECK". */
export function locationLabel(c: Pick<Claim, "location" | "derived_from">): string {
  const loc = c.location.trim().toLowerCase();
  if (loc === "n/a" || c.derived_from) return "LABEL CHECK";
  const m = /^photo:(\d+)$/.exec(loc);
  if (m) return `PHOTO ${m[1]}`;
  return loc.toUpperCase();
}

export function photoOfClaim(c: Claim): number | null {
  const m = /^photo:(\d+)$/.exec(c.location.trim().toLowerCase());
  return m ? Number(m[1]) : null;
}

/** Rule chip text: "R08 · Rule 11(3)", or the short source when the clause isn't confirmed. */
export function ruleChipText(id: string, rule: RuleChip | undefined): string {
  if (!rule) return id;
  return `${id} · ${shortClause(rule)}`;
}

/** "Rule 4(1)(ha) (CPCB certificate …); Rule 4(1)(h) …" in the PWM rules → "PWM 4(1)(ha)". */
export function shortClause(rule: RuleChip): string {
  const src = shortSource(rule.source);
  if (!rule.clause || /to be confirmed/i.test(rule.clause)) return src;
  const first = rule.clause.split(/;|\s\(/)[0]?.trim() ?? rule.clause;
  const bare = first.replace(/^(Rule|Clause|Section|Para(graph)?)\s+/i, "");
  return `${src.split(" ")[0]} ${bare}`;
}

export function shortSource(source: string): string {
  if (/ccpa/i.test(source)) return "CCPA 2024";
  if (/plastic waste/i.test(source)) return "PWM 2024";
  return source.split(",")[0]?.trim() ?? "";
}

// ---------------------------------------------------------------------------
// Highlights: where each claim's quote sits in a piece of listing text.

export interface Range {
  start: number;
  end: number;
  claimId: string;
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Find each claim's quote in `text` (case-insensitive, any whitespace). Overlaps keep the first. */
export function findRanges(text: string, claims: readonly Pick<Claim, "id" | "quote">[]): Range[] {
  const found: Range[] = [];
  for (const c of claims) {
    const q = c.quote.trim().replace(/[.。]+$/, "");
    if (q.length < 2) continue;
    const re = new RegExp(escapeRe(q).replace(/\s+/g, "\\s+"), "i");
    const m = re.exec(text);
    if (!m) continue;
    const r = { start: m.index, end: m.index + m[0].length, claimId: c.id };
    if (found.some((f) => r.start < f.end && f.start < r.end)) continue;
    found.push(r);
  }
  return found.sort((a, b) => a.start - b.start);
}

export interface Segment {
  text: string;
  claimId: string | null;
}

export function segments(text: string, ranges: readonly Range[]): Segment[] {
  const out: Segment[] = [];
  let at = 0;
  for (const r of ranges) {
    if (r.start > at) out.push({ text: text.slice(at, r.start), claimId: null });
    out.push({ text: text.slice(r.start, r.end), claimId: r.claimId });
    at = r.end;
  }
  if (at < text.length) out.push({ text: text.slice(at), claimId: null });
  return out;
}

// ---------------------------------------------------------------------------
// Evidence cards. The same print (e.g. one certificate on photo 8) often serves several claims;
// it becomes one card with a thread to each claim.

export type EvidenceCardKind = "photo" | "registry" | "conflict" | "certificate" | "qr" | "text";

export interface EvidenceLink {
  evidenceId: string;
  claimId: string;
  covers: CoversClaim;
}

export interface EvidenceCardModel {
  key: string;
  kind: EvidenceCardKind;
  ids: string[];
  first: Evidence;
  links: EvidenceLink[];
  /** strongest coverage over the links (for the card's edge colour) */
  covers: CoversClaim;
  /** seq of the first evidence event in the card */
  seq: number;
  // kind-specific fields
  printed?: string;
  photoIndex?: number;
  box?: Box;
  itemKind?: PhotoItem["kind"];
  location?: string;
  quote?: string;
  conflict?: { a: string; aTag: string; b: string; bTag: string };
  registry?: RegistryRow;
  ruleId?: string | null;
  qr?: { domain: string; followed: boolean; path: string | null };
}

const TEXT_PREFIX = /^(Description|Title|Tags?|FAQ|Page|Photo \d+|Link|[A-Z][\w ]{0,20}):\s+/;

/** "Description: BPA-free nylon…" → { location: "DESCRIPTION", quote: "BPA-free nylon…" } */
export function splitDetail(detail: string): { location: string; quote: string } {
  const m = TEXT_PREFIX.exec(detail);
  if (!m) return { location: "PAGE", quote: detail };
  return { location: (m[1] ?? "").toUpperCase(), quote: detail.slice(m[0].length) };
}

/** `"A" vs "B" (description)` → parts, for consistency evidence without a `conflict` field. */
export function parseVs(detail: string): { a: string; b: string; bLocation: string | null } | null {
  const m = /^["“](.+?)["”]\s+vs\.?\s+["“](.+?)["”](?:\s*\(([^)]+)\))?\s*$/.exec(detail.trim());
  if (!m?.[1] || !m[2]) return null;
  return { a: m[1], b: m[2], bLocation: m[3] ?? null };
}

function cardKind(e: Evidence): EvidenceCardKind {
  if (e.qr) return "qr";
  if (e.source === "registry") return "registry";
  if (e.source === "consistency" || e.conflict) return "conflict";
  if (e.source === "text" && e.covers_claim === "contradicts") return "conflict";
  if (e.cert_scope && ["company", "ingredient", "other"].includes(e.cert_scope)) return "certificate";
  if (e.source === "photo" && e.photo_index != null) return "photo";
  return "text";
}

function dedupeKey(e: Evidence, kind: EvidenceCardKind): string {
  if (kind === "conflict") return `${e.id}`; // each conflict is about its own claim
  if (kind === "registry") return `reg:${e.detail}`;
  if (kind === "qr" && e.qr) return `qr:${e.photo_index ?? ""}:${e.qr.domain}:${e.qr.path ?? ""}`;
  if (e.source === "photo" && e.crop_box) return `photo:${e.photo_index}:${e.crop_box.join(",")}`;
  return `${e.source}:${e.detail}`;
}

export function findRegistryRow(state: CaseState, e: Evidence): RegistryRow | undefined {
  const forClaim = state.registry.filter((r) => r.claim_id === e.claim_id || r.claim_id === null);
  return (
    forClaim.find((r) => e.detail.includes(r.query)) ??
    forClaim.find((r) => r.match && e.detail.includes(`S.No. ${r.match.s_no}`)) ??
    state.registry.find((r) => e.detail.includes(r.query))
  );
}

function photoItemFor(state: CaseState, photo: number, box: Box): PhotoItem | undefined {
  return (state.photoPrint[photo] ?? []).find((it) => it.box_2d && it.box_2d.join(",") === box.join(","));
}

export function evidenceCards(state: CaseState): EvidenceCardModel[] {
  const claims = new Map(state.claims.map((c) => [c.id, c] as const));
  const cards = new Map<string, EvidenceCardModel>();
  for (const e of state.evidence) {
    const kind = cardKind(e);
    const key = dedupeKey(e, kind);
    const link: EvidenceLink = { evidenceId: e.id, claimId: e.claim_id, covers: e.covers_claim };
    const existing = cards.get(key);
    if (existing) {
      existing.ids.push(e.id);
      existing.links.push(link);
      if (COVER_RANK[e.covers_claim] > COVER_RANK[existing.covers]) existing.covers = e.covers_claim;
      continue;
    }
    const card: EvidenceCardModel = {
      key,
      kind,
      ids: [e.id],
      first: e,
      links: [link],
      covers: e.covers_claim,
      seq: state.evidenceSeq[e.id] ?? 0,
      ruleId: e.rule_id ?? null,
    };
    if (e.photo_index != null) card.photoIndex = e.photo_index;
    if (e.crop_box) card.box = e.crop_box;
    if (kind === "photo" || kind === "certificate") {
      card.printed = e.detail.replace(/^Photo \d+:\s*/, "");
      if (e.photo_index != null && e.crop_box) card.itemKind = photoItemFor(state, e.photo_index, e.crop_box)?.kind;
    } else if (kind === "registry") {
      card.registry = findRegistryRow(state, e);
    } else if (kind === "qr" && e.qr) {
      card.qr = { domain: e.qr.domain, followed: e.qr.followed, path: e.qr.path ?? null };
    } else if (kind === "conflict") {
      const claim = claims.get(e.claim_id);
      const claimTag = claim ? `${claim.id} · ${locationLabel(claim)}` : e.claim_id;
      if (e.conflict) {
        card.conflict = {
          a: e.conflict.a,
          aTag: claimTag,
          b: e.conflict.b,
          bTag: (e.conflict.b_location ?? "LISTING").toUpperCase(),
        };
      } else {
        const vs = parseVs(e.detail);
        if (vs) {
          card.conflict = { a: vs.a, aTag: claimTag, b: vs.b, bTag: (vs.bLocation ?? "LISTING").toUpperCase() };
        } else {
          const { location, quote } = splitDetail(e.detail);
          card.conflict = { a: claim?.quote ?? e.claim_id, aTag: claimTag, b: quote, bTag: location };
        }
      }
    } else {
      const { location, quote } = splitDetail(e.detail);
      card.location = location;
      card.quote = quote;
    }
    cards.set(key, card);
  }
  return [...cards.values()];
}

// ---------------------------------------------------------------------------
// Photos and boxes

/** Item weight when choosing which photo the Scan shows: proof-like print first. */
const KIND_WEIGHT: Record<PhotoItem["kind"], number> = {
  code: 4,
  certificate: 3,
  composition: 3,
  label: 2,
  claim: 1,
  other: 0,
};

export function scanPhotoIndex(photos: readonly { index: number; items: readonly PhotoItem[] }[], prefer?: number): number | null {
  if (prefer != null && photos.some((p) => p.index === prefer)) return prefer;
  let best: number | null = null;
  let bestScore = -1;
  for (const p of photos) {
    const score = p.items.reduce((a, it) => a + KIND_WEIGHT[it.kind] + (it.box_2d ? 0.1 : 0), 0);
    if (score > bestScore) {
      best = p.index;
      bestScore = score;
    }
  }
  return best;
}

/** Pad a box (0–1000) so a crop has some breathing room, clamped to the photo. */
export function padBox(b: Box, padY = 18, padX = 14): Box {
  return [Math.max(0, b[0] - padY), Math.max(0, b[1] - padX), Math.min(1000, b[2] + padY), Math.min(1000, b[3] + padX)];
}

// ---------------------------------------------------------------------------
// Formatting

export function formatMs(ms: number): string {
  if (ms <= 0) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatClock(ms: number): string {
  const total = Math.max(0, ms) / 1000;
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-18T09:59:28Z" → "18 Oct 2026" (the listing date in the disclaimer). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${formatDate(iso)}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** "2023-10-26" → "26 OCT 2023" for ledger headers. */
export function ledgerDate(iso: string): string {
  return formatDate(`${iso}T12:00:00`).toUpperCase();
}

export function formatInr(x: number): string {
  return `₹${x.toFixed(2)}`;
}

/** Decide-row colour in the trace: "Backed: …" → Backed. */
export function labelFromSummary(summary: string): VerdictLabel | null {
  const m = /^(Backed|Partly backed|Not backed|Contradicted|Needs review|Not a claim)\b/.exec(summary);
  return (m?.[1] as VerdictLabel | undefined) ?? null;
}

// ---------------------------------------------------------------------------
// Compare: pair agent claims with text-only claims by quote similarity (rapidfuzz.ratio ≥ 80).

function normaliseQuote(s: string): string {
  return s.toLowerCase().replace(/[^\p{L}\p{N}%]+/gu, " ").trim();
}

/** Indel similarity in 0–100, like rapidfuzz.fuzz.ratio. */
export function ratio(a: string, b: string): number {
  if (!a.length && !b.length) return 100;
  const prev = new Array<number>(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    let diag = 0;
    for (let j = 1; j <= b.length; j++) {
      const up = prev[j] ?? 0;
      prev[j] = a[i - 1] === b[j - 1] ? diag + 1 : Math.max(up, prev[j - 1] ?? 0);
      diag = up;
    }
  }
  const lcs = prev[b.length] ?? 0;
  return (200 * lcs) / (a.length + b.length);
}

export function bestMatch<T extends Pick<Claim, "quote">>(quote: string, candidates: readonly T[]): T | null {
  const q = normaliseQuote(quote);
  let best: T | null = null;
  let bestScore = 0;
  for (const c of candidates) {
    const s = ratio(q, normaliseQuote(c.quote));
    if (s > bestScore) {
      best = c;
      bestScore = s;
    }
  }
  return bestScore >= 80 ? best : null;
}

/**
 * One short line for the compare split where a side has nothing for a claim: either it never saw
 * the claim, or it saw it and found no proof. `label` is that side's verdict, when it has one.
 */
export function compareGapLine(
  side: "agent" | "baseline",
  claim: Pick<Claim, "location" | "derived_from"> | null,
  other: Pick<Claim, "location" | "derived_from"> | null,
  label: string | null,
): string {
  const who = side === "baseline" ? "Text-only" : "The agent";
  if (!claim) {
    if (side === "agent") return "The agent didn't list this claim.";
    if (other && (other.derived_from || other.location.trim().toLowerCase() === "n/a")) {
      return "Text-only never checked the required label: it comes from the pack check.";
    }
    if (other && /^photo:\d+$/.test(other.location.trim().toLowerCase())) {
      return "Text-only never saw this claim: it's printed on the pack.";
    }
    return "Text-only didn't list this claim.";
  }
  if (label === "Not a claim") return "Not a claim, so no proof was needed.";
  if (label === "Contradicted") return `${who} found a conflict but no proof for this claim.`;
  return `${who} found no proof for this claim.`;
}
