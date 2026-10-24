// One pure reducer that turns events (live or recorded) into case state. Claims and verdicts are
// upserted by id (TRD §15.3: both may be sent again); everything keyed by claim id survives events
// that arrive for a claim the state hasn't seen yet.

import type {
  Claim,
  ErrorData,
  Evidence,
  ListingData,
  LlmMode,
  Mode,
  PhotoItem,
  PhotoReadData,
  PramanEvent,
  RegistryLookupData,
  RuleChip,
  RunFinishedData,
  StepData,
  Verdict,
} from "./events";

export interface StepRow extends StepData {
  seq: number;
  t_ms: number;
}

export interface PhotoReadRow extends PhotoReadData {
  seq: number;
}

export interface RegistryRow extends RegistryLookupData {
  seq: number;
}

export interface VerdictRow extends Verdict {
  /** seq of the event that set the current label (a re-sent verdict with the same label keeps it) */
  seq: number;
}

/** The overlay moments (DESIGN §5.1, §5.2): open from their event until the agent moves on. */
export interface ScanMoment {
  seq: number;
  read: PhotoReadRow;
}
export interface LedgerMoment {
  seq: number;
  lookup: RegistryRow;
}

export interface CaseState {
  runId: string | null;
  listingId: string | null;
  mode: Mode | null;
  llmMode: LlmMode | null;
  startedAt: string | null;
  listing: ListingData | null;
  claims: Claim[];
  evidence: Evidence[];
  evidenceSeq: Record<string, number>;
  verdicts: Record<string, VerdictRow>;
  steps: StepRow[];
  photoReads: PhotoReadRow[];
  /** Every printed item read so far, by photo index. */
  photoPrint: Record<number, PhotoItem[]>;
  registry: RegistryRow[];
  /** Every rule seen on a verdict, by id (for chips and conflict cards). */
  rules: Record<string, RuleChip>;
  activeClaimId: string | null;
  /** Claim ids with at least one step (so the board knows what is still waiting). */
  touched: Record<string, true>;
  scan: ScanMoment | null;
  ledger: LedgerMoment | null;
  finished: RunFinishedData | null;
  error: ErrorData | null;
  lastSeq: number;
  /** lastSeq before the latest release batch: things with a higher seq are new (animate them). */
  batchFromSeq: number;
  lastType: PramanEvent["type"] | null;
  eventCount: number;
}

export const initialState: CaseState = {
  runId: null,
  listingId: null,
  mode: null,
  llmMode: null,
  startedAt: null,
  listing: null,
  claims: [],
  evidence: [],
  evidenceSeq: {},
  verdicts: {},
  steps: [],
  photoReads: [],
  photoPrint: {},
  registry: [],
  rules: {},
  activeClaimId: null,
  touched: {},
  scan: null,
  ledger: null,
  finished: null,
  error: null,
  lastSeq: 0,
  batchFromSeq: 0,
  lastType: null,
  eventCount: 0,
};

/** Events that close an open Scan or Ledger overlay: the agent has moved on. */
function movesOn(type: PramanEvent["type"]): boolean {
  return type === "step" || type === "verdict" || type === "claims" || type === "run_finished" || type === "error";
}

