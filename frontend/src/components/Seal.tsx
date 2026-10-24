// The seal (DESIGN §3): "PRAMAN · PROOF CHECK ·" around "प्र", drawn from docs/design/praman_seal.svg.
// It is also the working indicator: it turns once every 6 s while the agent works and stops the
// moment the run finishes.

import { useApp } from "../AppContext";
import {
  SEAL_CENTRE as C,
  SEAL_GLYPHS,
  SEAL_INNER,
  SEAL_MARK,
  SEAL_OUTER,
  SEAL_RING_SIZE,
  SEAL_RING_Y,
  SEAL_VIEWBOX,
} from "../lib/seal";

/** Shared SVG defs: the seal symbol and the ink texture used by stamps. Render once. */
export function SvgDefs() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
      <defs>
        <filter id="ink" x="-10%" y="-20%" width="120%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="1.6" result="d" />
          <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="1" seed="2" result="s" />
          <feColorMatrix in="s" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -3 2.3" result="m" />
          <feComposite in="d" in2="m" operator="in" />
        </filter>
        <symbol id="seal" viewBox={`0 0 ${SEAL_VIEWBOX} ${SEAL_VIEWBOX}`}>
          <g style={{ fill: "none", stroke: "var(--accent)" }}>
            <circle cx={C} cy={C} r={SEAL_OUTER.r} strokeWidth={SEAL_OUTER.stroke} />
            <circle cx={C} cy={C} r={SEAL_INNER.r} strokeWidth={SEAL_INNER.stroke} />
          </g>
          <g
            fontSize={SEAL_RING_SIZE}
            fontWeight="700"
            textAnchor="middle"
            style={{ fill: "var(--accent)", fontFamily: "var(--font-sans)" }}
          >
            {SEAL_GLYPHS.map((g, i) => (
              <text key={i} x={C} y={SEAL_RING_Y} transform={`rotate(${g.angle} ${C} ${C})`}>
                {g.ch}
              </text>
            ))}
          </g>
          <text
            x={C}
            y={C}
            dy={SEAL_MARK.dy}
            fontSize={SEAL_MARK.size}
            fontWeight="700"
            textAnchor="middle"
            style={{ fill: "var(--accent)", fontFamily: "var(--font-deva)" }}
          >
            {SEAL_MARK.text}
          </text>
        </symbol>
      </defs>
    </svg>
  );
}

export function Seal({ spinning = false, size = 38, label }: { spinning?: boolean; size?: number; label?: string }) {
  const { reducedMotion } = useApp();
  return (
    <svg
      className={`seal${spinning && !reducedMotion ? " spin" : ""}`}
      width={size}
      height={size}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <use href="#seal" />
    </svg>
  );
}

export function Brand({ spinning = false }: { spinning?: boolean }) {
  return (
    <span className="brand">
      <Seal spinning={spinning} size={54} label={spinning ? "Praman, working" : "Praman"} />
      <span className="word">Praman</span>
    </span>
  );
}

export const FOOTER_LINE = "Decision support, not legal advice · CPCB certified list dated 26 Oct 2023";

export function FooterLine({ className = "" }: { className?: string }) {
  return <p className={`foot-note ${className}`}>{FOOTER_LINE}</p>;
}
