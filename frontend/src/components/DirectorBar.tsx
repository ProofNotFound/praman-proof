// The Director bar (DESIGN §7): restart, play/pause, step, speed, and one tick per event.

import { Pause, Play, RotateCcw, StepForward } from "lucide-react";
import type { PramanEvent } from "../lib/events";
import { SPEEDS, type PacerSnapshot, type Speed } from "../lib/pacer";
import { VERDICT_KEY } from "../lib/view";
import { useApp } from "../AppContext";
import { FooterLine } from "./Seal";

const speedText = (s: Speed) => (s === "instant" ? "Instant" : `${s}×`);

export function DirectorBar({
  snap,
  events,
  onToggle,
  onStep,
  onRestart,
}: {
  snap: PacerSnapshot;
  events: readonly PramanEvent[];
  onToggle: () => void;
  onStep: () => void;
  onRestart: () => void;
}) {
  const { speed, setSpeed, setShortcuts } = useApp();
  const done = snap.ended && snap.released >= snap.total;
  return (
    <footer className="director" aria-label="Director controls">
      <div className="ctrl">
        <button type="button" onClick={onRestart} aria-label="Restart (R)" title="Restart (R)">
          <RotateCcw size={17} strokeWidth={1.5} />
        </button>
        <button
          type="button"
          className={snap.paused ? "" : "on"}
          onClick={onToggle}
          aria-label={snap.paused ? "Play (Space)" : "Pause (Space)"}
          title={snap.paused ? "Play (Space)" : "Pause (Space)"}
          disabled={done}
        >
          {snap.paused ? <Play size={17} strokeWidth={1.5} /> : <Pause size={17} strokeWidth={1.5} />}
        </button>
        <button type="button" onClick={onStep} aria-label="Step one event (→)" title="Step one event (→)" disabled={snap.released >= snap.total}>
          <StepForward size={17} strokeWidth={1.5} />
        </button>
      </div>
      <div className="speeds" role="radiogroup" aria-label="Speed">
        {SPEEDS.map((s) => (
          <button key={String(s)} type="button" role="radio" aria-checked={speed === s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>
            {speedText(s)}
          </button>
        ))}
      </div>
      <div className="ticks" role="progressbar" aria-label="Events played" aria-valuemin={0} aria-valuemax={snap.total} aria-valuenow={snap.released}>
        {events.map((e, i) => {
          let cls = i < snap.released ? "f" : "";
          if (i < snap.released && e.type === "verdict") cls = `v v-${VERDICT_KEY[e.data.label]}`;
          if (i === snap.released - 1 && !done) cls += " now";
          return <i key={e.seq} className={cls} />;
        })}
      </div>
      <span className="count mono">
        {snap.released}/{snap.total}
      </span>
      <button type="button" className="keys" onClick={() => setShortcuts(true)}>
        <kbd>Space</kbd> pause · <kbd>→</kbd> step · <kbd>?</kbd> keys
      </button>
      <FooterLine className="director-note" />
    </footer>
  );
}
