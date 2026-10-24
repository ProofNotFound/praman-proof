import { describe, expect, it } from "vitest";
import { reduceAll } from "../src/lib/reducer";
import { disclaimer, toMarkdown } from "../src/lib/markdown";
import { compareRows } from "../src/components/CompareSplit";
import { loadRecording } from "./helpers";

const BANNED = /\b(illegal|violation|greenwashing|fraud|lying)\b/i;

describe("dossier markdown", () => {
  it.each(["L14", "L06", "L08", "L21"])("%s: every claim, its verdict and the exact disclaimer", (id) => {
    const rec = loadRecording(`${id}.agent.json`);
    const s = reduceAll(rec.events);
    const md = toMarkdown(s, { caseLabel: id, when: s.startedAt, approval: { name: "A Reviewer", at: "2026-10-18T10:00:00Z" } });
    for (const c of s.claims) expect(md).toContain(`### ${c.id} · ${s.verdicts[c.id]?.label ?? "No verdict"}`);
    expect(md).toContain("Reviewed and approved by A Reviewer");
    expect(md.trim().endsWith(disclaimer("18 Oct 2026"))).toBe(true);
    expect(md).not.toMatch(BANNED);
  });

  it("uses the PRD §8 wording", () => {
    expect(disclaimer("18 Oct 2026")).toBe(
      "Decision support, not legal advice. Based on what is visible on the listing on 18 Oct 2026. CPCB list dated 26 Oct 2023.",
    );
  });
});

describe("compare rows", () => {
  it("L14: the photo-only claim has no text-only partner and the compostable claim differs", () => {
    const a = reduceAll(loadRecording("L14.agent.json").events);
    const b = reduceAll(loadRecording("L14.baseline.json").events);
    const rows = compareRows(a, b, null);
    const plastic = rows.find((r) => r.agent?.quote.includes("0% plastic"));
    expect(plastic?.baseline).toBeNull();
    expect(plastic?.differs).toBe(true);
    const compostable = rows.find((r) => r.agent?.quote.startsWith("100% compostable"));
    expect(compostable?.baseline).not.toBeNull();
    expect(compostable?.differs).toBe(true);
    const ids = rows.flatMap((r) => (r.baseline ? [r.baseline.id] : []));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("follows the API's pairs when given", () => {
    const a = reduceAll(loadRecording("L06.agent.json").events);
    const b = reduceAll(loadRecording("L06.baseline.json").events);
    const first = a.claims[0]!;
    const rows = compareRows(a, b, [
      { agent_claim_id: first.id, baseline_claim_id: null, quote: first.quote, agent: null, baseline: null, differs: true },
    ]);
    expect(rows[0]?.baseline).toBeNull();
  });
});
