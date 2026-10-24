// A paired horizontal bar chart, hand-built in SVG (no chart library): for each verdict, how many
// of the labelled claims the agent and the text-only check got right.

import type { VerdictLabel } from "../lib/events";
import { verdictVar } from "../lib/view";

export interface ChartRow {
  label: VerdictLabel;
  expected: number;
  agent: number;
  baseline: number;
}

const ROW_H = 58;
const BAR_H = 16;
const LABEL_W = 150;
const VALUE_W = 64;
const W = 640;

export function EvalChart({ rows }: { rows: ChartRow[] }) {
  if (rows.length === 0) return <p className="note">No labelled claims in this set.</p>;
  const plot = W - LABEL_W - VALUE_W;
  const h = rows.length * ROW_H + 30;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${h}`} width="100%" role="img" aria-label="Agreement by verdict, agent and text-only">
        <title>Agreement by verdict</title>
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line x1={LABEL_W + plot * t} x2={LABEL_W + plot * t} y1={0} y2={rows.length * ROW_H} className="grid" />
            <text x={LABEL_W + plot * t} y={rows.length * ROW_H + 18} className="tick" textAnchor="middle">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const y = i * ROW_H + 8;
          const fa = r.expected ? r.agent / r.expected : 0;
          const fb = r.expected ? r.baseline / r.expected : 0;
          return (
            <g key={r.label}>
              <text x={0} y={y + BAR_H} className="row-label" style={{ fill: verdictVar(r.label) }}>
                {r.label}
              </text>
              <text x={0} y={y + BAR_H + 20} className="row-n">
                n = {r.expected}
              </text>
              <rect x={LABEL_W} y={y} width={Math.max(1, plot * fa)} height={BAR_H} className="bar agent" />
              <text x={LABEL_W + plot + 8} y={y + BAR_H - 3} className="val">
                {r.agent}/{r.expected}
              </text>
              <rect x={LABEL_W} y={y + BAR_H + 6} width={Math.max(1, plot * fb)} height={BAR_H} className="bar base" />
              <text x={LABEL_W + plot + 8} y={y + 2 * BAR_H + 3} className="val">
                {r.baseline}/{r.expected}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="legend mono">
        <span>
          <i className="sw agent" /> AGENT
        </span>
        <span>
          <i className="sw base" /> TEXT-ONLY
        </span>
      </figcaption>
    </figure>
  );
}
