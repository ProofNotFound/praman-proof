// The Threads (DESIGN §5.3): cubic Bézier curves from a claim card's right edge to each evidence
// card that cites it, coloured by covers_claim, drawn in when the evidence appears.

import { useEffect, useState, type RefObject } from "react";
import { motion } from "motion/react";
import type { CoversClaim } from "../lib/events";
import { COVER_VAR } from "../lib/view";
import { useApp } from "../AppContext";
import type { Focus } from "./caseUi";

export interface ThreadLink {
  claimId: string;
  cardKey: string;
  covers: CoversClaim;
  fresh: boolean;
}

interface Geometry {
  w: number;
  h: number;
  paths: { key: string; d: string; x1: number; y1: number; x2: number; y2: number; link: ThreadLink }[];
}

export function Threads({
  lanes,
  claimEls,
  cardEls,
  links,
  isLit,
  onFocus,
  version,
}: {
  lanes: RefObject<HTMLDivElement | null>;
  claimEls: RefObject<Map<string, HTMLElement>>;
  cardEls: RefObject<Map<string, HTMLElement>>;
  links: ThreadLink[];
  /** null when nothing is focused */
  isLit: (l: ThreadLink) => boolean | null;
  onFocus: (f: Focus | null) => void;
  /** changes whenever cards may have moved */
  version: number;
}) {
  const { motionOK, timeScale } = useApp();
  const [geo, setGeo] = useState<Geometry>({ w: 0, h: 0, paths: [] });

  // A passive effect: it runs after every ref in the board (siblings included) is attached.
  useEffect(() => {
    const root = lanes.current;
    if (!root) return;
    const measure = () => {
      const box = root.getBoundingClientRect();
      const paths: Geometry["paths"] = [];
      for (const link of links) {
        const a = claimEls.current.get(link.claimId);
        const b = cardEls.current.get(link.cardKey);
        if (!a || !b) continue;
        const ra = a.getBoundingClientRect();
        const rb = b.getBoundingClientRect();
        const x1 = ra.right - box.left;
        const y1 = ra.top - box.top + Math.min(40, ra.height / 2);
        const x2 = rb.left - box.left;
        const y2 = rb.top - box.top + Math.min(26, rb.height / 2);
        const dx = Math.max(24, (x2 - x1) * 0.55);
        paths.push({
          key: `${link.claimId}>${link.cardKey}`,
          d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`,
          x1,
          y1,
          x2,
          y2,
          link,
        });
      }
      setGeo((g) => {
        const same =
          g.w === box.width &&
          g.h === box.height &&
          g.paths.length === paths.length &&
          g.paths.every((p, i) => p.d === paths[i]?.d && p.link.covers === paths[i]?.link.covers);
        return same ? g : { w: box.width, h: box.height, paths };
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    for (const el of claimEls.current.values()) ro.observe(el);
    for (const el of cardEls.current.values()) ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [lanes, claimEls, cardEls, links, version]);

  return (
    <svg className="threads" width={geo.w} height={geo.h} viewBox={`0 0 ${geo.w || 1} ${geo.h || 1}`} aria-hidden="true">
      {geo.paths.map((p) => {
        const lit = isLit(p.link);
        const colour = COVER_VAR[p.link.covers];
        const dashed = p.link.covers === "no";
        const draw = p.link.fresh && motionOK && !dashed;
        return (
          <g key={p.key} className={lit === false ? "thread dim" : "thread"} style={{ color: colour }}>
            <motion.path
              d={p.d}
              className={dashed ? "dashed" : undefined}
              initial={draw ? { pathLength: 0 } : p.link.fresh && motionOK ? { opacity: 0 } : false}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ duration: 0.5 * timeScale, ease: "easeOut" }}
            />
            <circle cx={p.x1} cy={p.y1} r={3} />
            <circle cx={p.x2} cy={p.y2} r={3} />
            <path
              d={p.d}
              className="hit"
              onMouseEnter={() => onFocus({ kind: "link", id: p.link.claimId, card: p.link.cardKey })}
              onMouseLeave={() => onFocus(null)}
            />
          </g>
        );
      })}
    </svg>
  );
}
