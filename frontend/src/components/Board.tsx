// The Board (DESIGN §4.2, centre): claim cards on the left, evidence cards on the right, threads
// between them. The Scan and the Ledger play over it (DESIGN §5.1, §5.2).

import { useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import { isFresh, type CaseState } from "../lib/reducer";
import { evidenceCards, type EvidenceCardModel } from "../lib/view";
import { ClaimCard } from "./ClaimCard";
import { EvidenceCard } from "./EvidenceCard";
import { Threads, type ThreadLink } from "./Threads";
import { Seal } from "./Seal";
import { ImpactStrip } from "./ImpactStrip";
import { Glance } from "./Glance";
import { useCaseUi, type Focus } from "./caseUi";
import { useApp } from "../AppContext";

export const QUOTA_LINE = "Model quota reached: claims not yet checked are marked Needs review.";

export function useConnections(cards: EvidenceCardModel[], focus: Focus | null) {
  return useMemo(() => {
    if (!focus) return null;
    const claims = new Set<string>();
    const keys = new Set<string>();
    if (focus.kind === "claim") {
      claims.add(focus.id);
      for (const c of cards) if (c.links.some((l) => l.claimId === focus.id)) keys.add(c.key);
    } else if (focus.kind === "card") {
      keys.add(focus.id);
      for (const l of cards.find((c) => c.key === focus.id)?.links ?? []) claims.add(l.claimId);
    } else {
      claims.add(focus.id);
      if (focus.card) keys.add(focus.card);
    }
    return { claims, keys, focus };
  }, [cards, focus]);
}

export function Board({
  state,
  overlay,
  working,
  fallback,
}: {
  state: CaseState;
  overlay?: ReactNode;
  working: boolean;
  /** "Play the recorded run" when a live run fails (demo safety) */
  fallback?: ReactNode;
}) {
  const ui = useCaseUi();
  const { motionOK } = useApp();
  const lanes = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const claimEls = useRef(new Map<string, HTMLElement>());
  const cardEls = useRef(new Map<string, HTMLElement>());
  const cards = useMemo(() => evidenceCards(state), [state]);
  const conn = useConnections(cards, ui.focus);

  const links = useMemo<ThreadLink[]>(() => {
    const out: ThreadLink[] = [];
    for (const card of cards) {
      const seen = new Set<string>();
      for (const l of card.links) {
        if (seen.has(l.claimId)) continue;
        seen.add(l.claimId);
        const seq = state.evidenceSeq[l.evidenceId] ?? 0;
        out.push({ claimId: l.claimId, cardKey: card.key, covers: l.covers, fresh: isFresh(state, seq) });
      }
    }
    return out;
  }, [cards, state]);

  const setClaimEl = useCallback(
    (id: string) => (el: HTMLElement | null) => {
      if (el) claimEls.current.set(id, el);
      else claimEls.current.delete(id);
    },
    [],
  );
  const setCardEl = useCallback(
    (key: string) => (el: HTMLElement | null) => {
      if (el) cardEls.current.set(key, el);
      else cardEls.current.delete(key);
    },
    [],
  );

  // Follow the claim being checked (only that: following the newest evidence too made the two
  // scrolls fight). Once the viewer scrolls or clicks a chip themselves, stop following; when the
  // run finishes, go back to the top so the verdicts are what they see.
  const manual = useRef(false);
  useEffect(() => {
    const stop = () => {
      manual.current = true;
    };
    window.addEventListener("wheel", stop, { passive: true });
    window.addEventListener("touchmove", stop, { passive: true });
    return () => {
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchmove", stop);
    };
  }, []);
  useEffect(() => {
    if (state.eventCount === 0) manual.current = false; // a new or restarted run
  }, [state.eventCount]);
  const behavior = motionOK ? "smooth" : "auto";
  useEffect(() => {
    const id = state.activeClaimId;
    if (!id || !working || manual.current) return;
    claimEls.current.get(id)?.scrollIntoView({ block: "nearest", behavior });
  }, [state.activeClaimId, working, behavior]);
  const done = state.finished !== null;
  useEffect(() => {
    if (!done || manual.current) return;
    scroller.current?.scrollTo({ top: 0, behavior });
  }, [done, behavior]);
  const jump = useCallback(
    (id: string) => {
      manual.current = true;
      claimEls.current.get(id)?.scrollIntoView({ block: "start", behavior });
    },
    [behavior],
  );

  const decided = state.claims.filter((c) => state.verdicts[c.id]).length;
  const isLit = (l: ThreadLink) => (conn ? conn.claims.has(l.claimId) && conn.keys.has(l.cardKey) : null);

  return (
    <section className="board-wrap" aria-label="Claims and proof">
      <div className="col board" ref={scroller}>
        <div className="board-head">
          <h2>Claims and proof</h2>
          <span className="label">
            {state.claims.length} {state.claims.length === 1 ? "claim" : "claims"} · {decided} decided
          </span>
        </div>
        <Glance state={state} onJump={jump} />
        {state.error && (
          <div className="notice error" role="alert">
            The run stopped: {state.error.message}
            {fallback}
          </div>
        )}
        {state.finished?.quota_reached && (
          <div className="notice" role="status">
            {QUOTA_LINE}
            {fallback}
          </div>
        )}
        <ImpactStrip state={state} />
        {state.claims.length === 0 ? (
          <div className="empty">
            {working || !state.finished ? (
              <>
                <Seal spinning={working} size={30} />
                <span>Reading the page…</span>
              </>
            ) : (
              <span>{state.finished?.quota_reached ? "The model's quota ran out before the claims were listed." : "No claims on this page."}</span>
            )}
            <div className="skeleton" aria-hidden="true">
              <i style={{ width: "86%" }} />
              <i style={{ width: "64%" }} />
              <i style={{ width: "75%" }} />
            </div>
          </div>
        ) : (
          <div className="lanes" ref={lanes}>
            <Threads
              lanes={lanes}
              claimEls={claimEls}
              cardEls={cardEls}
              links={links}
              isLit={isLit}
              onFocus={ui.setFocus}
              version={state.lastSeq}
            />
            <div className="lane lane-claims">
              {state.claims.map((c) => (
                <ClaimCard
                  key={c.id}
                  ref={setClaimEl(c.id)}
                  claim={c}
                  state={state}
                  dim={conn !== null && !conn.claims.has(c.id)}
                  lit={conn !== null && conn.claims.has(c.id)}
                  onFocus={(on) => ui.setFocus(on ? { kind: "claim", id: c.id } : null)}
                />
              ))}
            </div>
            <div aria-hidden="true" />
            <div className="lane lane-evidence">
              {cards.length === 0 && state.claims.length > 0 && (
                <p className="lane-empty mono">{state.finished ? "NO EVIDENCE FOUND" : "EVIDENCE WILL APPEAR HERE"}</p>
              )}
              {cards.map((card) => (
                <EvidenceCard
                  key={card.key}
                  ref={setCardEl(card.key)}
                  card={card}
                  state={state}
                  fresh={isFresh(state, card.seq)}
                  dim={conn !== null && !conn.keys.has(card.key)}
                  lit={conn !== null && conn.keys.has(card.key)}
                  onFocus={(on) => ui.setFocus(on ? { kind: "card", id: card.key } : null)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
      {overlay}
    </section>
  );
}
