import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { validateEvent, validateIndex, validateRecording } from "../src/lib/events";

const DEMO = join(__dirname, "..", "public", "demo");
// JSON files next to the recordings that aren't recordings
const NOT_RECORDINGS = new Set(["index.json", "eval.json", "urls.json", "scan_demo.json", "rule_packs.json"]);
const files = readdirSync(DEMO).filter((f) => f.endsWith(".json") && !NOT_RECORDINGS.has(f));
const read = (f: string): unknown => JSON.parse(readFileSync(join(DEMO, f), "utf8"));

describe("bundled recordings (TRD §15.4)", () => {
  it("has a recording for each demo case in both modes", () => {
    for (const id of ["L14", "L06", "L08", "L21"]) {
      expect(files).toContain(`${id}.agent.json`);
      expect(files).toContain(`${id}.baseline.json`);
    }
  });

  it.each(files)("%s validates event by event", (f) => {
    const doc = read(f);
    const r = validateRecording(doc);
    expect(r.ok ? "ok" : r.error).toBe("ok");
    if (!r.ok) return;
    const events = r.value.events;
    expect(events[0]?.type).toBe("run_started");
    expect(events.at(-1)?.type).toBe("run_finished");
    for (const e of events) expect(validateEvent(e).ok).toBe(true);
    const listing = events.find((e) => e.type === "listing");
    expect(listing).toBeDefined();
    if (listing?.type === "listing") {
      for (const p of listing.data.photos) {
        expect(p.url.startsWith("demo/photos/")).toBe(true);
        expect(existsSync(join(DEMO, p.url.slice("demo/".length)))).toBe(true);
      }
    }
  });

  it("index.json lists every recording", () => {
    const r = validateIndex(read("index.json"));
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(new Set(r.value.map((e) => e.file))).toEqual(new Set(files));
  });

  it("rejects malformed events with a path", () => {
    const bad = { seq: 1, t_ms: 0, run_id: "x", type: "verdict", data: { claim_id: "C1" } };
    const r = validateEvent(bad);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain("event.data.label");
    expect(validateEvent({ ...bad, type: "nope" }).ok).toBe(false);
    expect(validateEvent({ ...bad, extra: 1 }).ok).toBe(false);
  });
});