export function reduce(state: CaseState, event: PramanEvent): CaseState {
  // Live streams can repeat events after a reconnect; the order is the seq.
  if (event.seq <= state.lastSeq) return state;
  let s: CaseState = {
    ...state,
    lastSeq: event.seq,
    lastType: event.type,
    eventCount: state.eventCount + 1,
  };
  if (movesOn(event.type)) {
    if (s.scan) s.scan = null;
    if (s.ledger) s.ledger = null;
  }

  switch (event.type) {
    case "run_started": {
      const d = event.data;
      s = { ...s, runId: d.run_id, listingId: d.listing_id, mode: d.mode, llmMode: d.llm_mode, startedAt: d.started_at };
      break;
    }
    case "listing":
      s = { ...s, listing: event.data, listingId: s.listingId ?? event.data.id };
      break;
    case "claims": {
      const byId = new Map(s.claims.map((c) => [c.id, c] as const));
      for (const c of event.data.claims) byId.set(c.id, c);
      // Keep first-seen order, append new ids in the order they arrive.
      const order = s.claims.map((c) => c.id);
      for (const c of event.data.claims) if (!order.includes(c.id)) order.push(c.id);
      s = { ...s, claims: order.map((id) => byId.get(id)).filter((c): c is Claim => c !== undefined) };
      break;
    }
    case "step": {
      const row: StepRow = { ...event.data, seq: event.seq, t_ms: event.t_ms };
      const cid = event.data.claim_id;
      s = {
        ...s,
        steps: [...s.steps, row],
        activeClaimId: cid ?? s.activeClaimId,
        touched: cid && !s.touched[cid] ? { ...s.touched, [cid]: true } : s.touched,
      };
      break;
    }
    case "photo_read": {
      const row: PhotoReadRow = { ...event.data, seq: event.seq };
      const print = { ...s.photoPrint };
      for (const p of event.data.photos) print[p.index] = [...(print[p.index] ?? []), ...p.items];
      s = { ...s, photoReads: [...s.photoReads, row], photoPrint: print, scan: { seq: event.seq, read: row } };
      break;
    }
    case "registry_lookup": {
      const row: RegistryRow = { ...event.data, seq: event.seq };
      s = { ...s, registry: [...s.registry, row], ledger: { seq: event.seq, lookup: row } };
      break;
    }
    case "evidence": {
      const e = event.data;
      const i = s.evidence.findIndex((x) => x.id === e.id);
      const evidence = i >= 0 ? s.evidence.map((x, j) => (j === i ? e : x)) : [...s.evidence, e];
      s = {
        ...s,
        evidence,
        evidenceSeq: i >= 0 ? s.evidenceSeq : { ...s.evidenceSeq, [e.id]: event.seq },
      };
      break;
    }
    case "verdict": {
      const v = event.data;
      const prev = s.verdicts[v.claim_id];
      const seq = prev && prev.label === v.label ? prev.seq : event.seq;
      const rules = { ...s.rules };
      for (const r of v.rules ?? []) rules[r.id] = r;
      s = { ...s, verdicts: { ...s.verdicts, [v.claim_id]: { ...v, seq } }, rules };
      break;
    }
    case "run_finished":
      s = { ...s, finished: event.data };
      break;
    case "error":
      s = { ...s, error: event.data };
      break;
  }
  return s;
}

export function reduceAll(events: readonly PramanEvent[], from: CaseState = initialState): CaseState {
  let s = from;
  for (const e of events) s = reduce(s, e);
  return s === from ? s : { ...s, batchFromSeq: from.lastSeq };
}

/** Did this arrive in the latest release batch (so it should animate in)? */
export function isFresh(state: CaseState, seq: number): boolean {
  return seq > state.batchFromSeq;
}

// ---------------------------------------------------------------------------
// Selectors

export type ClaimStatus = "waiting" | "active" | "decided";

export function claimStatus(state: CaseState, claimId: string): ClaimStatus {
  if (state.verdicts[claimId]) return "decided";
  if (state.activeClaimId === claimId && isWorking(state)) return "active";
  return "waiting";
}

export function isWorking(state: CaseState): boolean {
  return state.runId !== null && state.finished === null && state.error === null;
}

/** Model calls so far: the run's total once finished, else steps that used tokens. */
export function modelCalls(state: CaseState): number {
  if (state.finished) return state.finished.llm_calls;
  return state.steps.filter((st) => (st.tokens_in ?? 0) > 0).length;
}

export function photosRead(state: CaseState): Set<number> {
  const out = new Set<number>();
  for (const r of state.photoReads) for (const p of r.photos) out.add(p.index);
  return out;
}

export function evidenceForClaim(state: CaseState, claimId: string): Evidence[] {
  return state.evidence.filter((e) => e.claim_id === claimId);
}

export function verdictCounts(state: CaseState): Partial<Record<Verdict["label"], number>> {
  const out: Partial<Record<Verdict["label"], number>> = {};
  for (const v of Object.values(state.verdicts)) out[v.label] = (out[v.label] ?? 0) + 1;
  return out;
}
