// The release queue between an event source and the reducer (DESIGN §7). Replay runs finish in
// about a second; the pacer releases events at a readable pace: after an event of type T it waits
// at least GAPS[T] / speed before the next. Live runs that are slower than that pass straight through.
// Pure logic with an injectable clock, so tests can drive it with fake timers.

export type Speed = 0.5 | 1 | 2 | "instant";
export const SPEEDS: readonly Speed[] = [0.5, 1, 2, "instant"];

/** Minimum gap after each event type at 1×, in ms. */
export const GAPS: Readonly<Record<string, number>> = {
  run_started: 300,
  listing: 600,
  claims: 700,
  step: 500,
  photo_read: 2600,
  registry_lookup: 1500,
  evidence: 450,
  verdict: 900,
  run_finished: 0,
  error: 0,
};
const DEFAULT_GAP = 400;

export interface Clock {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export const realClock: Clock = {
  now: () => performance.now(),
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>),
};

export interface Paced {
  seq: number;
  type: string;
}

export interface PacerSnapshot {
  released: number;
  total: number;
  paused: boolean;
  speed: Speed;
  /** The source said no more events will come. */
  ended: boolean;
}

export interface PacerOptions<E extends Paced> {
  /** Called with the events released together (one, or all of them at "instant"). */
  onRelease: (events: E[]) => void;
  /** Called when the pacer restarts from the first event: clear any state built so far. */
  onReset?: () => void;
  clock?: Clock;
  speed?: Speed;
  paused?: boolean;
  gaps?: Readonly<Record<string, number>>;
}

export class Pacer<E extends Paced> {
  private buffer: E[] = [];
  private seen = new Set<number>();
  private index = 0;
  private lastReleaseAt = -Infinity;
  private lastGap = 0;
  private timer: unknown = null;
  private listeners = new Set<() => void>();
  private snap: PacerSnapshot;
  private readonly clock: Clock;
  private readonly gaps: Readonly<Record<string, number>>;
  private speed: Speed;
  private paused: boolean;
  private ended = false;
  private disposed = false;

  constructor(private readonly opts: PacerOptions<E>) {
    this.clock = opts.clock ?? realClock;
    this.gaps = opts.gaps ?? GAPS;
    this.speed = opts.speed ?? 1;
    this.paused = opts.paused ?? false;
    this.snap = this.makeSnapshot();
  }

  // -- source side ---------------------------------------------------------

  push(...events: E[]): void {
    for (const e of events) {
      if (this.seen.has(e.seq)) continue; // a reconnect may repeat events
      this.seen.add(e.seq);
      this.buffer.push(e);
    }
    this.buffer.sort((a, b) => a.seq - b.seq);
    this.changed();
    this.schedule();
  }

  /** The source has no more events (the run finished or the recording is fully loaded). */
  end(): void {
    this.ended = true;
    this.changed();
  }

  /** All events received so far, released or not (read-only). */
  get events(): readonly E[] {
    return this.buffer;
  }

  /** The events not yet released (for look-ahead, e.g. which photo boxes become evidence). */
  get upcoming(): readonly E[] {
    return this.buffer.slice(this.index);
  }

  // -- director side -------------------------------------------------------

  setSpeed(speed: Speed): void {
    this.speed = speed;
    this.changed();
    this.reschedule();
  }

  pause(): void {
    this.paused = true;
    this.clearTimer();
    this.changed();
  }

  resume(): void {
    this.paused = false;
    this.changed();
    this.schedule();
  }

  toggle(): void {
    if (this.paused) this.resume();
    else this.pause();
  }

  /** Release exactly one event now and stay paused (DESIGN §7: → steps). */
  step(): void {
    this.paused = true;
    this.clearTimer();
    if (this.index < this.buffer.length) this.releaseOne();
    this.changed();
  }

  /** Release events up to and including the first one of `type` (e.g. show the listing). */
  releaseThrough(type: string): void {
    while (this.index < this.buffer.length) {
      const e = this.buffer[this.index];
      this.releaseOne();
      if (e?.type === type) break;
    }
    this.changed();
  }

  /** Start again from the first event (R). The source keeps its events; nothing is refetched. */
  restart(opts: { paused?: boolean } = {}): void {
    this.clearTimer();
    this.index = 0;
    this.lastReleaseAt = -Infinity;
    this.lastGap = 0;
    if (opts.paused !== undefined) this.paused = opts.paused;
    this.opts.onReset?.();
    this.changed();
    this.schedule();
  }

  /** Release everything received so far at once. */
  flush(): void {
    this.clearTimer();
    if (this.index < this.buffer.length) {
      const batch = this.buffer.slice(this.index);
      this.index = this.buffer.length;
      this.lastReleaseAt = this.clock.now();
      this.lastGap = 0;
      this.opts.onRelease(batch);
    }
    this.changed();
  }

  dispose(): void {
    this.disposed = true;
    this.clearTimer();
    this.listeners.clear();
  }

  // -- observing -----------------------------------------------------------

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };

  /** Stable between changes (safe for useSyncExternalStore). */
  getSnapshot = (): PacerSnapshot => this.snap;

  // -- internals -----------------------------------------------------------

  private makeSnapshot(): PacerSnapshot {
    return {
      released: this.index,
      total: this.buffer.length,
      paused: this.paused,
      speed: this.speed,
      ended: this.ended,
    };
  }

  private changed(): void {
    const next = this.makeSnapshot();
    const s = this.snap;
    if (
      s.released === next.released &&
      s.total === next.total &&
      s.paused === next.paused &&
      s.speed === next.speed &&
      s.ended === next.ended
    ) {
      return;
    }
    this.snap = next;
    for (const fn of this.listeners) fn();
  }

  private gapFor(type: string): number {
    const base = this.gaps[type] ?? DEFAULT_GAP;
    return this.speed === "instant" ? 0 : base / this.speed;
  }

  private releaseOne(): void {
    const e = this.buffer[this.index];
    if (!e) return;
    this.index += 1;
    this.lastReleaseAt = this.clock.now();
    this.lastGap = this.gapFor(e.type);
    this.opts.onRelease([e]);
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      this.clock.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private reschedule(): void {
    this.clearTimer();
    // The gap after the last event depends on the speed it was released at; recompute it.
    const last = this.buffer[this.index - 1];
    if (last) this.lastGap = this.gapFor(last.type);
    this.schedule();
  }

  private schedule(): void {
    if (this.disposed || this.paused || this.timer !== null) return;
    if (this.index >= this.buffer.length) return;
    if (this.speed === "instant") {
      this.flush();
      return;
    }
    const wait = this.lastReleaseAt + this.lastGap - this.clock.now();
    if (wait <= 0) {
      this.releaseOne();
      this.changed();
      // Yield between events even when no gap is due, so each one renders.
      this.timer = this.clock.setTimeout(() => {
        this.timer = null;
        this.schedule();
      }, Math.max(0, this.lastGap));
      return;
    }
    this.timer = this.clock.setTimeout(() => {
      this.timer = null;
      this.schedule();
    }, wait);
  }
}
