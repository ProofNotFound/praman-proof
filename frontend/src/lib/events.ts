// The event contract (TRD §15.3) and the recording format (TRD §15.4), mirrored by hand from
// praman/events.py. The TRD table is the source of truth. Optional fields the core added are
// marked optional here; unknown extra fields are allowed (the core may add more).

export type Mode = "agent" | "baseline";
export type LlmMode = "live" | "replay" | "offline";
export type VerdictLabel =
  | "Backed"
  | "Partly backed"
  | "Not backed"
  | "Contradicted"
  | "Needs review"
  | "Not a claim";
export type CoversClaim = "yes" | "partly" | "no" | "contradicts";
export type EvidenceSource = "text" | "photo" | "registry" | "link" | "consistency" | "web";
export type CertScope = "product" | "material" | "ingredient" | "company" | "other" | "unknown";
export type ClaimType = "vague" | "specific" | "comparative" | "future";
export type ClaimScope =
  | "product"
  | "part"
  | "packaging"
  | "process"
  | "disposal"
  | "delivery"
  | "brand"
  | "unclear";
export type Phase = "plan" | "act" | "observe" | "decide";
export type PhotoItemKind = "code" | "certificate" | "composition" | "label" | "claim" | "other";
/** Gemini box_2d convention: [ymin, xmin, ymax, xmax], 0–1000. */
export type Box = [number, number, number, number];

export const VERDICT_LABELS: readonly VerdictLabel[] = [
  "Backed",
  "Partly backed",
  "Not backed",
  "Contradicted",
  "Needs review",
  "Not a claim",
];

export interface RunStartedData {
  run_id: string;
  listing_id: string;
  mode: Mode;
  llm_mode: LlmMode;
  started_at: string;
}

export interface PhotoRef {
  index: number;
  url: string;
  width?: number | null;
  height?: number | null;
}

export interface ListingData {
  id: string;
  title: string;
  store: string | null;
  body_text: string;
  photos: PhotoRef[];
  tags?: string[];
}

export interface Claim {
  id: string;
  quote: string;
  normalised: string;
  type: ClaimType;
  scope: ClaimScope;
  /** "title" | "description" | "tag" | "photo:N" | "n/a" (label checks) */
  location: string;
  is_claim: boolean;
  not_claim_reason?: string | null;
  rule_ids: string[];
  /** Set on a required-label check split from another claim. */
  derived_from?: string | null;
}

export interface ClaimsData {
  claims: Claim[];
}

export interface StepData {
  run_id: string;
  claim_id: string | null;
  n: number;
  phase: Phase;
  tool: string | null;
  summary: string;
  ms: number;
  tokens_in?: number;
  tokens_out?: number;
  payload_preview?: string;
}

export interface PhotoItem {
  text: string;
  kind: PhotoItemKind;
  box_2d: Box | null;
}

export interface PhotoReadPhoto {
  index: number;
  items: PhotoItem[];
}

export interface PhotoReadData {
  photos: PhotoReadPhoto[];
  claim_id?: string | null;
}

export interface RegistryMatch {
  s_no: number;
  name: string;
  state: string;
  type: string;
  validity: string;
  /** 1 certified, 2 not certified */
  table?: number | null;
}

export interface RegistryLookupData {
  claim_id: string | null;
  query: string;
  rows_scanned: number;
  list_date: string;
  match: RegistryMatch | null;
  /** name similarity 0–1 */
  score: number;
}

export interface Conflict {
  a: string;
  b: string;
  b_location?: string | null;
}

/** A QR code on the pack (W4): the domain it links to, and whether Praman opened it. */
export interface QrRef {
  domain: string;
  followed: boolean;
  path?: string | null;
}

export interface Evidence {
  id: string;
  claim_id: string;
  source: EvidenceSource;
  detail: string;
  photo_index?: number | null;
  crop_box?: Box | null;
  covers_claim: CoversClaim;
  certifier?: string | null;
  cert_scope?: CertScope | null;
  kind?: string | null;
  rule_id?: string | null;
  note?: string | null;
  conflict?: Conflict | null;
  qr?: QrRef | null;
}

export interface RuleChip {
  id: string;
  name: string;
  summary: string;
  clause: string;
  source: string;
}

