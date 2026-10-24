// The Trace (DESIGN §4.2, right): one row per plan → act → observe → decide step. PLAN rows show
// the agent's "why" in body text. Auto-scrolls unless the reader has scrolled up.

import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { isFresh, modelCalls, type CaseState, type StepRow } from "../lib/reducer";
import { formatClock, formatInr, formatMs, labelFromSummary, VERDICT_KEY } from "../lib/view";
import { useApp } from "../AppContext";

const PHASE: Record<StepRow["phase"], { glyph: string; text: string }> = {
  plan: { glyph: "◇", text: "PLAN" },
  act: { glyph: "▸", text: "ACT" },
  observe: { glyph: "○", text: "OBSERVE" },
  decide: { glyph: "■", text: "DECIDE" },
};

export function Trace({
  state,
  elapsedMs,
  working,
  modeLabel,
  llmLabel,
}: {
  state: CaseState;
  elapsedMs: number;
  working: boolean;
  modeLabel: string;
  llmLabel: string | null;
}) {
  const { present, motionOK, timeScale } = useApp();
  const list = useRef<HTMLOListElement>(null);
  const [pinned, setPinned] = useState(true);
  const steps = state.steps;
  const last = steps.at(-1);

  useEffect(() => {
    const el = list.current;
    if (!el || !pinned) return;
    el.scrollTo({ top: el.scrollHeight, behavior: motionOK ? "smooth" : "auto" });
  }, [steps.length, pinned, motionOK]);

  const onScroll = () => {
    const el = list.current;
    if (!el) return;
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  };

  return (
    <aside className="col trace" aria-label="Trace">
      <div className="trace-head">
        <span className="t">TRACE · {modeLabel}</span>
        <span className="clock" aria-label="Elapsed">
          {formatClock(elapsedMs)}
        </span>
      </div>
      <ol className="steps" ref={list} onScroll={onScroll}>
        {steps.length === 0 && <li className="steps-empty mono">{working ? "Starting…" : "No steps yet."}</li>}
        {steps.map((s) => {
          const ph = PHASE[s.phase];
          const label = s.phase === "decide" ? labelFromSummary(s.summary) : null;
          const live = working && s === last;
          const fresh = isFresh(state, s.seq) && motionOK;
          return (
            <motion.li
              key={s.seq}
              className={`step ph-${s.phase}${live ? " live" : ""}`}
              initial={fresh ? { opacity: 0, y: 8 } : false}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 * timeScale, ease: "easeOut" }}
            >
              <span className="n">{String(s.n).padStart(2, "0")}</span>
              <div>
                <div className="step-head">
                  <span className={`ph ph-${s.phase}${label ? ` v-${VERDICT_KEY[label]}` : ""}`}>
                    <span aria-hidden="true">{ph.glyph} </span>
                    {ph.text}
                  </span>
                  {s.claim_id && <span className="claim-ref">{s.claim_id}</span>}
                  {s.tool && <span className="tool">{s.tool}</span>}
                </div>
                <div className="sum">{s.summary}</div>
              </div>
              <span className="ms">{formatMs(s.ms)}</span>
            </motion.li>
          );
        })}
      </ol>
      {!pinned && (
        <button type="button" className="jump" onClick={() => setPinned(true)}>
          Jump to latest ↓
        </button>
      )}
      <div className="sr-only" aria-live="polite">
        {last ? `Step ${last.n}, ${PHASE[last.phase].text.toLowerCase()}: ${last.summary}` : ""}
      </div>
      <div className="trace-foot">
        <span>{steps.length} STEPS</span>
        <span>{modelCalls(state)} MODEL CALLS</span>
        {!present && <span>{state.finished ? formatInr(state.finished.est_cost_inr) : "₹ —"}</span>}
        {!present && llmLabel && <span className="opt">{llmLabel}</span>}
      </div>
    </aside>
  );
}
