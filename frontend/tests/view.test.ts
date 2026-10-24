import { describe, expect, it } from "vitest";
import { reduceAll } from "../src/lib/reducer";
import {
  bestMatch,
  compareGapLine,
  evidenceCards,
  findRanges,
  formatClock,
  formatDate,
  labelFromSummary,
  locationLabel,
  parseVs,
  ratio,
  ruleChipText,
  scanPhotoIndex,
  segments,
  splitDetail,
} from "../src/lib/view";
import { loadRecording } from "./helpers";

describe("claim highlights", () => {
  it("finds quotes case-insensitively across whitespace and skips overlaps", () => {
    const text = "Made from cornstarch\n100% Compostable  garbage bags\nBreaks down naturally";
    const r = findRanges(text, [
      { id: "C1", quote: "100% compostable garbage bags" },
      { id: "C2", quote: "compostable garbage" },
      { id: "C3", quote: "breaks down naturally." },
      { id: "C4", quote: "not here" },
    ]);
    expect(r.map((x) => x.claimId)).toEqual(["C1", "C3"]);
    const segs = segments(text, r);
    expect(segs.map((s) => s.text).join("")).toBe(text);
    expect(segs.find((s) => s.claimId === "C1")?.text).toBe("100% Compostable  garbage bags");
  });

  it("finds every placed claim of L14 in the listing text", () => {
    const s = reduceAll(loadRecording("L14.agent.json").events);
    const textClaims = s.claims.filter((c) => c.location === "description");
    const r = findRanges(s.listing?.body_text ?? "", textClaims);
    expect(r).toHaveLength(textClaims.length);
  });
});

describe("evidence cards", () => {
  it("L14: photo codes, registry rows and conflicts become typed cards", () => {
    const s = reduceAll(loadRecording("L14.agent.json").events);
    const cards = evidenceCards(s);
    const kinds = cards.map((c) => c.kind);
    expect(kinds).toContain("photo");
    expect(kinds).toContain("registry");
    expect(kinds).toContain("conflict");
    const reg = cards.find((c) => c.kind === "registry");
    expect(reg?.registry?.match?.s_no).toBe(32);
    const photo = cards.find((c) => c.kind === "photo");
    expect(photo?.printed).toBe("CPCB-UPC-II/GREEN DOT BIOPAK/Gujarat/443");
    expect(photo?.itemKind).toBe("code");
    const conflict = cards.find((c) => c.kind === "conflict");
    expect(conflict?.conflict?.b).toBe("100% compostable garbage bags");
  });

  it("L08: one certificate serving many claims is one card with a link per claim", () => {
    const s = reduceAll(loadRecording("L08.agent.json").events);
    const cards = evidenceCards(s);
    const bcorp = cards.filter((c) => c.kind === "certificate");
    expect(bcorp).toHaveLength(1);
    expect(bcorp[0]?.links.length).toBeGreaterThan(3);
    expect(cards.length).toBeLessThan(s.evidence.length);
    const ids = cards.flatMap((c) => c.ids);
    expect(new Set(ids).size).toBe(s.evidence.length);
  });
});

describe("text helpers", () => {
  it("parses consistency details and text locations", () => {
    expect(parseVs('"A b" vs "C d" (description)')).toEqual({ a: "A b", b: "C d", bLocation: "description" });
    expect(parseVs("Description: x")).toBeNull();
    expect(splitDetail("Description: BPA-free nylon")).toEqual({ location: "DESCRIPTION", quote: "BPA-free nylon" });
  });

  it("shortens rule chips", () => {
    const rule = {
      id: "R07",
      name: "n",
      summary: "s",
      clause: "Rule 4(1)(ha) (CPCB certificate before marketing or selling); Rule 4(1)(h) (IS/ISO 17088:2021)",
      source: "Plastic Waste Management (Amendment) Rules, 2024",
    };
    expect(ruleChipText("R07", rule)).toBe("R07 · PWM 4(1)(ha)");
    expect(ruleChipText("R02", { ...rule, clause: "clause to be confirmed", source: "CCPA guidelines on environmental claims, 2024" })).toBe(
      "R02 · CCPA 2024",
    );
    expect(ruleChipText("R99", undefined)).toBe("R99");
  });

  it("labels locations, verdict rows, times and dates", () => {
    expect(locationLabel({ location: "photo:7" })).toBe("PHOTO 7");
    expect(locationLabel({ location: "n/a", derived_from: "C1" })).toBe("LABEL CHECK");
    expect(labelFromSummary("Partly backed: some")).toBe("Partly backed");
    expect(labelFromSummary("Looking up")).toBeNull();
    expect(formatClock(83_400)).toBe("01:23.4");
    expect(formatDate("2026-10-18T09:59:28+00:00")).toMatch(/1[89] Oct 2026/);
  });

  it("picks the photo with proof-like print for the Scan", () => {
    const photos = [
      { index: 1, items: [{ text: "a", kind: "claim" as const, box_2d: null }] },
      { index: 7, items: [{ text: "CPCB", kind: "code" as const, box_2d: null }] },
    ];
    expect(scanPhotoIndex(photos)).toBe(7);
    expect(scanPhotoIndex(photos, 1)).toBe(1);
  });

  it("pairs claims like rapidfuzz ratio ≥ 80", () => {
    expect(ratio("abc", "abc")).toBe(100);
    expect(Math.round(ratio("abcd", "abce"))).toBe(75);
    expect(bestMatch("100% compostable garbage bags", [{ quote: "100% compostable garbage bag" }, { quote: "leak proof" }])?.quote).toBe(
      "100% compostable garbage bag",
    );
    expect(bestMatch("0% plastic", [{ quote: "leak proof" }])).toBeNull();
  });
});

describe("compareGapLine", () => {
  const photo = { location: "photo:7", derived_from: undefined };
  const text = { location: "description", derived_from: undefined };
  it("explains a claim the text-only check never saw", () => {
    expect(compareGapLine("baseline", null, photo, null)).toBe("Text-only never saw this claim: it's printed on the pack.");
    expect(compareGapLine("baseline", null, text, null)).toBe("Text-only didn't list this claim.");
    expect(compareGapLine("baseline", null, { location: "n/a", derived_from: "C1" }, null)).toMatch(/required label/);
    expect(compareGapLine("agent", null, text, null)).toBe("The agent didn't list this claim.");
  });
  it("says when a side saw the claim but found no proof", () => {
    expect(compareGapLine("baseline", text, text, "Not backed")).toBe("Text-only found no proof for this claim.");
    expect(compareGapLine("agent", text, text, "Not a claim")).toBe("Not a claim, so no proof was needed.");
  });
});
