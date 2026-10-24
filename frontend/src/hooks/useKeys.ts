import { useEffect, useRef } from "react";

export type KeyMap = Record<string, (e: KeyboardEvent) => void>;

function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** Keyboard shortcuts by `KeyboardEvent.key` ("ArrowRight", " ", "b"…), ignored while typing. */
export function useKeys(map: KeyMap, enabled = true): void {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      const fn = ref.current[e.key.length === 1 ? e.key.toLowerCase() : e.key];
      if (!fn) return;
      // Space on a focused button should not also click it.
      if (e.key === " " && e.target instanceof HTMLButtonElement) e.preventDefault();
      e.preventDefault();
      fn(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
