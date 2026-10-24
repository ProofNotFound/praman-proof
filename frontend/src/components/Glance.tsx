// Verdicts at a glance: one chip per claim, pinned above the board, filling in as the stamps land.
// A chip jumps to its claim. Hover shows the claim's words.

import { claimStatus, type CaseState } from "../lib/reducer";
import { VERDICT_KEY } from "../lib/view";

export function Glance({ state, onJump }: { state: CaseState; onJump: (claimId: string) => void }) {
  if (state.claims.length === 0) return null;
  return (
    <div className="glance" role="group" aria-label="Verdicts at a glance">
      {state.claims.map((c) => {
        const v = state.verdicts[c.id];
        const status = claimStatus(state, c.id);
        const cls = v ? `v-${VERDICT_KEY[v.label]}` : status;
        const text = v ? v.label : status === "active" ? "checking…" : "waiting";
        return (
          <button key={c.id} type="button" className={`glance-chip ${cls}`} title={`${c.id}: “${c.quote}”`} onClick={() => onJump(c.id)}>
            <span className="gid">{c.id}</span>
            <span className="gl">{text}</span>
          </button>
        );
      })}
    </div>
  );
}
