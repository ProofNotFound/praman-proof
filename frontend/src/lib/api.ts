// Talking to our own backend (TRD §15.2) or, when it isn't there, to the bundled recordings
// (DESIGN §8). No other network requests: every URL here is relative to our own origin.

import {
  EVENT_TYPES,
  validateEvent,
  validateIndex,
  validateRecording,
  type LlmMode,
  type Mode,
  type PramanEvent,
  type Recording,
  type RecordingIndexEntry,
  type Verdict,
  type VerdictLabel,
  type Claim,
} from "./events";
import { parseReview, parseReviews, type Review, type Role } from "./review";
import { parsePacks, type RulePack } from "./packs";
import { validateUrlKeys, type DemoUrlKey } from "./urls";

export interface Health {
  ok: boolean;
  llm_mode: LlmMode;
  anonymise: boolean;
  cpcb_list_date: string;
  cpcb_rows?: number;
  version: string;
  /** A page that isn't a recorded case can be checked on this server (older servers omit it). */
  live_checks?: boolean;
  /** Public server: checks beyond the recorded cases need the access code. */
  needs_access_code?: boolean;
  /** How a reviewer signs here: named keys, the demo role switch, or not at all (older servers omit it). */
  reviewer_access?: ReviewerAccess;
}

export type ReviewerAccess = "key" | "role" | "off";

/** How this backend lets a reviewer decide and sign; recordings keep the role switch in the tab. */
export function reviewerAccess(b: Backend | null): ReviewerAccess {
  return b?.kind === "live" ? (b.health.reviewer_access ?? "role") : "role";
}

export type Backend = { kind: "live"; health: Health } | { kind: "recording"; reason: string };

export const HEALTH_TIMEOUT_MS = 1500;
const BASE = import.meta.env.BASE_URL ?? "/";

/** Recordings use paths relative to the app ("demo/photos/L14/7.jpg"); the API uses "/api/…". */
export function assetUrl(url: string): string {
  if (url.startsWith("/") || /^[a-z]+:/i.test(url)) return url;
  return `${BASE}${url}`;
}

async function getJson(url: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = "";
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail || `The server answered ${res.status}.`);
  }
  return res.json();
}

const ACCESS_CODE_KEY = "praman.accessCode";

