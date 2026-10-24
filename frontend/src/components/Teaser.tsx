// The intake teaser (DESIGN §4.1): claim phrases from the demo cases, stamped in turn. Loops every
// 6 s, pauses on hover, and shows every stamp at once under reduced motion. Its stamps keep their
// own pace: the case player's speed (Instant included) doesn't apply here.

import { useEffect, useState } from "react";
import type { VerdictLabel } from "../lib/events";
import { Stamp } from "./Stamp";
import { useApp } from "../AppContext";

export interface TeaserItem {
  listingId: string;
  quote: string;
  label: VerdictLabel;
}

const CYCLE_MS = 6000;

export function Teaser({ items }: { items: TeaserItem[] }) {
  const { reducedMotion } = useApp();
  const [shown, setShown] = useState(0);
  const [hover, setHover] = useState(false);
  const still = reducedMotion;

  useEffect(() => {
    if (still || hover || items.length === 0) return;
    const step = CYCLE_MS / (items.length + 1);
    const id = setInterval(() => setShown((n) => (n >= items.length ? 0 : n + 1)), step);
    return () => clearInterval(id);
  }, [still, hover, items.length]);

  return (
    <div className="teaser" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <span className="label">From the case files</span>
      <ol>
        {items.map((it, i) => {
          const on = still || i < shown;
          return (
            <li key={it.listingId} className="teaser-row">
              <span className="mono teaser-id">{it.listingId}</span>
              <q className="teaser-quote">{it.quote}</q>
              <span className="teaser-stamp">{on && <Stamp label={it.label} animate={!still} size="sm" ownPace />}</span>
            </li>
          );
        })}
      </ol>
      {items.length > 0 && <p className="note">Real verdicts from the recorded runs.</p>}
    </div>
  );
}
