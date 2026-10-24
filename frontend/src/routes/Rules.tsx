// Rule packs (reusability): the same engine with a different rulebook. Each pack is one JSON file;
// "Try a pack" runs its trigger matching on any text, in the browser, with no model call.

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useApp } from "../AppContext";
import { fetchRulePacks } from "../lib/api";
import { triggeredRules, type RulePack } from "../lib/packs";
import { errorText } from "../lib/useCase";
import { TopBar } from "../components/TopBar";
import { FooterLine } from "../components/Seal";

const SAMPLES: Record<string, string> = {
  green_claims: "100% compostable garbage bags. Eco-friendly and plastic-free, made from plants. Carbon neutral by 2030.",
  food_labels: "100% natural, certified organic peanut butter. High protein, no added sugar. Boosts immunity.",
};

export function RulesRoute() {
  const { backend } = useApp();
  const [packs, setPacks] = useState<RulePack[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState("green_claims");
  const [text, setText] = useState(SAMPLES.green_claims ?? "");

  useEffect(() => {
    if (!backend) return;
    let alive = true;
    fetchRulePacks(backend)
      .then((p) => alive && setPacks(p))
      .catch((e: unknown) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [backend]);

  const pack = packs?.find((p) => p.name === active) ?? null;
  const hits = useMemo(() => (pack ? triggeredRules(pack, text) : []), [pack, text]);
  const choose = (name: string) => {
    setActive(name);
    setText(SAMPLES[name] ?? "");
  };

  return (
    <div className="screen eval-screen">
      <TopBar
        crumb={
          <>
            <Link to="/">CASES</Link> / <b>RULE PACKS</b>
          </>
        }
      />
      <main className="eval rule-packs">
        <span className="label">Reusability · same engine, another rulebook</span>
        <h1 className="eval-title">Rule packs</h1>
        <p className="rules-lede">
          Praman's engine reads claims, gathers proof and decides verdicts. What counts as proof comes from a rule pack: one JSON file per
          rulebook. A new domain is a new file, not new code.
        </p>
        {error && (
          <div className="notice error" role="alert">
            Couldn't load the rule packs: {error}
          </div>
        )}
        {packs && (
          <div className="pack-grid">
            {packs.map((p) => (
              <button key={p.name} type="button" className={`pack-card${p.name === active ? " on" : ""}`} onClick={() => choose(p.name)} aria-pressed={p.name === active}>
                <span className={`pack-status mono ${p.status}`}>{p.status === "active" ? "RUNNING IN THE AGENT" : "LOADED · READY TO CONNECT"}</span>
                <b>{p.title}</b>
                <span className="note">{p.domain}</span>
                <span className="mono pack-meta">
                  {p.rules.length} rules · {p.sources.length} {p.sources.length === 1 ? "source" : "sources"}
                </span>
                <span className="note">{p.status_note}</span>
              </button>
            ))}
            <div className="pack-card ghost">
              <span className="pack-status mono">NEXT</span>
              <b>Your rulebook</b>
              <span className="note">Cosmetics labels, ad claims, ESG disclosures in loan files: same format, same engine.</span>
            </div>
          </div>
        )}

        {pack && (
          <section className="split" aria-label="Try a pack">
            <h2 className="split-title">
              Try {pack.title} <span className="label">trigger matching, in code, no model call</span>
            </h2>
            <textarea className="rules-try" value={text} onChange={(e) => setText(e.target.value)} rows={3} aria-label="Product text to try" />
            {hits.length === 0 ? (
              <p className="note">No rule in this pack is triggered by that text.</p>
            ) : (
              <ul className="rule-hits">
                {hits.map(({ rule, terms }) => (
                  <li key={rule.id}>
                    <b className="mono">{rule.id}</b>
                    <div>
                      <span className="rule-name">{rule.name}</span>
                      <span className="note">
                        Triggered by {terms.map((t) => `“${t}”`).join(", ")} · needs: {rule.evidence.join("; ") || "no proof (not a claim)"}
                      </span>
                      <span className="note">
                        {rule.source}
                        {rule.clause ? `, ${rule.clause}` : ""}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </main>
      <footer className="foot">
        <FooterLine />
      </footer>
    </div>
  );
}
