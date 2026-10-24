// Store scan (TRD §15.7): rank a store's product pages by how much their green claims need
// checking. Code only, no model calls: triage, not a verdict. Live scans come from
// /api/scans; without a backend the app plays public/demo/scan_demo.json.

import { accessHeaders, assetUrl } from "./api";

export type Band = "high" | "medium" | "low" | "none";

export interface TriageTerm {
  term: string;
  kind: "vague" | "specific" | "comparative" | "future";
  rule_ids: string[];
  weight: number;
  snippet: string;
}

export interface ProofSignal {
  kind: "cpcb_code" | "standard" | "certificate_number" | "certifier" | "company_mark" | "certificate_link";
  text: string;
  weight: number;
}

export interface TriageRow {
  product: number;
  rank: number;
  title: string;
  url: string;
  score: number;
  band: Band;
  terms: TriageTerm[];
  proof: ProofSignal[];
  reasons: string[];
  listing_id: string | null;
  error: string | null;
}

export interface ScanResult {
  id: string;
  status: "running" | "finished" | "error";
  store: string;
  store_url: string;
  source: "shopify" | "sitemap" | null;
  total: number;
  done: number;
  started_at: string;
  finished_at: string | null;
  message: string | null;
  label: string;
  model_calls: number;
  /** the rule pack the pages were triaged with (older servers and the recording omit it) */
  pack?: string;
  rows: TriageRow[];
  /** set on the bundled recording */
  recorded_at?: string;
  synthetic?: boolean;
}

export const BAND_LABEL: Record<Band, string> = {
  high: "Check first",
  medium: "Check soon",
  low: "Lower",
  none: "No claim terms",
};

export const PROOF_LABEL: Record<ProofSignal["kind"], string> = {
  cpcb_code: "CPCB code",
  standard: "Standard",
  certificate_number: "Certificate no.",
  certifier: "Certifier",
  company_mark: "Company mark",
  certificate_link: "Certificates link",
};

// ---------------------------------------------------------------------------
// Validation: small guards, so a malformed answer fails with a path instead of a blank screen.

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

const BANDS: readonly Band[] = ["high", "medium", "low", "none"];

function validRow(x: unknown): x is TriageRow {
  return (
    isRecord(x) &&
    Number.isInteger(x.product) &&
    Number.isInteger(x.rank) &&
    typeof x.title === "string" &&
    typeof x.url === "string" &&
    Number.isInteger(x.score) &&
    typeof x.band === "string" &&
    (BANDS as readonly string[]).includes(x.band) &&
    Array.isArray(x.terms) &&
    x.terms.every((t) => isRecord(t) && typeof t.term === "string" && Array.isArray(t.rule_ids)) &&
    Array.isArray(x.proof) &&
    x.proof.every((p) => isRecord(p) && typeof p.text === "string" && typeof p.kind === "string") &&
    Array.isArray(x.reasons) &&
    x.reasons.every((r) => typeof r === "string") &&
    (x.listing_id === null || typeof x.listing_id === "string") &&
    (x.error === null || typeof x.error === "string")
  );
}

export function validateScan(x: unknown): { ok: true; value: ScanResult } | { ok: false; error: string } {
  if (!isRecord(x)) return { ok: false, error: "scan: expected an object" };
  for (const key of ["id", "store", "store_url", "started_at", "label"] as const) {
    if (typeof x[key] !== "string") return { ok: false, error: `scan.${key}: expected a string` };
  }
  if (!["running", "finished", "error"].includes(String(x.status))) return { ok: false, error: "scan.status: unknown" };
  for (const key of ["total", "done", "model_calls"] as const) {
    if (!Number.isInteger(x[key])) return { ok: false, error: `scan.${key}: expected an integer` };
  }
  if (!Array.isArray(x.rows)) return { ok: false, error: "scan.rows: expected an array" };
  const bad = x.rows.findIndex((r) => !validRow(r));
  if (bad >= 0) return { ok: false, error: `scan.rows[${bad}]: malformed` };
  return { ok: true, value: x as unknown as ScanResult };
}

async function getJson(url: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(url, init);
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  if (!res.ok) {
    const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : `The server answered ${res.status}.`;
    throw new Error(detail);
  }
  return body;
}

function parse(x: unknown): ScanResult {
  const r = validateScan(x);
  if (!r.ok) throw new Error(`The scan doesn't follow the format (${r.error}).`);
  return r.value;
}

/** Start a scan; `pack` picks the rulebook the pages are triaged with (green claims by default). */
export async function startScan(url: string, pack = "green_claims"): Promise<string> {
  const body = await getJson("/api/scans", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...accessHeaders() },
    body: JSON.stringify({ url, pack }),
  });
  if (isRecord(body) && typeof body.scan_id === "string") return body.scan_id;
  throw new Error("The server didn't return a scan id.");
}

export async function fetchScan(id: string): Promise<ScanResult> {
  return parse(await getJson(`/api/scans/${encodeURIComponent(id)}`));
}

let demoCache: Promise<ScanResult> | null = null;

export function loadDemoScan(): Promise<ScanResult> {
  demoCache ??= getJson(assetUrl("demo/scan_demo.json")).then(parse);
  demoCache.catch(() => (demoCache = null));
  return demoCache;
}

export function bandCounts(rows: readonly TriageRow[]): Record<Band, number> {
  const out: Record<Band, number> = { high: 0, medium: 0, low: 0, none: 0 };
  for (const r of rows) out[r.band] += 1;
  return out;
}
