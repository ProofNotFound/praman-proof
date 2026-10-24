// Shared UI state of the case screen: what's hovered (to dim everything not connected to it,
// DESIGN §5.3) and which photo the exhibit shows.

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export interface Focus {
  /** a claim id, an evidence card key, or one thread (claim id + card key) */
  kind: "claim" | "card" | "link";
  id: string;
  card?: string;
}

interface CaseUi {
  focus: Focus | null;
  setFocus: (f: Focus | null) => void;
  photo: number | null;
  setPhoto: (n: number | null) => void;
}

const Ctx = createContext<CaseUi>({ focus: null, setFocus: () => {}, photo: null, setPhoto: () => {} });

export function CaseUiProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<Focus | null>(null);
  const [photo, setPhoto] = useState<number | null>(null);
  const value = useMemo(() => ({ focus, setFocus, photo, setPhoto }), [focus, photo]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useCaseUi = (): CaseUi => useContext(Ctx);
