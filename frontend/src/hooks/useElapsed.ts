import { useEffect, useRef, useState } from "react";

/** Milliseconds spent running (paused time excluded); resets when `resetKey` changes. */
export function useElapsed(running: boolean, resetKey: unknown): number {
  const [ms, setMs] = useState(0);
  const acc = useRef(0);
  const since = useRef<number | null>(null);

  useEffect(() => {
    acc.current = 0;
    since.current = null;
    setMs(0);
  }, [resetKey]);

  useEffect(() => {
    if (!running) {
      if (since.current !== null) {
        acc.current += performance.now() - since.current;
        since.current = null;
        setMs(acc.current);
      }
      return;
    }
    since.current = performance.now();
    const id = setInterval(() => {
      if (since.current !== null) setMs(acc.current + performance.now() - since.current);
    }, 100);
    return () => {
      clearInterval(id);
      if (since.current !== null) {
        acc.current += performance.now() - since.current;
        since.current = null;
      }
    };
  }, [running]);

  return ms;
}