export interface Verdict {
  claim_id: string;
  label: VerdictLabel;
  evidence_ids: string[];
  rule_ids: string[];
  reason: string;
  missing?: string | null;
  rewrite?: string | null;
  sources_searched: string[];
  rules?: RuleChip[];
}

export interface RunFinishedData {
  llm_calls: number;
  tokens_in: number;
  tokens_out: number;
  est_cost_inr: number;
  elapsed_ms: number;
  counts: Record<string, number>;
  cached_calls?: number;
  tool_calls?: number;
  /** true when the model's quota ran out mid-run: claims not yet checked are Needs review */
  quota_reached?: boolean;
}

export interface ErrorData {
  message: string;
  recoverable: boolean;
}

export interface EventDataMap {
  run_started: RunStartedData;
  listing: ListingData;
  claims: ClaimsData;
  step: StepData;
  photo_read: PhotoReadData;
  registry_lookup: RegistryLookupData;
  evidence: Evidence;
  verdict: Verdict;
  run_finished: RunFinishedData;
  error: ErrorData;
}

export type EventType = keyof EventDataMap;
export const EVENT_TYPES: readonly EventType[] = [
  "run_started",
  "listing",
  "claims",
  "step",
  "photo_read",
  "registry_lookup",
  "evidence",
  "verdict",
  "run_finished",
  "error",
];

export type EventOf<T extends EventType> = {
  seq: number;
  t_ms: number;
  run_id: string;
  type: T;
  data: EventDataMap[T];
};

export type PramanEvent = { [T in EventType]: EventOf<T> }[EventType];

export interface Recording {
  format: "praman-recording/1";
  synthetic: boolean;
  listing_id: string;
  mode: Mode;
  title: string;
  recorded_at: string;
  events: PramanEvent[];
  run_id?: string;
  llm_mode?: LlmMode;
}

export interface RecordingIndexEntry {
  listing_id: string;
  mode: Mode;
  title: string;
  file: string;
  claim_count: number;
  synthetic: boolean;
}

// ---------------------------------------------------------------------------
// Runtime validator: small hand-written guards that report the path of the first problem.

export type Result<T> = { ok: true; value: T } | { ok: false; error: string };
type Guard<T> = (x: unknown, path: string) => Result<T>;

const ok = <T>(value: T): Result<T> => ({ ok: true, value });
const fail = <T>(path: string, want: string, got: unknown): Result<T> => ({
  ok: false,
  error: `${path}: expected ${want}, got ${got === null ? "null" : Array.isArray(got) ? "array" : typeof got}`,
});

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

const str: Guard<string> = (x, p) => (typeof x === "string" ? ok(x) : fail(p, "string", x));
const int: Guard<number> = (x, p) => (Number.isInteger(x) ? ok(x as number) : fail(p, "integer", x));
const num: Guard<number> = (x, p) =>
  typeof x === "number" && Number.isFinite(x) ? ok(x) : fail(p, "number", x);
const bool: Guard<boolean> = (x, p) => (typeof x === "boolean" ? ok(x) : fail(p, "boolean", x));

function oneOf<T extends string>(values: readonly T[]): Guard<T> {
  return (x, p) =>
    typeof x === "string" && (values as readonly string[]).includes(x)
      ? ok(x as T)
      : { ok: false, error: `${p}: expected one of ${values.join(", ")}, got ${JSON.stringify(x)}` };
}

function nullable<T>(g: Guard<T>): Guard<T | null> {
  return (x, p) => (x === null ? ok(null) : g(x, p));
}

function arrayOf<T>(g: Guard<T>): Guard<T[]> {
  return (x, p) => {
    if (!Array.isArray(x)) return fail(p, "array", x);
    const out: T[] = [];
    for (let i = 0; i < x.length; i++) {
      const r = g(x[i], `${p}[${i}]`);
      if (!r.ok) return r;
      out.push(r.value);
    }
    return ok(out);
  };
}

const box: Guard<Box> = (x, p) => {
  const r = arrayOf(num)(x, p);
  if (!r.ok) return r;
  return r.value.length === 4 ? ok(r.value as Box) : fail(p, "4 numbers", x);
};

