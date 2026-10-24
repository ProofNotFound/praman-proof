import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Clock } from "../src/lib/pacer";
import { validateRecording, type Recording } from "../src/lib/events";

export const DEMO = join(__dirname, "..", "public", "demo");

export function loadRecording(file: string): Recording {
  const r = validateRecording(JSON.parse(readFileSync(join(DEMO, file), "utf8")));
  if (!r.ok) throw new Error(r.error);
  return r.value;
}

/** A manual clock: timers fire only when the test advances time. */
export class FakeClock implements Clock {
  t = 0;
  private timers: { id: number; at: number; fn: () => void }[] = [];
  private nextId = 1;
  now(): number {
    return this.t;
  }
  setTimeout(fn: () => void, ms: number): unknown {
    const id = this.nextId++;
    this.timers.push({ id, at: this.t + ms, fn });
    return id;
  }
  clearTimeout(handle: unknown): void {
    this.timers = this.timers.filter((x) => x.id !== handle);
  }
  advance(ms: number): void {
    const end = this.t + ms;
    for (;;) {
      this.timers.sort((a, b) => a.at - b.at || a.id - b.id);
      const next = this.timers[0];
      if (!next || next.at > end) break;
      this.timers.shift();
      this.t = next.at;
      next.fn();
    }
    this.t = end;
  }
  get pending(): number {
    return this.timers.length;
  }
}
