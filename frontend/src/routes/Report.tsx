// The Report (DESIGN §4.3): an A4 dossier, print-ready. A reviewer decides each claim the agent
// left open and signs the report; signing gates Export. Every decision lands in the decision log.

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, Download, Printer } from "lucide-react";
import { useApp } from "../AppContext";
import {
  approveRun,
  fetchRun,
  getReviewerKey,
  parseCaseId,
  provenanceLine,
  reportMdUrl,
  resolveRun,
  reviewClaim,
  reviewerAccess,
  setReviewerKey,
  startRun,
  type Audit,
} from "../lib/api";
import { VERDICT_LABELS, type Claim, type VerdictLabel } from "../lib/events";
import type { CaseState } from "../lib/reducer";
import { loadFullCase, errorText, type CaseMeta } from "../lib/useCase";
import { disclaimer, toMarkdown } from "../lib/markdown";
import {
  decisionLog,
  finalCounts,
  latestReviews,
  loadLocal,
  pendingReviews,
  reviewLine,
  saveLocal,
  type Approval,
  type Review,
} from "../lib/review";
import { evidenceCards, formatDate, formatDateTime, locationLabel } from "../lib/view";
import { TopBar } from "../components/TopBar";
import { Seal } from "../components/Seal";
import { QUOTA_LINE } from "../components/Board";
import { Stamp } from "../components/Stamp";
import { EvidenceCard } from "../components/EvidenceCard";
import { ImpactStrip } from "../components/ImpactStrip";

const ORDER: VerdictLabel[] = ["Backed", "Partly backed", "Not backed", "Contradicted", "Needs review", "Not a claim"];

