// Evaluation (DESIGN §4.4): agreement with the labels for the agent and the text-only check,
// false "Backed", a paired bar chart per verdict, proof only the agent found, and disagreements.
// While labels are pending it says so and shows no numbers.

import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useApp } from "../AppContext";
import { fetchEval, fileCaseId, type EvalResult, type EvalSplit, type ModeMetrics, type RunStats } from "../lib/api";
import { VERDICT_LABELS, type VerdictLabel } from "../lib/events";
import { errorText } from "../lib/useCase";
import { formatDateTime } from "../lib/view";
import { TopBar } from "../components/TopBar";
import { FooterLine } from "../components/Seal";
import { Stamp } from "../components/Stamp";
import { EvalChart } from "../components/EvalChart";

const SPLIT_NAME: Record<string, string> = { dev: "Development set", holdout: "Blind holdout" };

export function EvalRoute() {
  const { backend } = useApp();
  const [result, setResult] = useState<EvalResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!backend) return;
    let alive = true;
    fetchEval(backend)
      .then((r) => alive && setResult(r))
      .catch((e: unknown) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [backend]);

  return (
    <div className="screen eval-screen">
      <TopBar
        crumb={
          <>
            <Link to="/">CASES</Link> / <b>EVALUATION</b>
          </>
        }
      />
      <main className="eval">
        <span className="label">Agent vs text-only, against hand labels</span>
        <h1 className="eval-title">Evaluation</h1>
        {error && (
          <div className="notice error" role="alert">
            Couldn't load the results: {error}
          </div>
        )}
        {!result && !error && (
          <div className="skeleton" aria-busy="true">
            <i style={{ width: "50%" }} />
            <i style={{ width: "70%" }} />
          </div>
        )}
        {result?.status === "pending" && (
          <section className="pending">
            <h2>Pending labels</h2>
            <p>
              Results appear here once the claim labels are written and the evaluation has run (<code>eval/labels.csv</code>, checked with{" "}
              <code>uv run eval/check_labels.py</code>, then <code>uv run eval/run_eval.py</code>). Until then there is nothing to report.
            </p>
          </section>
        )}
        {result?.status === "done" && (
          <>
            {result.labels_note && (
              <div className="notice labels-note" role="note">
                <b>Not the full evaluation.</b> {result.labels_note}
              </div>
            )}
            <p className="eval-meta mono">
              {result.eval_id} · {formatDateTime(result.generated_at)} · model answers {result.llm_mode} · labels {result.labels_file}
            </p>
            {(["dev", "holdout"] as const).map((k) => {
              const split = result.splits[k];
              return split ? <Split key={k} name={SPLIT_NAME[k] ?? k} split={split} /> : null;
            })}
            {!result.splits.holdout && <p className="note">No blind holdout results yet.</p>}
          </>
        )}
      </main>
      <footer className="foot">
        <FooterLine />
      </footer>
    </div>
  );
}

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "—";
}

