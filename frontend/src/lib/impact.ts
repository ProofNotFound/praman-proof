// Business impact (ROI): what one check cost against doing it by hand, and the same at scale.
// Every number that isn't measured is a stated assumption (docs/DECISIONS.md), editable on the
// Impact screen.

import type { CaseState } from "./reducer";

export const ASSUMPTIONS = {
  /** By hand: open the page, read it, scroll the photos; then per claim, look for proof and check
   * any certificate. Conservative: most claims are vague and quick to rule on, and only a few need
   * the CPCB registry searched. */
  manualMinutesPerPage: 5,
  manualMinutesPerClaim: 3,
  /** Measured, not assumed: the holdout evaluation ran 10 pages live at 43.5 s each on average
   * (eval/results.md; 4 earlier runs had a 21 s median). We quote the slower figure, rounded up. */
  liveSecondsPerPage: 45,
  /** A reviewer reading a Praman report, deciding any open claims and signing it. */
  reviewMinutesPerPage: 3,
  /** A compliance analyst in India, about ₹12 lakh a year. */
  reviewerRupeesPerHour: 600,
} as const;

/** Consumer Protection Act, 2019, s.21: penalty for a misleading advertisement. */
export const PENALTY_FIRST_INR = 1_000_000;
export const PENALTY_REPEAT_INR = 5_000_000;

export interface CaseImpact {
  claims: number;
  seconds: number;
  /** false when the run was replayed: the time is the typical live time, not this run's */
  measured: boolean;
  costInr: number;
  forReview: number;
  manualMinutes: number;
}

export function caseImpact(state: CaseState): CaseImpact {
  const labels = Object.values(state.verdicts).map((v) => v.label);
  const claims = labels.filter((l) => l !== "Not a claim").length;
  const fin = state.finished;
  const measured = state.llmMode === "live" && fin !== null && (fin.cached_calls ?? 0) < fin.llm_calls;
  return {
    claims,
    seconds: measured && fin ? fin.elapsed_ms / 1000 : ASSUMPTIONS.liveSecondsPerPage,
    measured,
    costInr: fin?.est_cost_inr ?? 0,
    forReview: labels.filter((l) => l === "Needs review").length,
    manualMinutes: ASSUMPTIONS.manualMinutesPerPage + ASSUMPTIONS.manualMinutesPerClaim * claims,
  };
}

export interface ScaleInputs {
  listings: number;
  claimsPerListing: number;
  manualMinutesPerPage: number;
  manualMinutesPerClaim: number;
  reviewMinutesPerPage: number;
  reviewerRupeesPerHour: number;
  aiRupeesPerListing: number;
}

export interface ScaleResult {
  manualHours: number;
  manualInr: number;
  pramanHours: number;
  pramanInr: number;
  hoursSaved: number;
  inrSaved: number;
  /** how many times faster a reviewer clears the same pages */
  speedup: number;
}

export function scaleImpact(i: ScaleInputs): ScaleResult {
  const manualMinutes = i.listings * (i.manualMinutesPerPage + i.manualMinutesPerClaim * i.claimsPerListing);
  const reviewMinutes = i.listings * i.reviewMinutesPerPage;
  const manualHours = manualMinutes / 60;
  const pramanHours = reviewMinutes / 60;
  const manualInr = manualHours * i.reviewerRupeesPerHour;
  const pramanInr = pramanHours * i.reviewerRupeesPerHour + i.listings * i.aiRupeesPerListing;
  return {
    manualHours,
    manualInr,
    pramanHours,
    pramanInr,
    hoursSaved: manualHours - pramanHours,
    inrSaved: manualInr - pramanInr,
    speedup: pramanHours > 0 ? manualHours / pramanHours : 0,
  };
}

/** ₹ in the Indian way: 12,34,567 and lakh/crore words for big sums. */
export function rupees(n: number): string {
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} crore`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} lakh`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export function duration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  const m = seconds / 60;
  if (m < 90) return `${Math.round(m)} min`;
  return `${(m / 60).toFixed(1)} h`;
}
