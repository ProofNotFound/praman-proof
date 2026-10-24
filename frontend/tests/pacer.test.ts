import { describe, expect, it } from "vitest";
import { Pacer, type Speed } from "../src/lib/pacer";
import { FakeClock } from "./helpers";

type Ev = { seq: number; type: string };
const ev = (seq: number, type: string): Ev => ({ seq, type });

function setup(speed: Speed = 1, paused = false) {
  const clock = new FakeClock();
  const released: Ev[] = [];
  let resets = 0;
  const pacer = new Pacer<Ev>({
    clock,
    speed,
    paused,
    onRelease: (es) => released.push(...es),
    onReset: () => {
      resets += 1;
      released.length = 0;
    },
  });
  return { clock, pacer, released, resets: () => resets };
}

describe("pacer", () => {
  it("releases the first event at once, then waits the gap of the event just released", () => {
    const { clock, pacer, released } = setup();
    pacer.push(ev(1, "step"), ev(2, "photo_read"), ev(3, "verdict"), ev(4, "step"));
    expect(released.map((e) => e.seq)).toEqual([1]);
    clock.advance(499);
    expect(released).toHaveLength(1);
    clock.advance(1); // step gap 500
    expect(released.map((e) => e.seq)).toEqual([1, 2]);
    clock.advance(2599); // photo_read gap 2600 (the Scan)
    expect(released).toHaveLength(2);
    clock.advance(1);
    expect(released).toHaveLength(3);
    clock.advance(900); // verdict gap
    expect(released).toHaveLength(4);
  });

  it("scales gaps with speed and releases everything at instant", () => {
    const fast = setup(2);
    fast.pacer.push(ev(1, "registry_lookup"), ev(2, "evidence"));
    fast.clock.advance(749);
    expect(fast.released).toHaveLength(1);
    fast.clock.advance(1); // 1500 / 2
    expect(fast.released).toHaveLength(2);

    const slow = setup(0.5);
    slow.pacer.push(ev(1, "evidence"), ev(2, "evidence"));
    slow.clock.advance(899);
    expect(slow.released).toHaveLength(1);
    slow.clock.advance(1); // 450 / 0.5
    expect(slow.released).toHaveLength(2);

    const inst = setup("instant");
    inst.pacer.push(ev(1, "step"), ev(2, "photo_read"), ev(3, "verdict"));
    expect(inst.released).toHaveLength(3);
    inst.pacer.push(ev(4, "step"));
    expect(inst.released).toHaveLength(4);
  });

  it("changing speed mid-gap reschedules the next release", () => {
    const { clock, pacer, released } = setup();
    pacer.push(ev(1, "photo_read"), ev(2, "step"));
    clock.advance(1000);
    pacer.setSpeed(2); // gap is now 1300, already 1000 in
    clock.advance(299);
    expect(released).toHaveLength(1);
    clock.advance(1);
    expect(released).toHaveLength(2);
  });

  it("pauses, resumes and steps one event at a time", () => {
    const { clock, pacer, released } = setup(1, true);
    pacer.push(ev(1, "step"), ev(2, "step"), ev(3, "step"));
    clock.advance(5000);
    expect(released).toHaveLength(0);
    pacer.step();
    expect(released.map((e) => e.seq)).toEqual([1]);
    expect(pacer.getSnapshot().paused).toBe(true);
    clock.advance(5000);
    expect(released).toHaveLength(1);
    pacer.step();
    expect(released).toHaveLength(2);
    pacer.resume();
    // the gap after event 2 started when it was stepped, 0 ms ago
    clock.advance(499);
    expect(released).toHaveLength(2);
    clock.advance(1);
    expect(released).toHaveLength(3);
    pacer.toggle();
    expect(pacer.getSnapshot().paused).toBe(true);
  });

  it("waits for events that haven't arrived yet and releases them when they do", () => {
    const { clock, pacer, released } = setup();
    pacer.push(ev(1, "step"));
    clock.advance(2000);
    pacer.push(ev(2, "step"));
    expect(released).toHaveLength(2); // the gap had already passed
    pacer.push(ev(3, "step"));
    expect(released).toHaveLength(2);
    clock.advance(500);
    expect(released).toHaveLength(3);
  });

  it("ignores repeated seqs and keeps seq order", () => {
    const { clock, pacer, released } = setup("instant");
    pacer.push(ev(2, "step"), ev(1, "step"), ev(2, "step"));
    clock.advance(10);
    expect(released.map((e) => e.seq)).toEqual([1, 2]);
    expect(pacer.getSnapshot().total).toBe(2);
  });

  it("restarts from the first event and can start paused", () => {
    const { clock, pacer, released, resets } = setup();
    pacer.push(ev(1, "step"), ev(2, "step"), ev(3, "step"));
    clock.advance(2000);
    expect(released).toHaveLength(3);
    pacer.restart({ paused: true });
    expect(resets()).toBe(1);
    expect(released).toHaveLength(0);
    expect(pacer.getSnapshot().released).toBe(0);
    pacer.releaseThrough("step");
    expect(released.map((e) => e.seq)).toEqual([1]);
    pacer.resume();
    clock.advance(1000);
    expect(released).toHaveLength(3);
  });

  it("notifies subscribers with stable snapshots", () => {
    const { pacer } = setup(1, true);
    let calls = 0;
    pacer.subscribe(() => (calls += 1));
    const a = pacer.getSnapshot();
    expect(pacer.getSnapshot()).toBe(a);
    pacer.push(ev(1, "step"));
    expect(calls).toBe(1);
    expect(pacer.getSnapshot()).not.toBe(a);
    pacer.end();
    expect(pacer.getSnapshot().ended).toBe(true);
    pacer.dispose();
  });
});
