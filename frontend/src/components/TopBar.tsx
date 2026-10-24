// Top bar (DESIGN §4.2): seal + wordmark, breadcrumb, mode switch, status chips, actions.

import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Mode } from "../lib/events";
import { useApp } from "../AppContext";
import { Brand } from "./Seal";

export function TopBar({
  working = false,
  synthetic = false,
  quiet = false,
  showRole = false,
  crumb,
  children,
  actions,
}: {
  working?: boolean;
  synthetic?: boolean;
  /** home page: no server status chips, except RECORDING when the app plays recordings */
  quiet?: boolean;
  /** the Analyst/Reviewer switch: only where the role changes something (the Report) */
  showRole?: boolean;
  crumb?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="top">
      <Link to="/" className="brand-link" aria-label="Praman home">
        <Brand spinning={working} />
      </Link>
      {crumb && <nav className="crumb" aria-label="Breadcrumb">{crumb}</nav>}
      {children}
      <div className="spacer" />
      {showRole && <RoleSwitch />}
      <StatusChips synthetic={synthetic} quiet={quiet} />
      {actions}
    </header>
  );
}

/** Only the chips a viewer needs: RECORDING when the app plays recordings (no server), and
 * SYNTHETIC on a made-up case. The server's model mode and anonymising stay out of the way. */
export function StatusChips({ synthetic = false }: { synthetic?: boolean; quiet?: boolean }) {
  const { backend } = useApp();
  const recording = backend?.kind === "recording";
  if (!recording && !synthetic) return null;
  return (
    <div className="chips">
      {recording && (
        <span className="chip warn" title={backend.reason}>
          RECORDING
        </span>
      )}
      {synthetic && <span className="chip warn">SYNTHETIC</span>}
    </div>
  );
}

/** Analysts run checks; only a Reviewer can decide a claim or sign a report. */
export function RoleSwitch() {
  const { role, setRole } = useApp();
  return (
    <div className="seg role-switch" role="radiogroup" aria-label="Role" title="Analysts run checks. Only a Reviewer can decide a claim or sign the report.">
      {(["analyst", "reviewer"] as const).map((r) => (
        <button key={r} type="button" role="radio" aria-checked={role === r} className={role === r ? "on" : ""} onClick={() => role !== r && setRole(r)}>
          {r.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function ModeSwitch({ mode, onChange }: { mode: Mode | null; onChange: (m: Mode) => void }) {
  return (
    <div className="seg" role="radiogroup" aria-label="Mode">
      {(["agent", "baseline"] as const).map((m) => (
        <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? "on" : ""} onClick={() => mode !== m && onChange(m)}>
          {m === "agent" ? "AGENT" : "TEXT-ONLY"}
        </button>
      ))}
    </div>
  );
}