type Shape<T> = { [K in keyof T]-?: Guard<T[K]> };

/** Required keys must be present; keys listed in `optional` may be missing or undefined. */
function object<T>(shape: Shape<T>, optional: readonly (keyof T)[] = []): Guard<T> {
  return (x, p) => {
    if (!isRecord(x)) return fail(p, "object", x);
    for (const key of Object.keys(shape) as (keyof T & string)[]) {
      const v = x[key];
      if (v === undefined) {
        if (optional.includes(key)) continue;
        return { ok: false, error: `${p}.${key}: missing` };
      }
      const r = shape[key](v, `${p}.${key}`);
      if (!r.ok) return r;
    }
    return ok(x as T);
  };
}

const optStr = nullable(str);

const runStarted = object<RunStartedData>({
  run_id: str,
  listing_id: str,
  mode: oneOf<Mode>(["agent", "baseline"]),
  llm_mode: oneOf<LlmMode>(["live", "replay", "offline"]),
  started_at: str,
});

const photoRef = object<PhotoRef>(
  { index: int, url: str, width: nullable(int), height: nullable(int) },
  ["width", "height"],
);

const listing = object<ListingData>(
  {
    id: str,
    title: str,
    store: optStr,
    body_text: str,
    photos: arrayOf(photoRef),
    tags: arrayOf(str),
  },
  ["tags"],
);

const claim = object<Claim>(
  {
    id: str,
    quote: str,
    normalised: str,
    type: oneOf<ClaimType>(["vague", "specific", "comparative", "future"]),
    scope: oneOf<ClaimScope>([
      "product",
      "part",
      "packaging",
      "process",
      "disposal",
      "delivery",
      "brand",
      "unclear",
    ]),
    location: str,
    is_claim: bool,
    not_claim_reason: optStr,
    rule_ids: arrayOf(str),
    derived_from: optStr,
  },
  ["not_claim_reason", "derived_from"],
);

const claims = object<ClaimsData>({ claims: arrayOf(claim) });

const step = object<StepData>(
  {
    run_id: str,
    claim_id: optStr,
    n: int,
    phase: oneOf<Phase>(["plan", "act", "observe", "decide"]),
    tool: optStr,
    summary: str,
    ms: int,
    tokens_in: int,
    tokens_out: int,
    payload_preview: (x, p) => {
      const r = str(x, p);
      if (!r.ok) return r;
      return r.value.length <= 300 ? r : { ok: false, error: `${p}: longer than 300 characters` };
    },
  },
  ["tokens_in", "tokens_out", "payload_preview"],
);

const photoItem = object<PhotoItem>({
  text: str,
  kind: oneOf<PhotoItemKind>(["code", "certificate", "composition", "label", "claim", "other"]),
  box_2d: nullable(box),
});

const photoRead = object<PhotoReadData>(
  {
    photos: arrayOf(object<PhotoReadPhoto>({ index: int, items: arrayOf(photoItem) })),
    claim_id: optStr,
  },
  ["claim_id"],
);

const registryMatch = object<RegistryMatch>(
  { s_no: int, name: str, state: str, type: str, validity: str, table: nullable(int) },
  ["table"],
);

const registryLookup = object<RegistryLookupData>({
  claim_id: optStr,
  query: str,
  rows_scanned: int,
  list_date: str,
  match: nullable(registryMatch),
  score: (x, p) => {
    const r = num(x, p);
    if (!r.ok) return r;
    return r.value >= 0 && r.value <= 1 ? r : { ok: false, error: `${p}: score must be 0–1` };
  },
});

const conflict = object<Conflict>({ a: str, b: str, b_location: optStr }, ["b_location"]);

const qrRef = object<QrRef>({ domain: str, followed: bool, path: optStr }, ["path"]);

const evidence = object<Evidence>(
  {
    id: str,
    claim_id: str,
    source: oneOf<EvidenceSource>(["text", "photo", "registry", "link", "consistency", "web"]),
    detail: str,
    photo_index: nullable(int),
    crop_box: nullable(box),
    covers_claim: oneOf<CoversClaim>(["yes", "partly", "no", "contradicts"]),
    certifier: optStr,
    cert_scope: nullable(
      oneOf<CertScope>(["product", "material", "ingredient", "company", "other", "unknown"]),
    ),
    kind: optStr,
    rule_id: optStr,
    note: optStr,
    conflict: nullable(conflict),
    qr: nullable(qrRef),
  },
  ["photo_index", "crop_box", "certifier", "cert_scope", "kind", "rule_id", "note", "conflict", "qr"],
);

