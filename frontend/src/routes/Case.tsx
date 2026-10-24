// The Case screen (DESIGN §4.2): Exhibit · Board · Trace, with the director bar.

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { FileText, SplitSquareHorizontal } from "lucide-react";
import { useApp, useOpenCase } from "../AppContext";
import { fileCaseId, hasRecording, modeName, parseCaseId, recordedCaseId, resolveRun, type CaseRef } from "../lib/api";
import type { Mode } from "../lib/events";
import { isWorking } from "../lib/reducer";
import { useCasePlayback } from "../lib/useCase";
import { useElapsed } from "../hooks/useElapsed";
import { useKeys } from "../hooks/useKeys";
import { TopBar, ModeSwitch } from "../components/TopBar";
import { Exhibit } from "../components/Exhibit";
import { Board } from "../components/Board";
import { Trace } from "../components/Trace";
import { DirectorBar } from "../components/DirectorBar";
import { CaseUiProvider } from "../components/caseUi";
import { FooterLine } from "../components/Seal";
import { CaseOverlays } from "../components/Overlays";
import { CompareSplit } from "../components/CompareSplit";

export function CaseRoute() {
  const { caseId = "" } = useParams();
  const { backend } = useApp();
  const navigate = useNavigate();
  const parsed = parseCaseId(caseId);
  const [resolveError, setResolveError] = useState<string | null>(null);

  // Live mode: a case file ("L14.agent") means the latest run of that listing and mode.
  const needsResolve = backend?.kind === "live" && parsed.kind === "file" && !parsed.bundled;
  useEffect(() => {
    if (!needsResolve || parsed.kind !== "file") return;
    let alive = true;
    setResolveError(null);
    resolveRun(parsed.listingId, parsed.mode)
      .then((runId) => alive && navigate(`/case/${encodeURIComponent(runId)}`, { replace: true }))
      .catch((e: unknown) => alive && setResolveError(e instanceof Error ? e.message : "Couldn't open that case."));
    return () => {
      alive = false;
    };
  }, [needsResolve, caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  const ref: CaseRef | null = backend && !needsResolve ? parsed : null;
  return (
    <CaseUiProvider key={caseId}>
      <CaseScreen caseRef={ref} caseId={caseId} resolveError={resolveError} />
    </CaseUiProvider>
  );
}

function CaseScreen({ caseRef, caseId, resolveError }: { caseRef: CaseRef | null; caseId: string; resolveError: string | null }) {
  const app = useApp();
  const { backend, present, speed, setShortcuts, role } = app;
  const navigate = useNavigate();
  const openCase = useOpenCase();
  const { state, meta, pacer, snap, loadError, restart } = useCasePlayback(backend, caseRef, { speed, present });
  const [compare, setCompare] = useState(false);

  const working = isWorking(state) && !snap.paused;
  const elapsed = useElapsed(isWorking(state) && !snap.paused && snap.released > 0, `${caseId}:${snap.released === 0}`);
  const listingId = state.listingId ?? meta?.listingId ?? (caseRef?.kind === "file" ? caseRef.listingId : null);
  const mode: Mode | null = state.mode ?? meta?.mode ?? (caseRef?.kind === "file" ? caseRef.mode : null);
  const llmMode = backend?.kind === "live" ? backend.health.llm_mode : null;
  const showDirector = present || backend?.kind === "recording" || llmMode !== "live";

  // A case file id works in both modes (live resolves it to the latest run).
  const bundled = caseRef?.kind === "file" && caseRef.bundled === true;
  const switchMode = (m: Mode) => listingId && navigate(`/case/${bundled ? recordedCaseId(listingId, m) : fileCaseId(listingId, m)}`);
  const reportPath = `/case/${encodeURIComponent(caseId)}/report`;

  useKeys({
    " ": () => pacer?.toggle(),
    ArrowRight: () => !compare && pacer?.step(),
    r: () => restart(),
    b: () => setCompare((c) => !c),
    e: () => navigate(reportPath),
    Escape: () => setCompare(false),
  });

  useEffect(() => {
    setCompare(false);
  }, [caseId]);

  const error = resolveError ?? loadError;

  // Demo safety: a live run that stops (or runs out of model quota) offers the shipped recording
  const [canFallback, setCanFallback] = useState(false);
  const failed = meta?.source === "live" && (error !== null || state.error !== null || state.finished?.quota_reached === true);
  useEffect(() => {
    setCanFallback(false);
    if (!failed || !listingId || !mode) return;
    let alive = true;
    void hasRecording(listingId, mode).then((ok) => alive && setCanFallback(ok));
    return () => {
      alive = false;
    };
  }, [failed, listingId, mode]);
  const fallback =
    canFallback && listingId && mode ? (
      <button type="button" className="btn solid" onClick={() => navigate(`/case/${recordedCaseId(listingId, mode)}`)}>
        Play the recorded run
      </button>
    ) : null;

  return (
    <div className={`screen case-screen${showDirector ? " with-director" : ""}`}>
      <TopBar
        working={working}
        synthetic={meta?.synthetic ?? false}
        crumb={
          <>
            <Link to="/">CASES</Link> / <b>{listingId ?? "…"}</b>
          </>
        }
        actions={
          <>
            <button type="button" className={`btn${compare ? " solid" : ""}`} onClick={() => setCompare((c) => !c)} aria-pressed={compare}>
              <SplitSquareHorizontal size={16} strokeWidth={1.5} aria-hidden="true" />
              Compare <kbd>B</kbd>
            </button>
            <Link className="btn solid" to={reportPath}>
              <FileText size={16} strokeWidth={1.5} aria-hidden="true" />
              {role === "reviewer" ? "Review & sign" : "Report"} <kbd>E</kbd>
            </Link>
          </>
        }
      >
        <ModeSwitch mode={mode} onChange={switchMode} />
      </TopBar>

      {error ? (
        <div className="case-error">
          <div className="notice error" role="alert">
            {error}
          </div>
          <div className="row-gap">
            {fallback}
            {app.demoCases.slice(0, 4).map((c) => (
              <button key={c.listingId} type="button" className="btn" onClick={() => openCase(c.listingId)}>
                Open case {c.listingId}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <main className="case">
          <Exhibit state={state} />
          <Board
            state={state}
            working={working}
            fallback={fallback}
            overlay={
              compare && listingId ? (
                <CompareSplit listingId={listingId} onClose={() => setCompare(false)} />
              ) : (
                <CaseOverlays state={state} upcoming={pacer?.upcoming ?? []} />
              )
            }
          />
          <Trace
            state={state}
            elapsedMs={elapsed}
            working={working}
            modeLabel={mode ? modeName(mode).toUpperCase() : "…"}
            llmLabel={backend?.kind === "live" ? (llmMode ?? "").toUpperCase() : "RECORDING"}
          />
        </main>
      )}

      {showDirector && pacer ? (
        <DirectorBar
          snap={snap}
          events={pacer.events}
          onToggle={() => pacer.toggle()}
          onStep={() => pacer.step()}
          onRestart={restart}
        />
      ) : (
        <footer className="foot">
          <FooterLine />
          <button type="button" className="keys" onClick={() => setShortcuts(true)}>
            <kbd>?</kbd> keys · <kbd>P</kbd> present
          </button>
        </footer>
      )}
    </div>
  );
}
