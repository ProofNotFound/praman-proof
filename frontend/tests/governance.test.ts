import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { reduceAll } from "../src/lib/reducer";
import { toMarkdown } from "../src/lib/markdown";
import { decisionLog, finalCounts, latestReviews, parseReviews, pendingReviews, type Review } from "../src/lib/review";
import { caseImpact, rupees, scaleImpact, ASSUMPTIONS } from "../src/lib/impact";
import { parsePacks, triggeredRules } from "../src/lib/packs";
import { parseAudit, provenanceLine, reviewerAccess } from "../src/lib/api";
import { DEMO, loadRecording } from "./helpers";

const l14 = () => reduceAll(loadRecording("L14.agent.json").events);

function review(claim_id: string, over: Partial<Review> = {}): Review {
  return { claim_id, decision: "agree", label: "Needs review", ai_label: "Needs review", reason: "", reviewer: "Asha", at: "2026-10-24T10:00:00Z", ...over };
}

describe("human review", () => {
  it("L14: the Needs review claim blocks sign-off until a reviewer decides it", () => {
    const s = l14();
    const open = pendingReviews(s, {});
    expect(open).toHaveLength(1);
    const id = open[0]!;
    expect(pendingReviews(s, latestReviews([review(id)]))).toEqual([]);
  });

  it("a changed verdict moves the counts and the export, and keeps the agent's label on record", () => {
    const s = l14();
    const id = pendingReviews(s, {})[0]!;
    const reviews = [review(id, { decision: "change", label: "Not backed", reason: "No certificate on the pack." })];
    const latest = latestReviews(reviews);
    expect(finalCounts(s, latest)["Needs review"]).toBeUndefined();
    const md = toMarkdown(s, { caseLabel: "L14", when: s.startedAt, approval: { name: "Asha", at: "2026-10-24T10:05:00Z" }, reviews });
    expect(md).toContain(`### ${id} · Not backed`);
    expect(md).toContain("Reviewer changed the verdict from Needs review to Not backed: No certificate on the pack.");
    expect(md).toContain("## Decision log");
    expect(md).toMatch(/Asha · Approved the report/);
  });

  it("the decision log lists every agent verdict with its proof, then the humans", () => {
    const s = l14();
    const log = decisionLog(s, [review("C1")], { name: "Asha", at: "2026-10-24T10:05:00Z" });
    const agentVerdicts = log.filter((e) => e.kind === "agent" && /→/.test(e.what));
    expect(agentVerdicts).toHaveLength(Object.keys(s.verdicts).length);
    expect(log.at(-1)?.what).toBe("Approved the report");
    expect(log.filter((e) => e.kind === "human")).toHaveLength(2);
  });

  it("drops malformed reviews", () => {
    expect(parseReviews([review("C1"), { claim_id: "C2", decision: "maybe" }, null])).toHaveLength(1);
  });
});

describe("impact", () => {
  it("a replayed run quotes the typical live time, not the replay's milliseconds", () => {
    const i = caseImpact(l14());
    expect(i.measured).toBe(false);
    expect(i.seconds).toBe(ASSUMPTIONS.liveSecondsPerPage);
    expect(i.claims).toBe(5);
    expect(i.forReview).toBe(1);
    expect(i.manualMinutes).toBe(ASSUMPTIONS.manualMinutesPerPage + 5 * ASSUMPTIONS.manualMinutesPerClaim);
  });

  it("adds up at scale", () => {
    const r = scaleImpact({
      listings: 1000,
      claimsPerListing: 4,
      manualMinutesPerPage: 10,
      manualMinutesPerClaim: 8,
      reviewMinutesPerPage: 5,
      reviewerRupeesPerHour: 600,
      aiRupeesPerListing: 1,
    });
    expect(r.manualHours).toBeCloseTo(700);
    expect(r.pramanHours).toBeCloseTo(83.33, 1);
    expect(r.manualInr).toBeCloseTo(420000);
    expect(r.pramanInr).toBeCloseTo(51000);
    expect(r.speedup).toBeCloseTo(8.4);
    expect(rupees(420000)).toBe("₹4.2 lakh");
    expect(rupees(1234)).toBe("₹1,234");
  });
});

describe("rule packs", () => {
  const packs = parsePacks(JSON.parse(readFileSync(join(DEMO, "rule_packs.json"), "utf8")));

  it("bundles the agent's pack and a second rulebook", () => {
    expect(packs.map((p) => p.name)).toEqual(["green_claims", "food_labels"]);
    expect(packs[0]?.status).toBe("active");
  });

  it("matches on word edges in either pack", () => {
    const green = packs[0]!;
    const food = packs[1]!;
    expect(triggeredRules(green, "100% compostable bags").map((h) => h.rule.id)).toContain("R07");
    const ids = triggeredRules(food, "Certified organic. High protein, no added sugar.").map((h) => h.rule.id);
    expect(ids).toEqual(expect.arrayContaining(["F01", "F03"]));
    expect(triggeredRules(food, "inorganic chemistry")).toHaveLength(0);
  });
});

describe("recorded-run fallback", () => {
  it("'.rec' case ids play the bundled recording; plain ones stay as before", async () => {
    const { parseCaseId, recordedCaseId } = await import("../src/lib/api");
    expect(parseCaseId(recordedCaseId("L14", "agent"))).toEqual({ kind: "file", listingId: "L14", mode: "agent", bundled: true });
    expect(parseCaseId("L14.agent")).toEqual({ kind: "file", listingId: "L14", mode: "agent" });
    expect(parseCaseId("L14-agent-20261024").kind).toBe("run");
  });
});

describe("audit and reviewer access", () => {
  const health = (reviewer_access?: "key" | "role" | "off") =>
    ({ kind: "live", health: { ok: true, llm_mode: "replay", anonymise: true, cpcb_list_date: "2023-10-26", version: "0.1.0", reviewer_access } }) as const;

  it("follows the server's reviewer access, and keeps the role switch for recordings and older servers", () => {
    expect(reviewerAccess(health("key"))).toBe("key");
    expect(reviewerAccess(health("off"))).toBe("off");
    expect(reviewerAccess(health())).toBe("role");
    expect(reviewerAccess({ kind: "recording", reason: "no server" })).toBe("role");
    expect(reviewerAccess(null)).toBe("role");
  });

  it("parses the audit and says what the run was checked with", () => {
    const a = parseAudit({
      provenance: { praman: "0.1.0", commit: "27e675a76e4c", rules_version: "0.2", rules_as_of: "2026-10-24", prompts: "d089d5dd46fb",
        model: "gemini-3.8-flash", live_model: "groq:openai/gpt-oss-120b", llm_mode: "replay", cpcb_list_date: "2023-10-26" },
      reviews: 2, reviews_intact: true, fingerprint: "ab".repeat(32), fingerprint_matches: true,
    });
    expect(a?.reviews).toBe(2);
    expect(a?.fingerprint_matches).toBe(true);
    expect(provenanceLine(a?.provenance ?? null)).toBe(
      "Checked with: rulebook 0.2 (2026-10-24) · prompts d089d5dd46fb · model gemini-3.8-flash · CPCB list 2023-10-26 · Praman 0.1.0 @ 27e675a76e4c.",
    );
    expect(provenanceLine(null)).toMatch(/not recorded/);
  });

  it("treats a malformed audit as missing parts, never as a match", () => {
    expect(parseAudit("nope")).toBeNull();
    const a = parseAudit({ reviews: "2", fingerprint_matches: "yes" });
    expect(a).toEqual({ provenance: null, reviews: 0, reviews_intact: false, fingerprint: null, fingerprint_matches: null });
  });
});
