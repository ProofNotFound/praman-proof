import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { useReducedMotion } from "motion/react";
import {
  assetUrl,
  detectBackend,
  fetchListings,
  fileCaseId,
  loadIndex,
  startRun,
  type Backend,
} from "./lib/api";
import type { Mode } from "./lib/events";
import type { Speed } from "./lib/pacer";
import type { Role } from "./lib/review";

export interface DemoCase {
  listingId: string;
  title: string;
  claimCount: number | null;
  thumb: string;
  role: string | null;
}

interface AppState {
  backend: Backend | null;
  present: boolean;
  setPresent: (v: boolean) => void;
  speed: Speed;
  setSpeed: (s: Speed) => void;
  shortcuts: boolean;
  setShortcuts: (v: boolean) => void;
  demoCases: DemoCase[];
  /** false under prefers-reduced-motion or at "instant" speed: skip all motion */
  motionOK: boolean;
  reducedMotion: boolean;
  /** animation durations multiply by this (1/speed) */
  timeScale: number;
  notice: string | null;
  setNotice: (s: string | null) => void;
  /** Analysts run checks; reviewers decide claims and sign reports (the server checks it too). */
  role: Role;
  setRole: (r: Role) => void;
  /** The reviewer's name, asked once and used on every decision and sign-off. */
  reviewerName: string;
  setReviewerName: (n: string) => void;
}

const Ctx = createContext<AppState | null>(null);

const ROLE_ORDER = ["normal", "failure", "ambiguous", "not_a_claim"];

function readSession<T>(key: string, fallback: T): T {
  try {
    const v = sessionStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

function writeSession(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode: per-tab state only */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [backend, setBackend] = useState<Backend | null>(null);
  const [present, setPresentState] = useState<boolean>(() => readSession("praman.present", false));
  const [speed, setSpeedState] = useState<Speed>(() => readSession<Speed>("praman.speed", 1));
  const [shortcuts, setShortcuts] = useState(false);
  const [demoCases, setDemoCases] = useState<DemoCase[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [role, setRoleState] = useState<Role>(() => (readSession<string>("praman.role", "analyst") === "reviewer" ? "reviewer" : "analyst"));
  const [reviewerName, setReviewerNameState] = useState<string>(() => readSession("praman.reviewerName", ""));
  const reducedMotion = useReducedMotion() ?? false;

  useEffect(() => {
    let alive = true;
    detectBackend().then((b) => {
      if (!alive) return;
      setBackend(b);
      if (b.kind === "recording") setNotice(b.reason);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!backend) return;
    let alive = true;
    const fromIndex = loadIndex()
      .then((index) =>
        index
          .filter((e) => e.mode === "agent")
          .map<DemoCase>((e) => ({
            listingId: e.listing_id,
            title: e.title,
            claimCount: e.claim_count,
            thumb: assetUrl(`demo/photos/${e.listing_id}/1.jpg`),
            role: null,
          })),
      )
      .catch(() => [] as DemoCase[]);
    if (backend.kind === "recording") {
      fromIndex.then((cases) => alive && setDemoCases(cases.slice(0, 4)));
    } else {
      Promise.all([fetchListings().catch(() => []), fromIndex]).then(([listings, recorded]) => {
        if (!alive) return;
        const demo = listings
          .filter((l) => l.demo_role)
          .sort((a, b) => ROLE_ORDER.indexOf(a.demo_role ?? "") - ROLE_ORDER.indexOf(b.demo_role ?? ""))
          .slice(0, 4)
          .map<DemoCase>((l) => ({
            listingId: l.id,
            title: l.title,
            claimCount: recorded.find((r) => r.listingId === l.id)?.claimCount ?? null,
            thumb: `/api/photos/${encodeURIComponent(l.id)}/1`,
            role: l.demo_role,
          }));
        setDemoCases(demo.length ? demo : recorded.slice(0, 4));
      });
    }
    return () => {
      alive = false;
    };
  }, [backend]);

  useEffect(() => {
    document.documentElement.classList.toggle("present", present);
  }, [present]);

  const setPresent = useCallback((v: boolean) => {
    setPresentState(v);
    writeSession("praman.present", v);
  }, []);
  const setSpeed = useCallback((s: Speed) => {
    setSpeedState(s);
    writeSession("praman.speed", s);
  }, []);
  const setRole = useCallback((r: Role) => {
    setRoleState(r);
    writeSession("praman.role", r);
  }, []);
  const setReviewerName = useCallback((n: string) => {
    setReviewerNameState(n);
    writeSession("praman.reviewerName", n);
  }, []);

  const value = useMemo<AppState>(
    () => ({
      backend,
      present,
      setPresent,
      speed,
      setSpeed,
      shortcuts,
      setShortcuts,
      demoCases,
      motionOK: !reducedMotion && speed !== "instant",
      reducedMotion,
      timeScale: speed === "instant" ? 0 : 1 / speed,
      notice,
      setNotice,
      role,
      setRole,
      reviewerName,
      setReviewerName,
    }),
    [backend, present, setPresent, speed, setSpeed, shortcuts, demoCases, reducedMotion, notice, role, setRole, reviewerName, setReviewerName],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

/** Open a case: a recorded case file, or (live) a fresh run of the listing. */
export function useOpenCase(): (listingId: string, mode?: Mode) => Promise<void> {
  const { backend, setNotice } = useApp();
  const navigate = useNavigate();
  return useCallback(
    async (listingId: string, mode: Mode = "agent") => {
      if (!backend) return;
      if (backend.kind === "recording") {
        navigate(`/case/${fileCaseId(listingId, mode)}`);
        return;
      }
      try {
        const runId = await startRun({ listing_id: listingId, mode });
        navigate(`/case/${encodeURIComponent(runId)}`);
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Couldn't start the run.");
      }
    },
    [backend, navigate, setNotice],
  );
}