const ruleChip = object<RuleChip>({ id: str, name: str, summary: str, clause: str, source: str });

const verdict = object<Verdict>(
  {
    claim_id: str,
    label: oneOf<VerdictLabel>(VERDICT_LABELS),
    evidence_ids: arrayOf(str),
    rule_ids: arrayOf(str),
    reason: str,
    missing: optStr,
    rewrite: optStr,
    sources_searched: arrayOf(str),
    rules: arrayOf(ruleChip),
  },
  ["missing", "rewrite", "rules"],
);

const runFinished = object<RunFinishedData>(
  {
    llm_calls: int,
    tokens_in: int,
    tokens_out: int,
    est_cost_inr: num,
    elapsed_ms: int,
    counts: (x, p) => {
      if (!isRecord(x)) return fail(p, "object", x);
      for (const [k, v] of Object.entries(x)) {
        if (!Number.isInteger(v)) return fail(`${p}.${k}`, "integer", v);
      }
      return ok(x as Record<string, number>);
    },
    cached_calls: int,
    tool_calls: int,
    quota_reached: bool,
  },
  ["cached_calls", "tool_calls", "quota_reached"],
);

const errorData = object<ErrorData>({ message: str, recoverable: bool });

const DATA_GUARDS: { [T in EventType]: Guard<EventDataMap[T]> } = {
  run_started: runStarted,
  listing,
  claims,
  step,
  photo_read: photoRead,
  registry_lookup: registryLookup,
  evidence,
  verdict,
  run_finished: runFinished,
  error: errorData,
};

const ENVELOPE_KEYS = new Set(["seq", "t_ms", "type", "run_id", "data"]);

export function validateEvent(x: unknown, path = "event"): Result<PramanEvent> {
  if (!isRecord(x)) return fail(path, "object", x);
  for (const key of Object.keys(x)) {
    if (!ENVELOPE_KEYS.has(key)) return { ok: false, error: `${path}.${key}: unexpected key` };
  }
  for (const [key, g] of [
    ["seq", int],
    ["t_ms", int],
    ["run_id", str],
  ] as const) {
    const r = g(x[key], `${path}.${key}`);
    if (!r.ok) return r;
  }
  const type = oneOf(EVENT_TYPES)(x.type, `${path}.type`);
  if (!type.ok) return type;
  const data = DATA_GUARDS[type.value](x.data, `${path}.data`);
  if (!data.ok) return data;
  return ok(x as unknown as PramanEvent);
}

export function validateRecording(x: unknown): Result<Recording> {
  if (!isRecord(x)) return fail("recording", "object", x);
  if (x.format !== "praman-recording/1") {
    return { ok: false, error: `recording.format: expected "praman-recording/1"` };
  }
  const head = object<Omit<Recording, "events" | "format" | "run_id" | "llm_mode">>({
    synthetic: bool,
    listing_id: str,
    mode: oneOf<Mode>(["agent", "baseline"]),
    title: str,
    recorded_at: str,
  })(x, "recording");
  if (!head.ok) return head;
  if (!Array.isArray(x.events)) return fail("recording.events", "array", x.events);
  let lastSeq = 0;
  for (let i = 0; i < x.events.length; i++) {
    const r = validateEvent(x.events[i], `recording.events[${i}]`);
    if (!r.ok) return r;
    if (r.value.seq <= lastSeq) {
      return { ok: false, error: `recording.events[${i}].seq: not increasing` };
    }
    lastSeq = r.value.seq;
  }
  return ok(x as unknown as Recording);
}

export function validateIndex(x: unknown): Result<RecordingIndexEntry[]> {
  return arrayOf(
    object<RecordingIndexEntry>({
      listing_id: str,
      mode: oneOf<Mode>(["agent", "baseline"]),
      title: str,
      file: str,
      claim_count: int,
      synthetic: bool,
    }),
  )(x, "index");
}
