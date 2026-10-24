import { describe, expect, it } from "vitest";
import type { Claim, PramanEvent } from "../src/lib/events";
import {
  claimStatus,
  initialState,
  isWorking,
  modelCalls,
  photosRead,
  reduce,
  reduceAll,
  verdictCounts,
} from "../src/lib/reducer";
import { loadRecording } from "./helpers";

const claim = (id: string, quote = `quote ${id}`): Claim => ({
  id,
  quote,
  normalised: quote.toLowerCase(),
  type: "specific",
  scope: "product",
  location: "description",
  is_claim: true,
  not_claim_reason: null,
  rule_ids: ["R02"],
});

let seq = 0;
function e<T extends PramanEvent["type"]>(type: T, data: Extract<PramanEvent, { type: T }>["data"]): PramanEvent {
  seq += 1;
  return { seq, t_ms: seq, run_id: "r1", type, data } as PramanEvent;
}

describe("reducer on the real recordings", () => {
  it("L14 agent: verdicts match PRD §12", () => {
    const s = reduceAll(loadRecording("L14.agent.json").events);
    expect(s.listing?.id).toBe("L14");
    expect(s.mode).toBe("agent");
    const byQuote = (q: string) => s.claims.find((c) => c.quote.includes(q));
    expect(s.verdicts[byQuote("100% compostable")!.id]?.label).toBe("Backed");
    expect(s.verdicts[byQuote("0% plastic")!.id]?.label).toBe("Contradicted");
    const label = s.claims.find((c) => c.derived_from === "C1" || c.location === "n/a");
    expect(label && s.verdicts[label.id]?.label).toBe("Needs review");
    expect(s.registry).toHaveLength(2);
    expect(s.registry[0]?.match?.s_no).toBe(32);
    expect(photosRead(s).has(7)).toBe(true);
    expect(s.finished).not.toBeNull();
    expect(isWorking(s)).toBe(false);
    expect(s.scan).toBeNull();
    expect(s.ledger).toBeNull();
    expect(modelCalls(s)).toBe(s.finished?.llm_calls);
    const counts = verdictCounts(s);
    expect(Object.values(counts).reduce((a, b) => a + (b ?? 0), 0)).toBe(s.claims.length);
  });

  it("L14 baseline never sees the photo-only claim", () => {
    const s = reduceAll(loadRecording("L14.baseline.json").events);
    expect(s.claims.some((c) => c.quote.includes("0% plastic"))).toBe(false);
    expect(s.photoReads).toHaveLength(0);
  });

  it("L21: not a claim, no tool calls beyond extraction", () => {
    const s = reduceAll(loadRecording("L21.agent.json").events);
    expect(Object.values(s.verdicts).every((v) => v.label === "Not a claim")).toBe(true);
    expect(s.registry).toHaveLength(0);
    expect(s.photoReads).toHaveLength(0);
  });

  it("L08: a re-sent verdict replaces the label (latest wins) and keeps the seq when unchanged", () => {
    const events = loadRecording("L08.agent.json").events;
    const s = reduceAll(events);
    const verdictEvents = events.filter((x) => x.type === "verdict" && x.data.claim_id === "C2");
    expect(verdictEvents.length).toBeGreaterThan(1);
    expect(s.verdicts.C2?.seq).toBe(verdictEvents[0]?.seq);
    expect(s.verdicts.C3?.label).toBe("Contradicted");
  });
});

describe("reducer units", () => {
  it("upserts claims by id and keeps first-seen order", () => {
    let s = reduce(initialState, e("claims", { claims: [claim("C1"), claim("C2")] }));
    s = reduce(s, e("claims", { claims: [claim("C2", "changed"), claim("C3")] }));
    expect(s.claims.map((c) => c.id)).toEqual(["C1", "C2", "C3"]);
    expect(s.claims[1]?.quote).toBe("changed");
  });

  it("keeps evidence and verdicts for a claim it hasn't seen yet", () => {
    let s = reduce(
      initialState,
      e("evidence", {
        id: "E1",
        claim_id: "C9",
        source: "text",
        detail: "Description: x",
        covers_claim: "yes",
      }),
    );
    s = reduce(
      s,
      e("verdict", {
        claim_id: "C9",
        label: "Backed",
        evidence_ids: ["E1"],
        rule_ids: ["R02"],
        reason: "r",
        sources_searched: ["text"],
      }),
    );
    expect(s.claims).toHaveLength(0);
    expect(claimStatus(s, "C9")).toBe("decided");
    s = reduce(s, e("claims", { claims: [claim("C9")] }));
    expect(s.claims[0]?.id).toBe("C9");
    expect(s.verdicts.C9?.label).toBe("Backed");
    expect(s.evidence[0]?.claim_id).toBe("C9");
  });

  it("ignores repeated or older seqs", () => {
    const first = e("claims", { claims: [claim("C1")] });
    const s1 = reduce(initialState, first);
    expect(reduce(s1, first)).toBe(s1);
  });

  it("opens the Scan and Ledger moments and closes them when the agent moves on", () => {
    let s = reduce(initialState, e("photo_read", { photos: [{ index: 3, items: [] }] }));
    expect(s.scan?.read.photos[0]?.index).toBe(3);
    s = reduce(
      s,
      e("evidence", { id: "E1", claim_id: "C1", source: "photo", detail: "Photo 3: x", covers_claim: "partly" }),
    );
    expect(s.scan).not.toBeNull();
    s = reduce(
      s,
      e("registry_lookup", {
        claim_id: "C1",
        query: "q",
        rows_scanned: 2,
        list_date: "2023-10-26",
        match: null,
        score: 0,
      }),
    );
    expect(s.ledger?.lookup.query).toBe("q");
    s = reduce(
      s,
      e("step", { run_id: "r1", claim_id: "C1", n: 1, phase: "observe", tool: "cpcb_lookup", summary: "s", ms: 1 }),
    );
    expect(s.scan).toBeNull();
    expect(s.ledger).toBeNull();
    expect(s.activeClaimId).toBe("C1");
  });

  it("tracks the active claim and the working state", () => {
    let s = reduce(
      initialState,
      e("run_started", { run_id: "r1", listing_id: "L1", mode: "agent", llm_mode: "replay", started_at: "x" }),
    );
    s = reduce(s, e("claims", { claims: [claim("C1"), claim("C2")] }));
    expect(isWorking(s)).toBe(true);
    expect(claimStatus(s, "C1")).toBe("waiting");
    s = reduce(
      s,
      e("step", { run_id: "r1", claim_id: "C1", n: 1, phase: "plan", tool: "search_text", summary: "s", ms: 0, tokens_in: 10 }),
    );
    expect(claimStatus(s, "C1")).toBe("active");
    expect(claimStatus(s, "C2")).toBe("waiting");
    expect(modelCalls(s)).toBe(1);
    s = reduce(s, e("error", { message: "Stopped", recoverable: false }));
    expect(isWorking(s)).toBe(false);
    expect(s.error?.message).toBe("Stopped");
  });
});
