// One line of business impact under a finished check: what it took against doing it by hand.

import { Link } from "react-router";
import type { CaseState } from "../lib/reducer";
import { ASSUMPTIONS, caseImpact, duration } from "../lib/impact";

export function ImpactStrip({ state }: { state: CaseState }) {
  if (!state.finished) return null;
  const i = caseImpact(state);
  const timeNote = i.measured ? "this run" : `a live run takes about ${ASSUMPTIONS.liveSecondsPerPage} s; this one was replayed`;
  return (
    <p className="impact-strip mono" aria-label="Impact">
      <span className="impact-k">IMPACT</span>
      <span>
        {i.claims} {i.claims === 1 ? "claim" : "claims"} checked
      </span>
      <span title={timeNote}>
        {i.measured ? "" : "~"}
        {duration(i.seconds)}
      </span>
      <span>₹{i.costInr.toFixed(2)}</span>
      <span>{i.forReview} for human review</span>
      <span title={`${ASSUMPTIONS.manualMinutesPerPage} min a page + ${ASSUMPTIONS.manualMinutesPerClaim} min a claim (assumption)`}>
        by hand ≈ {duration(i.manualMinutes * 60)} (est.)
      </span>
      <Link to="/impact" className="no-print">
        At scale →
      </Link>
    </p>
  );
}