function Split({ name, split }: { name: string; split: EvalSplit }) {
  if (split.status === "not_run") {
    return (
      <section className="split" aria-label={name}>
        <h2 className="split-title">
          {name} <span className="label">not run yet</span>
        </h2>
        <p className="note">
          {split.listings.length} listings, {split.n_labelled ?? "?"} labelled claims. The blind holdout runs once, at the end (
          <code>uv run eval/run_eval.py --holdout</code>), so no prompt is ever tuned on it.
        </p>
      </section>
    );
  }
  const a = split.modes.agent;
  const b = split.modes.baseline;
  return (
    <section className="split" aria-label={name}>
      <h2 className="split-title">
        {name} <span className="label">{split.listings.join(" · ")}</span>
      </h2>
      {split.hand_checked !== undefined && a && (
        <p className="note">
          Labels checked by a person: {split.hand_checked} of {a.n_labelled}.
        </p>
      )}
      <div className="bignums">
        <BigNumber title="Verdict agreement · agent" m={a} />
        <BigNumber title="Verdict agreement · text-only" m={b} />
        <div className="bignum">
          <span className="label">False “Backed” · agent</span>
          <b className={a && a.false_backed > 0 ? "bad" : ""}>{a ? a.false_backed : "—"}</b>
          <span className="sub">
            {a ? `of ${a.n_labelled} labelled claims · text-only: ${b?.false_backed ?? "—"}` : "no agent run"} · target 0
          </span>
        </div>
      </div>

      <h3 className="label">Agreement by verdict</h3>
      <EvalChart rows={chartRows(a, b)} />

      {(a?.confusion || b?.confusion) && (
        <>
          <h3 className="label">Confusion matrix · rows are our labels</h3>
          <div className="confusions">
            {a?.confusion && <Confusion title="Agent" m={a.confusion} />}
            {b?.confusion && <Confusion title="Text-only" m={b.confusion} />}
          </div>
        </>
      )}

      {split.per_listing && split.per_listing.length > 0 && (
        <>
          <h3 className="label">Model calls, time and cost per listing</h3>
          <table className="disagree per-listing">
            <thead>
              <tr>
                <th scope="col">Listing</th>
                <th scope="col">Agent</th>
                <th scope="col">Text-only</th>
              </tr>
            </thead>
            <tbody>
              {split.per_listing.map((p) => (
                <tr key={p.listing_id}>
                  <td className="mono">
                    <Link to={`/case/${fileCaseId(p.listing_id, "agent")}`}>{p.listing_id}</Link>
                  </td>
                  <td className="mono">{statsText(p.agent)}</td>
                  <td className="mono">{statsText(p.baseline)}</td>
                </tr>
              ))}
              {a?.per_listing_avg && b?.per_listing_avg && (
                <tr className="avg">
                  <td className="mono">Average</td>
                  <td className="mono">{statsText(a.per_listing_avg)}</td>
                  <td className="mono">{statsText(b.per_listing_avg)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}

      <h3 className="label">Proof only the agent found</h3>
      {split.proof_only_agent.length === 0 ? (
        <p className="note">None in this set.</p>
      ) : (
        <ul className="proof-only">
          {split.proof_only_agent.map((p) => (
            <li key={p.claim_ref}>
              <Stamp label={p.label as VerdictLabel} size="sm" />
              <q>{p.quote}</q>
              <span className="mono sources">{p.sources.map((s) => s.toUpperCase()).join(" + ")}</span>
              <Link to={`/case/${fileCaseId(p.listing_id, "agent")}`}>Case {p.listing_id}</Link>
            </li>
          ))}
        </ul>
      )}

      <h3 className="label">Where they disagree</h3>
      {split.disagreements.length === 0 ? (
        <p className="note">No disagreements.</p>
      ) : (
        <table className="disagree">
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Our label</th>
              <th scope="col">Agent</th>
              <th scope="col">Text-only</th>
              <th scope="col">
                <span className="sr-only">Case</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {split.disagreements.map((d) => (
              <tr key={d.claim_ref}>
                <td>
                  <q>{d.quote}</q>
                  <span className="mono ref">{d.claim_ref}</span>
                </td>
                <td>{d.expected}</td>
                <td className={d.agent === d.expected ? "agree" : "differ"}>{d.agent ?? "not found"}</td>
                <td className={d.baseline === d.expected ? "agree" : "differ"}>{d.baseline ?? "not found"}</td>
                <td>
                  <Link to={`/case/${fileCaseId(d.listing_id, "agent")}`}>Case {d.listing_id}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const NOT_FOUND = "Not found";

function Confusion({ title, m }: { title: string; m: Record<string, Record<string, number>> }) {
  const rows = VERDICT_LABELS.filter((v) => m[v]);
  const cols = [...VERDICT_LABELS, NOT_FOUND].filter((v) => rows.some((r) => (m[r]?.[v] ?? 0) > 0));
  return (
    <table className="disagree confusion">
      <caption className="label">{title}</caption>
      <thead>
        <tr>
          <th scope="col">Label \ verdict</th>
          {cols.map((c) => (
            <th key={c} scope="col">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r}>
            <th scope="row">{r}</th>
            {cols.map((c) => {
              const n = m[r]?.[c] ?? 0;
              return (
                <td key={c} className={`mono${n && c === r ? " agree" : n ? " differ" : ""}`}>
                  {n || "·"}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function statsText(s: Pick<RunStats, "model_calls" | "seconds" | "cost_inr">): string {
  return `${s.model_calls} ${s.model_calls === 1 ? "call" : "calls"} · ${s.seconds.toFixed(1)} s · ₹${s.cost_inr.toFixed(2)}`;
}

function BigNumber({ title, m }: { title: string; m: ModeMetrics | undefined }) {
  return (
    <div className="bignum">
      <span className="label">{title}</span>
      <b>{m ? pct(m.agree, m.n_labelled) : "—"}</b>
      <span className="sub">
        {m ? `${m.agree} of ${m.n_labelled} labelled claims${m.missed ? ` · ${m.missed} not found` : ""}` : "no run"}
      </span>
    </div>
  );
}

function chartRows(a: ModeMetrics | undefined, b: ModeMetrics | undefined) {
  return VERDICT_LABELS.map((label) => {
    const ea = a?.by_verdict[label];
    const eb = b?.by_verdict[label];
    const expected = ea?.expected ?? eb?.expected ?? 0;
    return { label, expected, agent: ea?.agree ?? 0, baseline: eb?.agree ?? 0 };
  }).filter((r) => r.expected > 0);
}
