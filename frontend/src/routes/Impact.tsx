// Impact (ROI): the same check at a team's scale. Every input is editable; the defaults are the
// evaluation's measured averages and the stated assumptions in lib/impact.ts.

import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useApp } from "../AppContext";
import { fetchEval } from "../lib/api";
import { ASSUMPTIONS, PENALTY_FIRST_INR, PENALTY_REPEAT_INR, rupees, scaleImpact, type ScaleInputs } from "../lib/impact";
import { TopBar } from "../components/TopBar";
import { FooterLine } from "../components/Seal";

const DEFAULTS: ScaleInputs = {
  listings: 1000,
  claimsPerListing: 3.8,
  manualMinutesPerPage: ASSUMPTIONS.manualMinutesPerPage,
  manualMinutesPerClaim: ASSUMPTIONS.manualMinutesPerClaim,
  reviewMinutesPerPage: ASSUMPTIONS.reviewMinutesPerPage,
  reviewerRupeesPerHour: ASSUMPTIONS.reviewerRupeesPerHour,
  aiRupeesPerListing: 1.01,
};

const FIELDS: { key: keyof ScaleInputs; label: string; note: string; step: number }[] = [
  { key: "listings", label: "Product pages to check", note: "a month", step: 100 },
  { key: "claimsPerListing", label: "Green claims per page", note: "measured: our 21 dev pages", step: 0.1 },
  { key: "manualMinutesPerPage", label: "By hand: minutes per page", note: "assumption: open, read, scroll the photos", step: 1 },
  { key: "manualMinutesPerClaim", label: "By hand: minutes per claim", note: "assumption: look for proof, check any certificate", step: 1 },
  { key: "reviewMinutesPerPage", label: "With Praman: review minutes per page", note: "assumption: read the report, decide open claims, sign", step: 1 },
  { key: "reviewerRupeesPerHour", label: "Reviewer cost, ₹ an hour", note: "assumption: about ₹12 lakh a year", step: 50 },
  { key: "aiRupeesPerListing", label: "Model cost, ₹ per page", note: "measured: agent mode, dev set", step: 0.1 },
];

export function ImpactRoute() {
  const { backend } = useApp();
  const [inputs, setInputs] = useState<ScaleInputs>(DEFAULTS);

  // Measured defaults from the evaluation, when it has run
  useEffect(() => {
    if (!backend) return;
    let alive = true;
    fetchEval(backend)
      .then((r) => {
        const dev = r.status === "done" ? r.splits.dev : undefined;
        const avg = dev?.modes.agent?.per_listing_avg;
        if (!alive || !dev || !avg || !dev.n_labelled || !dev.listings.length) return;
        setInputs((i) => ({
          ...i,
          claimsPerListing: Math.round((dev.n_labelled! / dev.listings.length) * 10) / 10,
          aiRupeesPerListing: Math.round(avg.cost_inr * 100) / 100,
        }));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [backend]);

  const r = scaleImpact(inputs);
  const set = (k: keyof ScaleInputs) => (v: string) => {
    const n = Number(v);
    if (Number.isFinite(n) && n >= 0) setInputs((i) => ({ ...i, [k]: n }));
  };

  return (
    <div className="screen eval-screen">
      <TopBar
        crumb={
          <>
            <Link to="/">CASES</Link> / <b>IMPACT</b>
          </>
        }
      />
      <main className="eval impact">
        <span className="label">Business value · change any number</span>
        <h1 className="eval-title">Impact at scale</h1>

        <div className="bignums">
          <div className="bignum">
            <span className="label">Reviewer hours saved</span>
            <b>{Math.round(r.hoursSaved).toLocaleString("en-IN")}</b>
            <span className="sub">
              {Math.round(r.manualHours).toLocaleString("en-IN")} h by hand → {Math.round(r.pramanHours).toLocaleString("en-IN")} h with Praman
            </span>
          </div>
          <div className="bignum">
            <span className="label">Cost saved</span>
            <b>{rupees(r.inrSaved)}</b>
            <span className="sub">
              {rupees(r.manualInr)} by hand → {rupees(r.pramanInr)} with Praman (model cost included)
            </span>
          </div>
          <div className="bignum">
            <span className="label">Faster</span>
            <b>{r.speedup ? `${r.speedup.toFixed(1)}×` : "—"}</b>
            <span className="sub">pages a reviewer clears in the same time; a human still signs every report</span>
          </div>
        </div>

        <p className="impact-risk">
          Penalties for a misleading advertisement under the Consumer Protection Act, 2019 (s.21) reach {rupees(PENALTY_FIRST_INR)}, and{" "}
          {rupees(PENALTY_REPEAT_INR)} for a repeat. At {rupees(inputs.aiRupeesPerListing)} a page, one avoided penalty pays for{" "}
          {Math.floor(PENALTY_FIRST_INR / Math.max(inputs.aiRupeesPerListing, 0.01)).toLocaleString("en-IN")} page checks.
        </p>

        <section className="split" aria-label="Inputs">
          <h2 className="split-title">Inputs</h2>
          <div className="impact-inputs">
            {FIELDS.map((f) => (
              <label key={f.key} className="impact-field">
                <span>{f.label}</span>
                <input type="number" min={0} step={f.step} value={inputs[f.key]} onChange={(e) => set(f.key)(e.target.value)} />
                <span className="note">{f.note}</span>
              </label>
            ))}
          </div>
          <div className="row-gap">
            <button type="button" className="btn" onClick={() => setInputs(DEFAULTS)}>
              Reset
            </button>
          </div>
          <p className="note">
            How it adds up: by hand = pages × (minutes per page + minutes per claim × claims). With Praman = pages × review minutes, plus the
            model cost. Assumptions are written down in docs/DECISIONS.md. A typical live check takes about {ASSUMPTIONS.liveSecondsPerPage} s
            of machine time, which needs no reviewer.
          </p>
        </section>
      </main>
      <footer className="foot">
        <FooterLine />
      </footer>
    </div>
  );
}
