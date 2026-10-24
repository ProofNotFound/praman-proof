// Source → pacer → reducer for one case. Live runs stream over SSE; recordings are loaded whole.
// Both go through the same pacer and reducer (DESIGN §7).

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { fetchRunRecording, loadRecording, streamRun, type Backend, type CaseRef } from "./api";
import type { Mode, PramanEvent } from "./events";
import { Pacer, type PacerSnapshot, type Speed } from "./pacer";
import { initialState, reduceAll, type CaseState } from "./reducer";

export interface CaseMeta {
  source: "live" | "recording";
  synthetic: boolean;
  listingId: string | null;
  mode: Mode | null;
  runId: string | null;
  recordedAt: string | null;
  title: string | null;
}

type Action = { kind: "events"; events: PramanEvent[] } | { kind: "reset" };

function caseReducer(state: CaseState, action: Action): CaseState {
  return action.kind === "reset" ? initialState : reduceAll(action.events, state);
}

const IDLE: PacerSnapshot = { released: 0, total: 0, paused: false, speed: 1, ended: false };

export interface CasePlayback {
  state: CaseState;
  meta: CaseMeta | null;
  pacer: Pacer<PramanEvent> | null;
  snap: PacerSnapshot;
  loadError: string | null;
  restart: () => void;
}

/**
 * `ref` null means "not resolved yet" (a live case file waiting for its run id).
 * In present mode each case starts paused once the listing is on screen.
 */
export function useCasePlayback(
  backend: Backend | null,
  ref: CaseRef | null,
  opts: { speed: Speed; present: boolean },
): CasePlayback {
  const [state, dispatch] = useReducer(caseReducer, initialState);
  const [meta, setMeta] = useState<CaseMeta | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pacer, setPacer] = useState<Pacer<PramanEvent> | null>(null);
  const presentRef = useRef(opts.present);
  presentRef.current = opts.present;
  const speedRef = useRef(opts.speed);
  speedRef.current = opts.speed;

  const key = ref ? (ref.kind === "file" ? `file:${ref.listingId}.${ref.mode}${ref.bundled ? ".rec" : ""}` : `run:${ref.runId}`) : null;

  useEffect(() => {
    if (!backend || !ref || !key) return;
    dispatch({ kind: "reset" });
    setMeta(null);
    setLoadError(null);
    const present = presentRef.current;
    const p = new Pacer<PramanEvent>({
      onRelease: (events) => dispatch({ kind: "events", events }),
      onReset: () => dispatch({ kind: "reset" }),
      speed: speedRef.current,
      paused: present,
    });
    let primed = !present;
    const prime = () => {
      // Present mode: show the listing, then wait for the presenter.
      if (!primed && p.events.some((e) => e.type === "listing")) {
        primed = true;
        p.releaseThrough("listing");
      }
    };
    setPacer(p);
    let cancelled = false;
    let stop: (() => void) | null = null;

    if (ref.kind === "file" && (backend.kind === "recording" || ref.bundled)) {
      loadRecording(ref.listingId, ref.mode)
        .then((rec) => {
          if (cancelled) return;
          setMeta({
            source: "recording",
            synthetic: rec.synthetic,
            listingId: rec.listing_id,
            mode: rec.mode,
            runId: rec.run_id ?? null,
            recordedAt: rec.recorded_at,
            title: rec.title,
          });
          p.push(...rec.events);
          p.end();
          prime();
        })
        .catch((err: unknown) => !cancelled && setLoadError(errorText(err)));
    } else if (ref.kind === "run" && backend.kind === "live") {
      setMeta({ source: "live", synthetic: false, listingId: null, mode: null, runId: ref.runId, recordedAt: null, title: null });
      // A replayed run streams its events in a burst; hand them to the pacer a tick at a time
      // rather than one render per event.
      let inbox: PramanEvent[] = [];
      let tick: ReturnType<typeof setTimeout> | null = null;
      const drain = () => {
        tick = null;
        if (cancelled || inbox.length === 0) return;
        const batch = inbox;
        inbox = [];
        p.push(...batch);
        prime();
      };
      stop = streamRun(ref.runId, {
        onEvent: (e) => {
          if (cancelled) return;
          inbox.push(e);
          tick ??= setTimeout(drain, 0);
        },
        onEnd: () => {
          drain();
          p.end();
        },
        onError: (msg) => !cancelled && setLoadError(msg),
      });
    } else if (ref.kind === "run" && backend.kind === "recording") {
      setLoadError("This run lives on the Praman server, which isn't reachable. Open a recorded case instead.");
    }
    return () => {
      cancelled = true;
      stop?.();
      p.dispose();
    };
  }, [backend, key]); // `key` stands for `ref`

  useEffect(() => {
    pacer?.setSpeed(opts.speed);
  }, [pacer, opts.speed]);

  // Not useSyncExternalStore: its updates are synchronous, and a burst of events would chain
  // dozens of sync renders. An ordinary state update batches with the reducer's.
  const [snap, setSnap] = useState<PacerSnapshot>(IDLE);
  useEffect(() => {
    if (!pacer) {
      setSnap(IDLE);
      return;
    }
    setSnap(pacer.getSnapshot());
    return pacer.subscribe(() => setSnap(pacer.getSnapshot()));
  }, [pacer]);

  const restart = useCallback(() => {
    if (!pacer) return;
    const present = presentRef.current;
    pacer.restart({ paused: present });
    if (present) pacer.releaseThrough("listing");
  }, [pacer]);

  return { state, meta, pacer, snap, loadError, restart };
}

/** A whole run, reduced at once (for Compare and the Report). */
export async function loadFullCase(backend: Backend, ref: CaseRef): Promise<{ state: CaseState; meta: CaseMeta }> {
  if (ref.kind === "file") {
    const rec = backend.kind === "recording" || ref.bundled ? await loadRecording(ref.listingId, ref.mode) : null;
    if (!rec) throw new Error("Resolve the case file to a run first.");
    return {
      state: reduceAll(rec.events),
      meta: {
        source: "recording",
        synthetic: rec.synthetic,
        listingId: rec.listing_id,
        mode: rec.mode,
        runId: rec.run_id ?? null,
        recordedAt: rec.recorded_at,
        title: rec.title,
      },
    };
  }
  if (backend.kind === "recording") {
    throw new Error("This run lives on the Praman server, which isn't reachable. Open a recorded case instead.");
  }
  const rec = await fetchRunRecording(ref.runId);
  return {
    state: reduceAll(rec.events),
    meta: {
      source: "live",
      synthetic: rec.synthetic,
      listingId: rec.listing_id,
      mode: rec.mode,
      runId: ref.runId,
      recordedAt: rec.recorded_at,
      title: rec.title,
    },
  };
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong.";
}
