import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { SEAL_GLYPHS, SEAL_INNER, SEAL_OUTER, SEAL_RING_TEXT, SEAL_RING_Y } from "../src/lib/seal";

// The favicon is the corrected logo (docs/design/praman_seal.svg) with a paper fill, so it is the reference.
const reference = readFileSync(new URL("../public/seal.svg", import.meta.url), "utf8");

describe("seal ring text", () => {
  it("spells the ring text once, one glyph per character", () => {
    expect(SEAL_GLYPHS.map((g) => g.ch).join("")).toBe(SEAL_RING_TEXT.replaceAll(" ", ""));
  });

  it("matches the corrected logo (the favicon): glyphs, angles and circles", () => {
    const glyphs = [...reference.matchAll(/rotate\(([\d.]+) 100 100\)">([^<]+)</g)].map((m) => ({
      ch: m[2],
      angle: Number(m[1]),
    }));
    expect(glyphs).toEqual(SEAL_GLYPHS);
    expect(reference).toContain(`r="${SEAL_OUTER.r}" stroke-width="${SEAL_OUTER.stroke}"`);
    expect(reference).toContain(`r="${SEAL_INNER.r}" stroke-width="${SEAL_INNER.stroke}"`);
    expect(reference).toContain(`y="${SEAL_RING_Y}"`);
  });

  it("goes once round the circle with no two glyphs closer than a letter step", () => {
    const steps = SEAL_GLYPHS.map((g, i) => {
      const next = SEAL_GLYPHS[(i + 1) % SEAL_GLYPHS.length]?.angle ?? 0;
      return (next - g.angle + 360) % 360;
    });
    expect(steps.reduce((a, b) => a + b, 0)).toBeCloseTo(360, 6);
    expect(Math.min(...steps)).toBeGreaterThan(18);
  });

  it("keeps the ring text between the two circles", () => {
    const baseline = 100 - SEAL_RING_Y;
    expect(baseline).toBeGreaterThan(SEAL_INNER.r + SEAL_INNER.stroke / 2);
    expect(baseline + 18 * 0.7).toBeLessThan(SEAL_OUTER.r - SEAL_OUTER.stroke / 2);
  });
});
