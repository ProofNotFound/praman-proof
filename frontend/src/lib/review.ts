// Human review (governance): roles, a reviewer's decision per claim, the sign-off gate and the
// decision log. Live mode keeps decisions on the server; recording mode keeps them in this tab.

import { VERDICT_LABELS, type VerdictLabel } from "./events";
import type { CaseState } from "./reducer";

export type Role = "analyst" | "reviewer";

export interface Review {
  claim_id: string;
  decision: "agree" | "change";
  label: VerdictLabel;
  ai_label: VerdictLabel;
  reason: string;
  reviewer: string;
  at: string;
}

export interface Approval {
  name: string;
  at: string;
}

/** The latest decision per claim (the history keeps every one). */
export function latestReviews(reviews: readonly Review[]): Record<string, Review> {
  const out: Record<string, Review> = {};
  for (const r of reviews) out[r.claim_id] = r;
  return out;
}

/** The reviewer's verdict when there is one, else the agent's. */
export function finalLabel(state: CaseState, latest: Record<string, Review>, claimId: string): VerdictLabel | null {
  return latest[claimId]?.label ?? state.verdicts[claimId]?.label ?? null;
}

export function finalCounts(state: CaseState, latest: Record<string, Review>): Partial<Record<VerdictLabel, number>> {
  const out: Partial<Record<VerdictLabel, number>> = {};
  for (const id of Object.keys(state.verdicts)) {
    const l = finalLabel(state, latest, id);
    if (l) out[l] = (out[l] ?? 0) + 1;
  }
  return out;
}

/** Claims the agent marked Needs review that no reviewer has decided: they block the sign-off. */
export function pendingReviews(state: CaseState, latest: Record<string, Review>): string[] {
  return state.claims.filter((c) => state.verdicts[c.id]?.label === "Needs review" && !latest[c.id]).map((c) => c.id);
}

export function reviewLine(r: Review): string {
  if (r.decision === "agree") return `Reviewer agreed with ${r.ai_label}.`;
  return `Reviewer changed the verdict from ${r.ai_label} to ${r.label}: ${r.reason}`;
}

export interface LogEntry {
  at: string | null;
  who: string;
  what: string;
  kind: "agent" | "human";
}

/** The audit trail in order: the agent's run and each verdict with its proof, then every human
 * decision, then the sign-off. */
export function decisionLog(state: CaseState, reviews: readonly Review[], approval: Approval | null): LogEntry[] {
  const out: LogEntry[] = [];
  if (state.startedAt || state.steps.length) {
    const fin = state.finished;
    const cost = fin ? ` · ${fin.llm_calls} model calls · ₹${fin.est_cost_inr.toFixed(2)}` : "";
    out.push({ at: state.startedAt, who: "Agent", what: `Checked the page in ${state.steps.length} steps${cost}`, kind: "agent" });
  }
  for (const c of state.claims) {
    const v = state.verdicts[c.id];
    if (!v) continue;
    const proof = [...v.evidence_ids, ...v.rule_ids].join(", ");
    out.push({ at: state.startedAt, who: "Agent", what: `${c.id} → ${v.label}${proof ? ` (${proof})` : ""}`, kind: "agent" });
  }
  for (const r of reviews) out.push({ at: r.at, who: r.reviewer, what: `${r.claim_id}: ${reviewLine(r)}`, kind: "human" });
  if (approval) out.push({ at: approval.at, who: approval.name, what: "Approved the report", kind: "human" });
  return out;
}

// ---------------------------------------------------------------------------
// Parsing what the server (or this tab's storage) gives back

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

const isLabel = (x: unknown): x is VerdictLabel => typeof x === "string" && (VERDICT_LABELS as readonly string[]).includes(x);

export function parseReview(x: unknown): Review | null {
  if (!isRecord(x)) return null;
  const { claim_id, decision, label, ai_label, reason, reviewer, at } = x;
  if (typeof claim_id !== "string" || (decision !== "agree" && decision !== "change")) return null;
  if (!isLabel(label) || !isLabel(ai_label) || typeof reviewer !== "string" || typeof at !== "string") return null;
  return { claim_id, decision, label, ai_label, reason: typeof reason === "string" ? reason : "", reviewer, at };
}

export function parseReviews(x: unknown): Review[] {
  return Array.isArray(x) ? x.map(parseReview).filter((r): r is Review => r !== null) : [];
}

// Recording mode: decisions and the sign-off live in this tab, per case
const key = (caseId: string) => `praman.review.${caseId}`;

export function loadLocal(caseId: string): { reviews: Review[]; approval: Approval | null } {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(key(caseId)) ?? "null");
    if (!isRecord(raw)) return { reviews: [], approval: null };
    const a = raw.approval;
    const approval = isRecord(a) && typeof a.name === "string" && typeof a.at === "string" ? { name: a.name, at: a.at } : null;
    return { reviews: parseReviews(raw.reviews), approval };
  } catch {
    return { reviews: [], approval: null };
  }
}

export function saveLocal(caseId: string, reviews: readonly Review[], approval: Approval | null): void {
  try {
    sessionStorage.setItem(key(caseId), JSON.stringify({ reviews, approval }));
  } catch {
    /* storage blocked: decisions stay on this page */
  }
}
