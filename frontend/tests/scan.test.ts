import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BAND_LABEL, bandCounts, validateScan } from "../src/lib/scan";

const demo: unknown = JSON.parse(readFileSync(join(__dirname, "..", "public", "demo", "scan_demo.json"), "utf8"));

describe("recorded store scan (public/demo/scan_demo.json)", () => {
  it("follows the scan format and says it is triage", () => {
    const r = validateScan(demo);
    expect(r.ok ? "ok" : r.error).toBe("ok");
    if (!r.ok) return;
    const s = r.value;
    expect(s.label).toBe("Triage, not a verdict");
    expect(s.model_calls).toBe(0);
    expect(s.status).toBe("finished");
    expect(s.store).toMatch(/^brand-[a-z]+\.example$/);
    expect(s.rows.map((x) => x.rank)).toEqual(s.rows.map((_, i) => i + 1));
    const scores = s.rows.filter((x) => !x.error).map((x) => x.score);
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
    const counts = bandCounts(s.rows);
    expect(Object.values(counts).reduce((a, b) => a + b, 0)).toBe(s.rows.length);
  });

  it("uses careful words only", () => {
    const text = JSON.stringify(demo).toLowerCase() + Object.values(BAND_LABEL).join(" ").toLowerCase();
    for (const word of ["illegal", "violation", "greenwashing", "fraud", "lying"]) expect(text).not.toContain(word);
  });

  it("rejects a malformed scan with a path", () => {
    const r = validateScan({ id: "S1", status: "finished", rows: [{}] });
    expect(r.ok).toBe(false);
  });
});
