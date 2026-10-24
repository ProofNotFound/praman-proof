// Store scan (TRD §15.7): a store's product pages ranked by how much their green claims need
// checking. Triage, not a verdict: plain code, no model calls. Live mode runs /api/scans and
// polls it; without a backend (or before a scan starts) it shows the recorded scan of an
// anonymised seed store.

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowRight } from "lucide-react";
import { useApp, useOpenCase } from "../AppContext";
import { ApiError, fetchRulePacks, startRun } from "../lib/api";
import type { RulePack } from "../lib/packs";
import {
  BAND_LABEL,
  PROOF_LABEL,
  bandCounts,
  fetchScan,
  loadDemoScan,
  startScan,
  type ScanResult,
  type TriageRow,
} from "../lib/scan";
import { errorText } from "../lib/useCase";
import { formatDate } from "../lib/view";
import { TopBar } from "../components/TopBar";
import { FooterLine, Seal } from "../components/Seal";
import { AccessCode } from "../components/AccessCode";

const POLL_MS = 1000;

export function ScanRoute() {
  const { scanId } = useParams();
  const { backend, demoCases } = useApp();
  const navigate = useNavigate();
  const openCase = useOpenCase();
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [rowMsg, setRowMsg] = useState<string | null>(null);
  const [packs, setPacks] = useState<RulePack[]>([]);
  const [pack, setPack] = useState("green_claims");

  const live = backend?.kind === "live";
  const canScan = live; // an offline server can still scan a store it has cached; it says so if not
  const recorded = !scanId;

  // The rulebooks a live scan can use (the same engine triages with any of them)
  useEffect(() => {
    if (backend?.kind !== "live") return;
    let alive = true;
    fetchRulePacks(backend)
      .then((p) => alive && setPacks(p))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [backend]);

  // The recorded scan, or a live scan polled until it finishes.
  useEffect(() => {
    if (!backend) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setError(null);
    setScan(null);
    if (!scanId) {
      loadDemoScan()
        .then((s) => alive && setScan(s))
        .catch((e: unknown) => alive && setError(errorText(e)));
    } else if (!live) {
      setError("This scan lives on the Praman server, which isn't reachable. The recorded scan is below.");
      loadDemoScan()
        .then((s) => alive && setScan(s))
        .catch(() => undefined);
    } else {
      const poll = () =>
        fetchScan(scanId)
          .then((s) => {
            if (!alive) return;
            setScan(s);
            if (s.status === "running") timer = setTimeout(poll, POLL_MS);
          })
          .catch((e: unknown) => alive && setError(errorText(e)));
      void poll();
    }
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [backend, scanId, live]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (!url.trim()) {
      setError("Paste a store's address first.");
      return;
    }
    if (!canScan) {
      setError("Store scans need the Praman server, which isn't running here. The recorded scan is below.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const id = await startScan(url.trim(), pack);
      navigate(`/scan/${encodeURIComponent(id)}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const hasCase = (id: string | null): id is string => !!id && demoCases.some((c) => c.listingId === id);

  const check = async (row: TriageRow) => {
    setRowMsg(null);
    try {
      if (scanId && live) {
        const runId = await startRun({ scan_id: scanId, product: row.product, mode: "agent" });
        navigate(`/case/${encodeURIComponent(runId)}`);
      } else if (row.listing_id) {
        await openCase(row.listing_id);
      }
    } catch (err) {
      setRowMsg(err instanceof ApiError || err instanceof Error ? err.message : "Couldn't start the check.");
    }
  };

  const counts = scan ? bandCounts(scan.rows) : null;
  const running = scan?.status === "running";

  return (
    <div className="screen scan-screen">
      <TopBar
        working={running}
        crumb={
          <>
            <Link to="/">CASES</Link> / <b>STORE SCAN</b>
          </>
        }
        actions={
          <Link className="btn" to="/eval">
            Evaluation
          </Link>
        }
      />
      <main className="scan">
        <span className="label">Store scan · triage, not a verdict</span>
        <h1 className="scan-title">Which product pages need checking first?</h1>
        <p className="lede">
          Praman reads a store's product pages and ranks them by the green-claim terms they use and the proof they show. Plain code: no model
          calls and no verdicts. A high place means "check this page first", not that a claim is wrong.
        </p>

        <form className="url-form" onSubmit={submit}>
          <label htmlFor="store-url" className="label">
            Store address
          </label>
          <div className="url-row">
            <input
              id="store-url"
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              placeholder="https://store.example"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <button type="submit" className="btn solid" disabled={busy || !backend}>
              {busy ? "Starting…" : "Scan store"} <ArrowRight size={16} strokeWidth={1.5} aria-hidden="true" />
            </button>
          </div>
          {packs.length > 1 && (
            <div className="pack-pick">
              <label htmlFor="scan-pack" className="label">
                Rulebook
              </label>
              <select id="scan-pack" value={pack} onChange={(e) => setPack(e.target.value)}>
                {packs.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.title} · {p.domain}
                  </option>
                ))}
              </select>
            </div>
          )}
          {backend?.kind === "live" && backend.health.needs_access_code === true && (
            <AccessCode id="scan-access-code" />
          )}
          <p className="note">
            {canScan
              ? "Shopify stores: up to 100 products from /products.json; other stores: up to 50 product pages from the sitemap, one request a second."
              : "Live scans need the Praman server. Below: a recorded scan of an anonymised store."}
          </p>
        </form>

        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}

        {!scan && !error && (
          <div className="skeleton" aria-busy="true">
            <i style={{ width: "60%" }} />
            <i style={{ width: "80%" }} />
            <i style={{ width: "40%" }} />
          </div>
        )}

        {scan && (
          <section className="scan-result" aria-label="Scan result">
            <div className="scan-status">
              {running && <Seal spinning size={30} />}
              <span className="mono">
                {scan.store.toUpperCase()} · {scan.total} {scan.total === 1 ? "PRODUCT" : "PRODUCTS"}
                {scan.source ? ` FROM ${scan.source === "shopify" ? "/PRODUCTS.JSON" : "THE SITEMAP"}` : ""} · {scan.model_calls} MODEL
                CALLS
                {scan.pack && scan.pack !== "green_claims"
                  ? ` · RULEBOOK ${(packs.find((p) => p.name === scan.pack)?.title ?? scan.pack).toUpperCase()}`
                  : ""}
                {recorded && scan.recorded_at ? ` · RECORDED ${formatDate(scan.recorded_at).toUpperCase()}` : ""}
              </span>
              <span className="chip">{scan.label.toUpperCase()}</span>
            </div>
            {running && (
              <div className="scan-progress" role="status">
                <span>
                  Read {scan.done} of {scan.total || "…"} product pages
                </span>
                <span className="bar" aria-hidden="true">
                  <i style={{ width: `${scan.total ? Math.round((100 * scan.done) / scan.total) : 0}%` }} />
                </span>
              </div>
            )}
            {scan.status === "error" && (
              <div className="notice error" role="alert">
                {scan.message ?? "The scan stopped."}
              </div>
            )}
            {counts && scan.rows.length > 0 && (
              <p className="scan-counts">
                {(["high", "medium", "low", "none"] as const).map((b) => (
                  <span key={b} className={`band band-${b}`}>
                    <b>{counts[b]}</b> {BAND_LABEL[b].toLowerCase()}
                  </span>
                ))}
              </p>
            )}
            {rowMsg && (
              <div className="notice" role="status">
                {rowMsg}
              </div>
            )}
            {scan.rows.length > 0 && (
              <table className="scan-table">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Product and why</th>
                    <th scope="col">Needs checking</th>
                    <th scope="col">Claim terms</th>
                    <th scope="col">Proof signals</th>
                    <th scope="col">
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {scan.rows.map((r) => (
                    <Row
                      key={r.product}
                      row={r}
                      max={Math.max(1, ...scan.rows.map((x) => x.score))}
                      action={
                        scanId && live ? (
                          <button type="button" className="btn" onClick={() => void check(r)} disabled={!!r.error}>
                            Check this product
                          </button>
                        ) : hasCase(r.listing_id) ? (
                          <button type="button" className="btn" onClick={() => void check(r)}>
                            Open case {r.listing_id}
                          </button>
                        ) : (
                          <span className="muted mono">{live ? "Scan the store to check it" : "Needs the server"}</span>
                        )
                      }
                    />
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )}
      </main>
      <footer className="foot">
        <FooterLine />
        <span className="keys">Triage ranks pages to check; only a full check gives verdicts</span>
      </footer>
    </div>
  );
}

/** The rule a term points to most: the registry rules (R07, R09) when they apply. */
function mainRule(ids: string[]): string {
  return ids.find((r) => r === "R07" || r === "R09") ?? ids[0] ?? "";
}

function Row({ row, max, action }: { row: TriageRow; max: number; action: ReactNode }) {
  return (
    <tr className={`band-row band-${row.band}`}>
      <td className="mono rank">{row.rank}</td>
      <td className="prod">
        <span className="prod-title">{row.title}</span>
        <ul className="reasons">
          {row.reasons.slice(0, 3).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
          {row.reasons.length > 3 && <li className="more">+{row.reasons.length - 3} more</li>}
        </ul>
        {row.error && <span className="muted">{row.error}</span>}
      </td>
      <td className="need">
        <span className="score mono">{row.score}</span>
        <span className="meter" aria-hidden="true">
          <i style={{ width: `${Math.round((100 * row.score) / max)}%` }} />
        </span>
        <span className="band-tag mono">{BAND_LABEL[row.band]}</span>
      </td>
      <td className="terms">
        {row.terms.slice(0, 6).map((t) => (
          <span key={t.term} className={`term-chip kind-${t.kind}`} title={t.snippet}>
            {t.term} <span className="rid">{mainRule(t.rule_ids)}</span>
          </span>
        ))}
        {row.terms.length > 6 && <span className="muted mono">+{row.terms.length - 6}</span>}
        {row.terms.length === 0 && <span className="muted">—</span>}
      </td>
      <td className="proof">
        {row.proof.map((p, i) => (
          <span key={i} className="proof-chip" title={p.text}>
            {PROOF_LABEL[p.kind]}: {p.text}
          </span>
        ))}
        {row.proof.length === 0 && <span className="muted">None found</span>}
      </td>
      <td className="act">{action}</td>
    </tr>
  );
}
