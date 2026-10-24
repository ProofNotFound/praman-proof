// Compare split (DESIGN §5.5): the text-only run and the agent run of the same listing, overlaid
// row by row; a divider decides which side shows. Left of it: text-only; right: agent.

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { X } from "lucide-react";
import { useApp } from "../AppContext";
import { fetchCompare, fetchRunRecording, loadRecording, startRun, streamRun, type Backend, type ComparePair } from "../lib/api";
import type { Claim, Mode, PramanEvent } from "../lib/events";
import { reduceAll, type CaseState } from "../lib/reducer";
import { bestMatch, compareGapLine, evidenceCards } from "../lib/view";
import { errorText } from "../lib/useCase";
import { useKeys } from "../hooks/useKeys";
import { ClaimCard } from "./ClaimCard";
import { EvidenceCard } from "./EvidenceCard";

interface Sides {
  agent: CaseState | null;
  baseline: CaseState | null;
  pairs: ComparePair[] | null;
}

/** Load both runs to their end. Live: the latest runs from /api/compare (a missing side can be run). */
export function useCompareData(backend: Backend | null, listingId: string) {
  const [sides, setSides] = useState<Sides | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<Mode | null>(null);

  useEffect(() => {
    if (!backend) return;
    let alive = true;
    setSides(null);
    setError(null);
    (async () => {
      if (backend.kind === "recording") {
        const [a, b] = await Promise.all([
          loadRecording(listingId, "agent").then((r) => reduceAll(r.events)).catch(() => null),
          loadRecording(listingId, "baseline").then((r) => reduceAll(r.events)).catch(() => null),
        ]);
        return { agent: a, baseline: b, pairs: null };
      }
      const cmp = await fetchCompare(listingId);
      const load = (id: string | undefined) => (id ? fetchRunRecording(id).then((r) => reduceAll(r.events)) : Promise.resolve(null));
      const [a, b] = await Promise.all([load(cmp.agent?.run_id), load(cmp.baseline?.run_id)]);
      return { agent: a, baseline: b, pairs: cmp.pairs.length ? cmp.pairs : null };
    })()
      .then((s) => alive && setSides(s))
      .catch((e: unknown) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [backend, listingId]);

  const runMissing = (mode: Mode) => {
    setRunning(mode);
    startRun({ listing_id: listingId, mode })
      .then(
        (runId) =>
          new Promise<CaseState>((resolve, reject) => {
            const events: PramanEvent[] = [];
            streamRun(runId, {
              onEvent: (e) => events.push(e),
              onEnd: () => resolve(reduceAll(events)),
              onError: (m) => reject(new Error(m)),
            });
          }),
      )
      .then((state) => setSides((s) => (s ? { ...s, [mode]: state, pairs: null } : s)))
      .catch((e: unknown) => setError(errorText(e)))
      .finally(() => setRunning(null));
  };

  return { sides, error, running, runMissing };
}

interface Row {
  key: string;
  agent: Claim | null;
  baseline: Claim | null;
  differs: boolean;
}

export function compareRows(agent: CaseState, baseline: CaseState, pairs: ComparePair[] | null): Row[] {
  const rows: Row[] = [];
  const usedB = new Set<string>();
  const bById = new Map(baseline.claims.map((c) => [c.id, c] as const));
  for (const a of agent.claims) {
    let b: Claim | null = null;
    const pair = pairs?.find((p) => p.agent_claim_id === a.id);
    if (pair) b = pair.baseline_claim_id ? (bById.get(pair.baseline_claim_id) ?? null) : null;
    else b = bestMatch(a.quote, baseline.claims.filter((c) => !usedB.has(c.id)));
    if (b) usedB.add(b.id);
    const la = agent.verdicts[a.id]?.label ?? null;
    const lb = b ? (baseline.verdicts[b.id]?.label ?? null) : null;
    rows.push({ key: `a:${a.id}`, agent: a, baseline: b, differs: la !== lb });
  }
  for (const b of baseline.claims) {
    if (!usedB.has(b.id)) rows.push({ key: `b:${b.id}`, agent: null, baseline: b, differs: true });
  }
  return rows;
}

export function CompareSplit({ listingId, onClose }: { listingId: string; onClose: () => void }) {
  const { backend } = useApp();
  const { sides, error, running, runMissing } = useCompareData(backend, listingId);
  const [pos, setPos] = useState(50);
  const stage = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  useKeys({
    ArrowLeft: () => setPos((p) => Math.max(0, p - 10)),
    ArrowRight: () => setPos((p) => Math.min(100, p + 10)),
  });

  const rows = useMemo(
    () => (sides?.agent && sides.baseline ? compareRows(sides.agent, sides.baseline, sides.pairs) : []),
    [sides],
  );
  const differ = rows.filter((r) => r.differs).length;

  const moveTo = (clientX: number) => {
    const box = stage.current?.getBoundingClientRect();
    if (!box) return;
    setPos(Math.max(0, Math.min(100, ((clientX - box.left) / box.width) * 100)));
  };
  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    moveTo(e.clientX);
  };
  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => dragging.current && moveTo(e.clientX);
  const onUp = () => {
    dragging.current = false;
  };

  const missing: Mode | null = sides && !sides.agent ? "agent" : sides && !sides.baseline ? "baseline" : null;

  return (
    <div className="overlay compare" role="region" aria-label="Compare agent and text-only">
      <div className="cmp-head">
        <h2>Agent vs text-only</h2>
        <span className="label">
          {sides?.agent && sides.baseline ? `${rows.length} claims · ${differ} decided differently` : "Loading both runs…"}
        </span>
        <div className="spacer" />
        <span className="label cmp-hint">
          Drag the divider or press <kbd>←</kbd> <kbd>→</kbd>
        </span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close compare (B)">
          <X size={18} strokeWidth={1.5} />
        </button>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {missing && !error && (
        <div className="notice">
          There's no {missing === "agent" ? "agent" : "text-only"} run of {listingId} yet.
          {backend?.kind === "live" && (
            <button type="button" className="btn" disabled={running !== null} onClick={() => runMissing(missing)}>
              {running ? "Running…" : `Run the ${missing === "agent" ? "agent" : "text-only"} check`}
            </button>
          )}
        </div>
      )}
      {sides?.agent && sides.baseline && (
        <div className="cmp-stage" ref={stage}>
          <div className="cmp-rows">
            {rows.map((r) => (
              <div key={r.key} className="cmp-row">
                <div className="cmp-layer" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} aria-hidden={pos < 5}>
                  <Side state={sides.baseline!} claim={r.baseline} other={r.agent} differs={r.differs} side="baseline" />
                </div>
                <div className="cmp-layer" style={{ clipPath: `inset(0 0 0 ${pos}%)` }} aria-hidden={pos > 95}>
                  <Side state={sides.agent!} claim={r.agent} other={r.baseline} differs={r.differs} side="agent" />
                </div>
              </div>
            ))}
          </div>
          <div
            className="cmp-divider"
            style={{ left: `${pos}%` }}
            role="slider"
            tabIndex={0}
            aria-label="Divider: text-only on the left, agent on the right"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pos)}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
          >
            <span className="cmp-handle mono">
              <span>TEXT-ONLY</span>
              <i aria-hidden="true">⟷</i>
              <span>AGENT</span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function Side({
  state,
  claim,
  other,
  differs,
  side,
}: {
  state: CaseState;
  claim: Claim | null;
  other: Claim | null;
  differs: boolean;
  side: Mode;
}) {
  const cards = useMemo(() => (claim ? evidenceCards(state).filter((c) => c.links.some((l) => l.claimId === claim.id)) : []), [state, claim]);
  const noop = () => {};
  if (!claim) {
    return (
      <div className="cmp-side">
        <article className="card claim not-seen">
          <div className="claim-head">
            <span className="cid">{side === "baseline" ? "TEXT-ONLY" : "AGENT"}</span>
            <span className="stamp outline stamp-sm">NOT SEEN</span>
          </div>
          <div className="quote">“{other?.quote}”</div>
        </article>
        <Gap side={side} text={compareGapLine(side, null, other, null)} />
      </div>
    );
  }
  return (
    <div className="cmp-side">
      <ClaimCard claim={claim} state={state} dim={false} lit={false} onFocus={noop} differs={differs} still compact />
      {cards.length === 0 && side === "baseline" && (
        <Gap side={side} text={compareGapLine(side, claim, other, state.verdicts[claim.id]?.label ?? null)} />
      )}
      <div className="cmp-ev">
        {cards.length === 0 && side === "agent" && (
          <p className="cmp-gap">{compareGapLine(side, claim, other, state.verdicts[claim.id]?.label ?? null)}</p>
        )}
        {cards.slice(0, 3).map((card) => (
          <EvidenceCard key={card.key} card={card} state={state} fresh={false} dim={false} lit={false} onFocus={noop} />
        ))}
        {cards.length > 3 && <p className="more mono">+{cards.length - 3} more</p>}
      </div>
    </div>
  );
}

/** Why a side has nothing for a claim, placed where that side shows at the default divider:
 *  under the claim card on the text-only side, in the evidence lane on the agent side. */
function Gap({ side, text }: { side: Mode; text: string }) {
  if (side === "agent") {
    return (
      <div className="cmp-ev">
        <p className="cmp-gap">{text}</p>
      </div>
    );
  }
  return <p className="cmp-gap under">{text}</p>;
}