export function ReportRoute() {
  const { caseId = "" } = useParams();
  const { backend } = useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<{ state: CaseState; meta: CaseMeta } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [audit, setAudit] = useState<Audit | null>(null);
  const ref = parseCaseId(caseId);

  useEffect(() => {
    if (!backend) return;
    let alive = true;
    setData(null);
    setError(null);
    setApproval(null);
    setReviews([]);
    setAudit(null);
    (async () => {
      if (backend.kind === "live" && ref.kind === "file" && !ref.bundled) {
        const runId = await resolveRun(ref.listingId, ref.mode);
        if (alive) navigate(`/case/${encodeURIComponent(runId)}/report`, { replace: true });
        return;
      }
      const full = await loadFullCase(backend, ref);
      if (!alive) return;
      setData(full);
      if (backend.kind === "live" && ref.kind === "run") {
        const detail = await fetchRun(ref.runId).catch(() => null);
        if (!alive || !detail) return;
        setReviews(detail.reviews);
        setAudit(detail.audit);
        if (detail.run.approved_by && detail.run.approved_at) setApproval({ name: detail.run.approved_by, at: detail.run.approved_at });
      } else {
        const local = loadLocal(caseId);
        setReviews(local.reviews);
        setApproval(local.approval);
      }
    })().catch((e: unknown) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [backend, caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  const listingId = data?.state.listingId ?? (ref.kind === "file" ? ref.listingId : null);
  return (
    <div className="screen report-screen">
      <TopBar
        showRole={!approval}
        crumb={
          <>
            <Link to="/">CASES</Link> / <Link to={`/case/${encodeURIComponent(caseId)}`}>{listingId ?? "…"}</Link> / <b>REPORT</b>
          </>
        }
        actions={
          <Link className="btn" to={`/case/${encodeURIComponent(caseId)}`}>
            <ArrowLeft size={16} strokeWidth={1.5} aria-hidden="true" /> Back to the case
          </Link>
        }
      />
      <main className="report">
        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}
        {!data && !error && (
          <div className="page skeleton-page" aria-busy="true">
            <div className="skeleton">
              <i style={{ width: "60%" }} />
              <i style={{ width: "85%" }} />
              <i style={{ width: "40%" }} />
            </div>
          </div>
        )}
        {data && (
          <Dossier
            state={data.state}
            meta={data.meta}
            caseId={caseId}
            approval={approval}
            reviews={reviews}
            audit={audit}
            onReviewed={(r) => {
              const next = [...reviews, r];
              setReviews(next);
              if (data.meta.source !== "live") saveLocal(caseId, next, approval);
            }}
            onApproved={(a) => {
              setApproval(a);
              if (data.meta.source !== "live") saveLocal(caseId, reviews, a);
              else if (data.meta.runId) {
                // the server stored the sign-off fingerprint: show it
                void fetchRun(data.meta.runId)
                  .then((d) => d && setAudit(d.audit))
                  .catch(() => {});
              }
            }}
            onReset={() => {
              // recording mode: decisions live in this tab, so starting over clears them
              saveLocal(caseId, [], null);
              setReviews([]);
              setApproval(null);
            }}
          />
        )}
      </main>
    </div>
  );
}

function Dossier({
  state,
  meta,
  caseId,
  approval,
  reviews,
  audit,
  onReviewed,
  onApproved,
  onReset,
}: {
  state: CaseState;
  meta: CaseMeta;
  caseId: string;
  approval: Approval | null;
  reviews: Review[];
  audit: Audit | null;
  onReviewed: (r: Review) => void;
  onApproved: (a: Approval) => void;
  onReset: () => void;
}) {
  const { backend, role } = useApp();
  const cards = useMemo(() => evidenceCards(state), [state]);
  const latest = useMemo(() => latestReviews(reviews), [reviews]);
  const counts = finalCounts(state, latest);
  const pending = pendingReviews(state, latest);
  const when = state.startedAt ?? meta.recordedAt;
  const caseLabel = `${state.listingId ?? meta.listingId ?? "?"}${state.mode === "baseline" ? " · TEXT-ONLY" : ""}`;
  const live = backend?.kind === "live" && meta.source === "live" && meta.runId !== null;
  const access = live ? reviewerAccess(backend) : "role";
  const canDecide = role === "reviewer" && !approval && access !== "off";

  // The printed PDF takes its file name from the page title
  useEffect(() => {
    const before = document.title;
    document.title = `Praman proof report – ${caseLabel}`;
    return () => {
      document.title = before;
    };
  }, [caseLabel]);

  return (
    <article className="page" aria-label="Proof report">
      <header className="dossier-head">
        <Seal size={54} />
        <div>
          <div className="dossier-kicker">
            <span className="deva">प्रमाण</span> · Proof report{approval ? "" : " · Draft"}
          </div>
          <h1>{state.listing?.title ?? meta.title}</h1>
          <div className="dossier-meta mono">
            <span>CASE {caseLabel}</span>
            {state.listing?.store && <span>{state.listing.store}</span>}
            <span>{formatDateTime(when)}</span>
            <span>MODEL ANSWERS: {(state.llmMode ?? "unknown").toUpperCase()}</span>
            {meta.source === "recording" && <span>RECORDED RUN</span>}
            {meta.synthetic && <span>SYNTHETIC</span>}
          </div>
        </div>
      </header>

      <section className="dossier-summary" aria-label="Summary">
        <h2 className="label">Summary</h2>
        <div className="summary-stamps">
          {ORDER.filter((l) => counts[l]).map((l) => (
            <span key={l} className="summary-item">
              <Stamp label={l} size="sm" />
              <b className="mono">×{counts[l]}</b>
            </span>
          ))}
          {state.claims.length === 0 && <span className="muted">No claims on this page.</span>}
        </div>
        {state.finished?.quota_reached && <p className="muted">{QUOTA_LINE}</p>}
        <ImpactStrip state={state} />
      </section>

      {approval && <SignedBanner approval={approval} live={live} state={state} onReset={onReset} />}
      {role === "reviewer" && !approval && <ReviewerBar access={access} />}

      {state.claims.map((c) => {
        const v = state.verdicts[c.id];
        const r = latest[c.id];
        const label = r?.label ?? v?.label;
        const mine = cards.filter((card) => card.links.some((l) => l.claimId === c.id));
        const ruleIds = v?.rules?.length ? v.rules.map((x) => x.id) : c.rule_ids;
        return (
          <section key={c.id} className="dossier-claim">
            <div className="dc-head">
              <span className="cid">
                {c.id} · {locationLabel(c)}
                {c.derived_from ? ` · from ${c.derived_from}` : ""} · {c.type.toUpperCase()} · {c.scope.toUpperCase()}
              </span>
              <span className="dc-stamps">
                {r?.decision === "change" && v && <span className="ai-label mono">AGENT: {v.label.toUpperCase()}</span>}
                {label && <Stamp label={label} size="sm" />}
              </span>
            </div>
            <blockquote className="quote">“{c.quote}”</blockquote>
            <p className="reason">{v?.reason ?? c.not_claim_reason ?? "No verdict."}</p>
            {v?.missing && v.label !== "Backed" && v.label !== "Not a claim" && <p className="missing">{v.missing}</p>}
            {mine.length > 0 && (
              <div className="dc-evidence">
                {mine.map((card) => (
                  <EvidenceCard key={card.key} card={card} state={state} fresh={false} dim={false} lit={false} onFocus={() => {}} />
                ))}
              </div>
            )}
            {ruleIds.length > 0 && (
              <ul className="dc-rules">
                {ruleIds.map((id) => {
                  const rule = state.rules[id];
                  return (
                    <li key={id}>
                      <b className="mono">{id}</b>{" "}
                      {rule ? `${rule.name}. ${rule.source}${rule.clause && !/to be confirmed/i.test(rule.clause) ? `, ${rule.clause}` : ""}.` : ""}
                    </li>
                  );
                })}
              </ul>
            )}
            {v?.rewrite && v.label !== "Backed" && v.label !== "Not a claim" && (
              <p className="dc-rewrite">
                <span className="label">Suggested wording</span>
                {v.rewrite}
              </p>
            )}
            {v && (
              <ClaimReview
                claim={c}
                aiLabel={v.label}
                review={r ?? null}
                canDecide={canDecide}
                analyst={role === "analyst" && !approval}
                live={live}
                runId={meta.runId}
                onReviewed={onReviewed}
              />
            )}
          </section>
        );
      })}

      <Approve
        state={state}
        caseLabel={caseLabel}
        when={when}
        caseId={caseId}
        live={live}
        runId={meta.runId}
        approval={approval}
        reviews={reviews}
        pending={pending}
        onApproved={onApproved}
      />

      <DecisionLog state={state} reviews={reviews} approval={approval} />
      {live && audit && <AuditBlock audit={audit} />}

      <footer className="disclaimer">{disclaimer(formatDate(when))}</footer>
    </article>
  );
}

/** A signed report is closed: say so, and offer a fresh check to review. */
function SignedBanner({ approval, live, state, onReset }: { approval: Approval; live: boolean; state: CaseState; onReset: () => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const again = async () => {
    if (!live) {
      onReset();
      return;
    }
    if (!state.listingId) return;
    setBusy(true);
    setError(null);
    try {
      const runId = await startRun({ listing_id: state.listingId, mode: state.mode ?? "agent" });
      navigate(`/case/${encodeURIComponent(runId)}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };
  return (
    <div className="notice signed-banner no-print" role="status">
      <span>
        Signed by <b>{approval.name}</b> on {formatDateTime(approval.at)}. A signed report is closed to changes, so the Analyst / Reviewer
        switch is hidden.{error ? ` ${error}` : ""}
      </span>
      <button type="button" className="btn" onClick={() => void again()} disabled={busy}>
        {busy ? "Starting…" : live ? "Check this page again" : "Start the review over"}
      </button>
    </div>
  );
}

/** The reviewer's name, asked once (it signs every decision and the report). With named reviewer
 * keys on the server, the key is asked for too and the server signs with the key's name. */
function ReviewerBar({ access }: { access: ReturnType<typeof reviewerAccess> }) {
  const { reviewerName, setReviewerName } = useApp();
  const [key, setKey] = useState(getReviewerKey);
  if (access === "off") {
    return (
      <div className="reviewer-bar no-print">
        <span className="note">
          Sign-off is off on this public server: no reviewer keys are set up. Anyone can follow the check and read the report, but only a named
          reviewer can decide claims or sign.
        </span>
      </div>
    );
  }
  return (
    <div className="reviewer-bar no-print">
      <label htmlFor="reviewer" className="label">
        Reviewing as
      </label>
      <input
        id="reviewer"
        value={reviewerName}
        onChange={(e) => setReviewerName(e.target.value)}
        placeholder="Reviewer's name"
        maxLength={80}
        autoComplete="name"
      />
      {access === "key" && (
        <>
          <label htmlFor="reviewer-key" className="label">
            Reviewer key
          </label>
          <input
            id="reviewer-key"
            type="password"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setReviewerKey(e.target.value);
            }}
            placeholder="Your key"
            maxLength={200}
            autoComplete="off"
          />
        </>
      )}
      <span className="note">
        Agree with each verdict or change it with a reason. Claims marked Needs review must be decided before sign-off.
        {access === "key" ? " The server signs with the name tied to your key." : ""}
      </span>
    </div>
  );
}

function ClaimReview({
  claim,
  aiLabel,
  review,
  canDecide,
  analyst,
  live,
  runId,
  onReviewed,
}: {
  claim: Claim;
  aiLabel: VerdictLabel;
  review: Review | null;
  canDecide: boolean;
  analyst: boolean;
  live: boolean;
  runId: string | null;
  onReviewed: (r: Review) => void;
}) {
  const { role, reviewerName } = useApp();
  const [changing, setChanging] = useState(false);
  const [label, setLabel] = useState<VerdictLabel | "">("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = reviewerName.trim();
  const open = aiLabel === "Needs review" && !review;

  const decide = async (decision: Review["decision"]) => {
    if (!name) return;
    setError(null);
    const req = decision === "agree" ? { name, decision } : { name, decision, label: label || undefined, reason: reason.trim() };
    if (!live || !runId) {
      onReviewed({
        claim_id: claim.id,
        decision,
        label: decision === "agree" || !label ? aiLabel : label,
        ai_label: aiLabel,
        reason: req.reason ?? "",
        reviewer: name,
        at: new Date().toISOString(),
      });
      setChanging(false);
      return;
    }
    setBusy(true);
    try {
      onReviewed(await reviewClaim(runId, claim.id, req, role));
      setChanging(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const submitChange = (e: FormEvent) => {
    e.preventDefault();
    if (label && reason.trim()) void decide("change");
  };

  return (
    <div className={`dc-review${open ? " open" : ""}`}>
      {review && (
        <p className="dc-review-line">
          <span className="label">Human review</span>
          {reviewLine(review)} <span className="mono">{review.reviewer} · {formatDateTime(review.at)}</span>
        </p>
      )}
      {open && analyst && <p className="dc-review-line no-print">Needs a reviewer's decision before the report can be signed.</p>}
      {canDecide && !changing && (
        <div className="dc-review-actions no-print">
          {open && <span className="label">Needs a reviewer's decision</span>}
          <button type="button" className="btn" disabled={!name || busy || review?.decision === "agree"} onClick={() => void decide("agree")}>
            Agree with {aiLabel}
          </button>
          <button type="button" className="btn" disabled={!name || busy} onClick={() => setChanging(true)}>
            Change verdict
          </button>
          {!name && <span className="note">Enter your name above first.</span>}
        </div>
      )}
      {canDecide && changing && (
        <form className="dc-review-form no-print" onSubmit={submitChange}>
          <label className="label" htmlFor={`label-${claim.id}`}>
            New verdict
          </label>
          <select id={`label-${claim.id}`} value={label} onChange={(e) => setLabel(e.target.value as VerdictLabel)}>
            <option value="">Choose…</option>
            {VERDICT_LABELS.filter((l) => l !== aiLabel).map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <label className="label" htmlFor={`reason-${claim.id}`}>
            Why (required)
          </label>
          <textarea id={`reason-${claim.id}`} value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} />
          <div className="row-gap">
            <button type="submit" className="btn solid" disabled={!label || !reason.trim() || busy}>
              Save decision
            </button>
            <button type="button" className="btn" onClick={() => setChanging(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="notice error no-print" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function Approve({
  state,
  caseLabel,
  when,
  caseId,
  live,
  runId,
  approval,
  reviews,
  pending,
  onApproved,
}: {
  state: CaseState;
  caseLabel: string;
  when: string | null;
  caseId: string;
  live: boolean;
  runId: string | null;
  approval: Approval | null;
  reviews: Review[];
  pending: string[];
  onApproved: (a: Approval) => void;
}) {
  const { backend, role, reviewerName } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = reviewerName.trim();
  const off = live && reviewerAccess(backend) === "off";
  const blocked = role !== "reviewer" || pending.length > 0 || off;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name || blocked) return;
    setError(null);
    if (!live || !runId) {
      onApproved({ name, at: new Date().toISOString() });
      return;
    }
    setBusy(true);
    try {
      const run = await approveRun(runId, name, role);
      onApproved({ name: run.approved_by ?? name, at: run.approved_at ?? new Date().toISOString() });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const downloadLocal = () => {
    const md = toMarkdown(state, { caseLabel, when, approval, reviews });
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `praman-${caseId}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section className="approve" aria-label="Approval">
      {approval ? (
        <p className="signature">
          Reviewed and approved by <b>{approval.name}</b>
          <span className="mono">{formatDateTime(approval.at)}</span>
        </p>
      ) : (
        <form className="approve-form no-print" onSubmit={submit}>
          <span className="label">Sign-off</span>
          {off ? (
            <p className="note">Sign-off is off on this public server: only a named reviewer with a key can approve.</p>
          ) : role !== "reviewer" ? (
            <p className="note">Only a Reviewer can approve this report. Switch the role at the top.</p>
          ) : pending.length > 0 ? (
            <p className="note">
              {pending.length} {pending.length === 1 ? "claim needs" : "claims need"} a reviewer's decision first: {pending.join(", ")}.
            </p>
          ) : (
            <p className="note">Approving signs the report as {name || "…"} and unlocks export.</p>
          )}
          <button type="submit" className="btn solid" disabled={!name || blocked || busy}>
            {busy ? "Approving…" : "Approve report"}
          </button>
        </form>
      )}
      {error && (
        <p className="notice error no-print" role="alert">
          {error}
        </p>
      )}
      {!live && <p className="note no-print">Recording mode: decisions and the sign-off stay in this browser tab.</p>}
      <div className="export no-print">
        <button type="button" className="btn" disabled={!approval} onClick={() => window.print()}>
          <Printer size={16} strokeWidth={1.5} aria-hidden="true" /> Print / Save as PDF
        </button>
        {live && runId && approval ? (
          <a className="btn" href={reportMdUrl(runId)} download>
            <Download size={16} strokeWidth={1.5} aria-hidden="true" /> Download Markdown
          </a>
        ) : (
          <button type="button" className="btn" disabled={!approval} onClick={downloadLocal}>
            <Download size={16} strokeWidth={1.5} aria-hidden="true" /> Download Markdown
          </button>
        )}
        {!approval && <span className="note">Export unlocks after approval.</span>}
      </div>
    </section>
  );
}

/** The audit trail: what the agent decided and on what proof, then every human decision. */
function DecisionLog({ state, reviews, approval }: { state: CaseState; reviews: Review[]; approval: Approval | null }) {
  const log = decisionLog(state, reviews, approval);
  if (!log.length) return null;
  return (
    <section className="decision-log" aria-label="Decision log">
      <h2 className="label">Decision log</h2>
      <ol>
        {log.map((e, i) => (
          <li key={i} className={e.kind}>
            <span className="mono">{e.at ? formatDateTime(e.at) : ""}</span>
            <b>{e.who}</b>
            <span>{e.what}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** What the run was checked with, and whether the stored record still matches its signature. */
function AuditBlock({ audit }: { audit: Audit }) {
  return (
    <section className="decision-log audit" aria-label="Audit">
      <h2 className="label">Audit</h2>
      <ol>
        <li className="agent">
          <span className="mono">PROVENANCE</span>
          <b>Run</b>
          <span>{provenanceLine(audit.provenance)}</span>
        </li>
        {audit.reviews > 0 && (
          <li className="human">
            <span className="mono">REVIEW CHAIN</span>
            <b>{audit.reviews_intact ? "Intact" : "Broken"}</b>
            <span>
              {audit.reviews} {audit.reviews === 1 ? "decision" : "decisions"},{" "}
              {audit.reviews_intact ? "each one linked by hash to the one before." : "the chain doesn't match: compare with an exported copy."}
            </span>
          </li>
        )}
        {audit.fingerprint && (
          <li className="human">
            <span className="mono">FINGERPRINT</span>
            <b>{audit.fingerprint_matches ? "Matches" : "Changed"}</b>
            <span className="mono audit-hash">SHA-256 {audit.fingerprint}</span>
          </li>
        )}
      </ol>
    </section>
  );
}
