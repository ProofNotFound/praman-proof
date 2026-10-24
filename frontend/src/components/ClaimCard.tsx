// Claim cards (DESIGN §4.2): ID and location, the quote, type and scope, rule chips, the stamp,
// one line of reason once decided, and suggested wording for anything not Backed.

import { forwardRef, useEffect } from "react";
import { motion, useAnimate } from "motion/react";
import type { Claim } from "../lib/events";
import { claimStatus, isFresh, type CaseState } from "../lib/reducer";
import { locationLabel, ruleChipText } from "../lib/view";
import { Stamp } from "./Stamp";
import { Seal } from "./Seal";
import { useApp } from "../AppContext";

interface Props {
  claim: Claim;
  state: CaseState;
  dim: boolean;
  lit: boolean;
  onFocus: (on: boolean) => void;
  /** a small mark when the other side of Compare decided differently */
  differs?: boolean;
  compact?: boolean;
  /** never animate (Compare, Report) */
  still?: boolean;
}

export const ClaimCard = forwardRef<HTMLElement, Props>(function ClaimCard(
  { claim, state, dim, lit, onFocus, differs = false, compact = false, still = false },
  ref,
) {
  const { motionOK, timeScale } = useApp();
  const v = state.verdicts[claim.id];
  const status = still ? (v ? "decided" : "waiting") : claimStatus(state, claim.id);
  const fresh = !still && v ? isFresh(state, v.seq) : false;
  const [scope, animate] = useAnimate<HTMLDivElement>();

  // The jolt: once the stamp lands, the card dips 1px and back (not for Not a claim).
  useEffect(() => {
    if (!fresh || !motionOK || !v || v.label === "Not a claim" || !scope.current) return;
    animate(scope.current, { y: [0, 1, 0] }, { duration: 0.08 * timeScale, delay: 0.26 * timeScale });
  }, [fresh, motionOK, v, animate, scope, timeScale]);

  const rules = v?.rules?.length ? v.rules.map((r) => r.id) : claim.rule_ids;
  const notClaim = !claim.is_claim || v?.label === "Not a claim";
  const finishedUndecided = !v && state.finished !== null;
  const waitingLabel = finishedUndecided ? "NO VERDICT" : "WAITING";
  const cls = [
    "card claim",
    status,
    notClaim ? "not-claim" : "",
    dim ? "dim" : "",
    lit ? "lit" : "",
    compact ? "compact" : "",
  ].join(" ");

  return (
    <motion.article
      ref={ref}
      className={cls}
      data-claim={claim.id}
      tabIndex={0}
      aria-label={`Claim ${claim.id}: ${claim.quote}. ${v ? `Verdict ${v.label}.` : status === "active" ? "Being checked." : "Waiting."}`}
      onMouseEnter={() => onFocus(true)}
      onMouseLeave={() => onFocus(false)}
      onFocus={() => onFocus(true)}
      onBlur={() => onFocus(false)}
    >
      <div ref={scope}>
        <div className="claim-head">
          <span className="cid">
            {claim.id} · {locationLabel(claim)}
            {claim.derived_from ? ` · from ${claim.derived_from}` : ""}
            {differs && (
              <span className="differs" title="Agent and text-only decided differently">
                {" "}· ◆ DIFFERS
              </span>
            )}
          </span>
          {v && <Stamp key={v.label} label={v.label} animate={fresh} className="claim-stamp" />}
          {status === "active" && !v && (
            <span className="working mono">
              <Seal spinning size={22} />
              CHECKING
            </span>
          )}
        </div>
        <div className="quote">“{claim.quote}”</div>
        <div className="meta">
          {claim.type.toUpperCase()} · {claim.scope.toUpperCase()}
          {status === "waiting" && <> · {waitingLabel}</>}
        </div>
        {!compact && rules.length > 0 && !notClaim && (
          <div className="rules">
            {rules.map((id) => {
              const r = state.rules[id];
              return (
                <span key={id} className="rule" title={r ? `${r.name}. ${r.summary} (${r.source})` : id}>
                  {ruleChipText(id, r)}
                </span>
              );
            })}
          </div>
        )}
        {v && <p className="reason">{v.reason}</p>}
        {!v && notClaim && claim.not_claim_reason && <p className="reason">{claim.not_claim_reason}</p>}
        {!compact && v?.missing && v.label !== "Backed" && v.label !== "Not a claim" && (
          <p className="missing">{v.missing}</p>
        )}
        {!compact && v?.rewrite && v.label !== "Backed" && v.label !== "Not a claim" && (
          <details className="sugg">
            <summary>Suggested wording</summary>
            <p>{v.rewrite}</p>
          </details>
        )}
      </div>
    </motion.article>
  );
});