export function getAccessCode(): string {
  try {
    return sessionStorage.getItem(ACCESS_CODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAccessCode(code: string): void {
  try {
    sessionStorage.setItem(ACCESS_CODE_KEY, code.trim());
  } catch {
    /* storage blocked: the code is asked for again */
  }
}

const REVIEWER_KEY_KEY = "praman.reviewerKey";

export function getReviewerKey(): string {
  try {
    return sessionStorage.getItem(REVIEWER_KEY_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setReviewerKey(key: string): void {
  try {
    sessionStorage.setItem(REVIEWER_KEY_KEY, key.trim());
  } catch {
    /* storage blocked: the key is asked for again */
  }
}

/** The access code header for requests that start a live check (sent only when one is set). */
export function accessHeaders(): Record<string, string> {
  const code = getAccessCode();
  return code ? { "X-Access-Code": code } : {};
}

/** Whether this backend can check a page that isn't a recorded case. */
export function canCheckNewPages(b: Backend | null): boolean {
  if (b?.kind !== "live") return false;
  return b.health.live_checks ?? b.health.llm_mode === "live";
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

// ---------------------------------------------------------------------------
// Health: decides the mode for the whole session.

export async function detectBackend(timeoutMs = HEALTH_TIMEOUT_MS): Promise<Backend> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const body = await getJson("/api/health", { signal: ctl.signal, cache: "no-store" });
    if (isRecord(body) && body.ok === true && typeof body.llm_mode === "string") {
      return { kind: "live", health: body as unknown as Health };
    }
    return { kind: "recording", reason: "The Praman server answered, but not as expected." };
  } catch {
    return { kind: "recording", reason: "Can't reach the Praman server. Playing the recorded cases instead." };
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Case ids: "L14.agent" names a case file (a listing and a mode); anything else is a run id.

/** `bundled`: play the recording shipped with the app even when the server is up ("L14.agent.rec",
 * the fallback when a live run fails on stage). */
export type CaseRef = { kind: "file"; listingId: string; mode: Mode; bundled?: boolean } | { kind: "run"; runId: string };

export function parseCaseId(id: string): CaseRef {
  const m = /^([A-Za-z0-9_-]+)\.(agent|baseline)(\.rec)?$/.exec(id);
  if (m?.[1] && m[2]) return { kind: "file", listingId: m[1], mode: m[2] as Mode, ...(m[3] ? { bundled: true } : {}) };
  return { kind: "run", runId: id };
}

export const fileCaseId = (listingId: string, mode: Mode): string => `${listingId}.${mode}`;
export const recordedCaseId = (listingId: string, mode: Mode): string => `${listingId}.${mode}.rec`;

/** Whether the app ships a recording of this listing in this mode. */
export async function hasRecording(listingId: string, mode: Mode): Promise<boolean> {
  try {
    return (await loadIndex()).some((e) => e.listing_id === listingId && e.mode === mode);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Bundled recordings (public/demo/)

let indexCache: Promise<RecordingIndexEntry[]> | null = null;

export function loadIndex(): Promise<RecordingIndexEntry[]> {
  indexCache ??= getJson(assetUrl("demo/index.json")).then((x) => {
    const r = validateIndex(x);
    if (!r.ok) throw new Error(`The recordings index is malformed (${r.error}).`);
    return r.value;
  });
  indexCache.catch(() => (indexCache = null));
  return indexCache;
}

const recordingCache = new Map<string, Promise<Recording>>();

export function loadRecording(listingId: string, mode: Mode): Promise<Recording> {
  const key = fileCaseId(listingId, mode);
  let p = recordingCache.get(key);
  if (!p) {
    p = loadIndex().then(async (index) => {
      const entry = index.find((e) => e.listing_id === listingId && e.mode === mode);
      if (!entry) throw new Error(`There's no recording of ${listingId} in ${modeName(mode)} mode.`);
      return parseRecording(await getJson(assetUrl(`demo/${entry.file}`)));
    });
    p.catch(() => recordingCache.delete(key));
    recordingCache.set(key, p);
  }
  return p;
}

export function parseRecording(x: unknown): Recording {
  const r = validateRecording(x);
  if (!r.ok) throw new Error(`The recording doesn't follow the format (${r.error}).`);
  return r.value;
}

export const modeName = (m: Mode): string => (m === "agent" ? "agent" : "text-only");

let urlKeysCache: Promise<DemoUrlKey[]> | null = null;

/** URL keys of the bundled demo cases (public/demo/urls.json); empty when the file is missing. */
export function loadUrlKeys(): Promise<DemoUrlKey[]> {
  urlKeysCache ??= getJson(assetUrl("demo/urls.json"))
    .then(validateUrlKeys)
    .catch(() => []);
  return urlKeysCache;
}

// ---------------------------------------------------------------------------
// Live API

export interface ListingSummary {
  id: string;
  title: string;
  category: string;
  demo_role: string | null;
  photo_count: number;
  cached: boolean;
}

export async function fetchListings(): Promise<ListingSummary[]> {
  const body = await getJson("/api/listings");
  return Array.isArray(body) ? (body as ListingSummary[]) : [];
}

export async function startRun(req: {
  listing_id?: string;
  url?: string;
  scan_id?: string;
  product?: number;
  mode: Mode;
}): Promise<string> {
  const body = await getJson("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...accessHeaders() },
    body: JSON.stringify(req),
  });
  if (isRecord(body) && typeof body.run_id === "string") return body.run_id;
  throw new Error("The server didn't return a run id.");
}

export async function fetchRunRecording(runId: string): Promise<Recording> {
  return parseRecording(await getJson(`/api/runs/${encodeURIComponent(runId)}/recording`));
}

export interface RunInfo {
  id: string;
  listing_id: string;
  mode: Mode;
  status?: string;
  approved_by?: string | null;
  approved_at?: string | null;
}

/** What a run was checked with (rulebook, prompts, model, code), stored with the run. */
export interface Provenance {
  praman: string;
  commit: string;
  rules_version: string | null;
  rules_as_of: string | null;
  prompts: string;
  model: string;
  live_model: string | null;
  llm_mode: string;
  cpcb_list_date: string;
}

/** Tamper evidence: the review hash chain and the sign-off fingerprint, checked by the server. */
export interface Audit {
  provenance: Provenance | null;
  reviews: number;
  reviews_intact: boolean;
  fingerprint: string | null;
  fingerprint_matches: boolean | null;
}

const str = (x: unknown): string => (typeof x === "string" ? x : "");
const strOrNull = (x: unknown): string | null => (typeof x === "string" ? x : null);

export function parseAudit(x: unknown): Audit | null {
  if (!isRecord(x)) return null;
  const p = x.provenance;
  return {
    provenance: isRecord(p)
      ? {
          praman: str(p.praman),
          commit: str(p.commit),
          rules_version: strOrNull(p.rules_version),
          rules_as_of: strOrNull(p.rules_as_of),
          prompts: str(p.prompts),
          model: str(p.model),
          live_model: strOrNull(p.live_model),
          llm_mode: str(p.llm_mode),
          cpcb_list_date: str(p.cpcb_list_date),
        }
      : null,
    reviews: typeof x.reviews === "number" ? x.reviews : 0,
    reviews_intact: x.reviews_intact === true,
    fingerprint: strOrNull(x.fingerprint),
    fingerprint_matches: typeof x.fingerprint_matches === "boolean" ? x.fingerprint_matches : null,
  };
}

/** One plain line: what the run was checked with (the same words as the exported report). */
export function provenanceLine(p: Provenance | null): string {
  if (!p) return "Checked with: not recorded (this run predates provenance records).";
  const model = p.llm_mode === "live" && p.live_model ? p.live_model : p.model;
  return (
    `Checked with: rulebook ${p.rules_version ?? "?"} (${p.rules_as_of ?? "?"}) · prompts ${p.prompts} · model ${model} · ` +
    `CPCB list ${p.cpcb_list_date} · Praman ${p.praman}${p.commit ? ` @ ${p.commit}` : ""}.`
  );
}

export async function fetchRun(runId: string): Promise<{ run: RunInfo; reviews: Review[]; audit: Audit | null } | null> {
  const body = await getJson(`/api/runs/${encodeURIComponent(runId)}`);
  if (!isRecord(body) || !isRecord(body.run)) return null;
  return { run: body.run as unknown as RunInfo, reviews: parseReviews(body.reviews), audit: parseAudit(body.audit) };
}

/** Deciding a claim and signing a report are reviewer actions; the server checks the role, or the
 * reviewer's key when it has named reviewers (and then signs with the key's name). */
const roleHeaders = (role: Role): Record<string, string> => {
  const key = getReviewerKey();
  return { "Content-Type": "application/json", "X-Praman-Role": role, ...(key ? { "X-Reviewer-Key": key } : {}) };
};

export async function approveRun(runId: string, name: string, role: Role): Promise<RunInfo> {
  const body = await getJson(`/api/runs/${encodeURIComponent(runId)}/approve`, {
    method: "POST",
    headers: roleHeaders(role),
    body: JSON.stringify({ name }),
  });
  return body as RunInfo;
}

export async function reviewClaim(
  runId: string,
  claimId: string,
  req: { name: string; decision: Review["decision"]; label?: VerdictLabel; reason?: string },
  role: Role,
): Promise<Review> {
  const body = await getJson(`/api/runs/${encodeURIComponent(runId)}/reviews/${encodeURIComponent(claimId)}`, {
    method: "POST",
    headers: roleHeaders(role),
    body: JSON.stringify(req),
  });
  const r = parseReview(body);
  if (!r) throw new Error("The server's answer to the review wasn't understood.");
  return r;
}

export const reportMdUrl = (runId: string): string => `/api/runs/${encodeURIComponent(runId)}/report.md`;

export interface CompareSide {
  run_id: string;
  claims: Claim[];
  verdicts: Verdict[];
}
export interface ComparePair {
  agent_claim_id: string;
  baseline_claim_id: string | null;
  quote: string;
  agent: string | null;
  baseline: string | null;
  differs: boolean;
}
export interface CompareResponse {
  listing_id: string;
  agent: CompareSide | null;
  baseline: CompareSide | null;
  pairs: ComparePair[];
}

export async function fetchCompare(listingId: string): Promise<CompareResponse> {
  return (await getJson(`/api/compare/${encodeURIComponent(listingId)}`)) as CompareResponse;
}

/** The latest run of a listing in a mode, or a fresh one when there is none. */
export async function resolveRun(listingId: string, mode: Mode): Promise<string> {
  try {
    const cmp = await fetchCompare(listingId);
    const side = cmp[mode];
    if (side?.run_id) return side.run_id;
  } catch {
    /* fall through to a new run */
  }
  return startRun({ listing_id: listingId, mode });
}

// ---------------------------------------------------------------------------
// SSE: /api/runs/{id}/events. Named events (one per type); closes after run_finished or error.

export interface StreamHandlers {
  onEvent: (e: PramanEvent) => void;
  onEnd: () => void;
  onError: (message: string) => void;
}

export function streamRun(runId: string, h: StreamHandlers): () => void {
  let lastSeq = 0;
  let closed = false;
  let es: EventSource | null = null;
  let retries = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const close = () => {
    closed = true;
    es?.close();
    if (retryTimer) clearTimeout(retryTimer);
  };

  const onMessage = (msg: MessageEvent<string>) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(msg.data);
    } catch {
      return;
    }
    const r = validateEvent(parsed);
    if (!r.ok) {
      console.warn("Praman: dropped an event that doesn't follow the contract:", r.error);
      return;
    }
    retries = 0;
    if (r.value.seq <= lastSeq) return;
    lastSeq = r.value.seq;
    h.onEvent(r.value);
    if (r.value.type === "run_finished" || r.value.type === "error") {
      close();
      h.onEnd();
    }
  };

  const open = () => {
    if (closed) return;
    const q = lastSeq > 0 ? `?last_event_id=${lastSeq}` : "";
    es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events${q}`);
    for (const t of EVENT_TYPES) es.addEventListener(t, onMessage as EventListener);
    es.onerror = () => {
      if (closed) return;
      // The browser retries on its own while CONNECTING; reopen ourselves once it gives up.
      if (es?.readyState === EventSource.CLOSED) {
        retries += 1;
        if (retries > 5) {
          close();
          h.onError("Lost the connection to the Praman server.");
          return;
        }
        retryTimer = setTimeout(open, Math.min(8000, 500 * 2 ** retries));
      }
    };
  };

  open();
  return close;
}

// ---------------------------------------------------------------------------
// Evaluation (TRD §17 step 7)

export interface ModeMetrics {
  n_labelled: number;
  matched: number;
  agree: number;
  agreement: number;
  agreement_all: number;
  false_backed: number;
  missed: number;
  model_calls: number;
  cost_inr: number;
  seconds: number;
  by_verdict: Record<string, { expected: number; predicted: number; agree: number }>;
  /** our label → this mode's verdict (or "Not found") → count */
  confusion?: Record<string, Record<string, number>>;
  per_listing_avg?: { model_calls: number; cost_inr: number; seconds: number };
}

export interface RunStats {
  model_calls: number;
  cost_inr: number;
  seconds: number;
  failed?: boolean;
}

export interface EvalSplit {
  /** "not_run": holdout listings wait for the one final run (eval/run_eval.py --holdout) */
  status?: "done" | "not_run";
  n_labelled?: number;
  /** labels a person checked with eval/hand_check.py */
  hand_checked?: number;
  per_listing?: { listing_id: string; agent: RunStats; baseline: RunStats }[];
  listings: string[];
  modes: { agent?: ModeMetrics; baseline?: ModeMetrics };
  proof_only_agent: { listing_id: string; claim_ref: string; quote: string; label: string; sources: string[]; run_id: string }[];
  disagreements: {
    listing_id: string;
    claim_ref: string;
    quote: string;
    expected: string;
    agent: string | null;
    baseline: string | null;
    agent_run_id: string;
    baseline_run_id: string;
  }[];
}

export type EvalResult =
  | { status: "pending"; reason?: string }
  | {
      status: "done";
      eval_id: string;
      generated_at: string;
      llm_mode: string;
      labels_file: string;
      labels_note?: string | null;
      splits: Partial<Record<"dev" | "holdout", EvalSplit>>;
    };

export async function fetchRulePacks(backend: Backend): Promise<RulePack[]> {
  return parsePacks(await getJson(backend.kind === "live" ? "/api/rule-packs" : assetUrl("demo/rule_packs.json")));
}

export async function fetchEval(backend: Backend): Promise<EvalResult> {
  const body = await getJson(backend.kind === "live" ? "/api/eval" : assetUrl("demo/eval.json"));
  if (isRecord(body) && body.status === "done" && isRecord(body.splits)) return body as unknown as EvalResult;
  return { status: "pending", reason: isRecord(body) && typeof body.reason === "string" ? body.reason : undefined };
}
