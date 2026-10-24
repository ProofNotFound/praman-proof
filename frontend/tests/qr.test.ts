import { describe, expect, it } from "vitest";
import { validateEvent, type PramanEvent } from "../src/lib/events";
import { reduceAll } from "../src/lib/reducer";
import { evidenceCards } from "../src/lib/view";
import { toMarkdown } from "../src/lib/markdown";

const ev = (seq: number, type: string, data: unknown) => ({ seq, t_ms: seq, run_id: "R", type, data });

const events = [
  ev(1, "run_started", { run_id: "R", listing_id: "U1", mode: "agent", llm_mode: "replay", started_at: "2026-10-19T10:00:00+00:00" }),
  ev(2, "listing", { id: "U1", title: "Bags", store: "brand-i.example", body_text: "100% compostable bags.", photos: [{ index: 3, url: "demo/photos/U1/3.jpg" }] }),
  ev(3, "claims", {
    claims: [{ id: "C1", quote: "100% compostable bags", normalised: "100% compostable bags", type: "specific", scope: "product", location: "description", is_claim: true, rule_ids: ["R02"] }],
  }),
  ev(4, "evidence", {
    id: "E1",
    claim_id: "C1",
    source: "photo",
    detail: "QR code links to qr-short.example; not followed",
    photo_index: 3,
    crop_box: [500, 500, 700, 700],
    covers_claim: "no",
    kind: "qr_link",
    note: "Praman opens only links on the store's own site.",
    qr: { domain: "qr-short.example", followed: false },
  }),
  ev(5, "evidence", {
    id: "E2",
    claim_id: "C1",
    source: "photo",
    detail: "Photo 3: QR code links to /pages/certs on the store's own site",
    photo_index: 3,
    crop_box: [100, 100, 300, 300],
    covers_claim: "partly",
    kind: "disclosure_link",
    qr: { domain: "brand-i.example", followed: true, path: "/pages/certs" },
  }),
];

describe("QR code evidence (W4)", () => {
  it("validates against the contract, with and without a path", () => {
    for (const e of events) expect(validateEvent(e).ok).toBe(true);
    const bad = ev(6, "evidence", { ...(events[3]?.data as object), qr: { domain: 3 } });
    expect(validateEvent(bad).ok).toBe(false);
  });

  it("becomes a QR card per code, with the domain and whether it was opened", () => {
    const s = reduceAll(events as PramanEvent[]);
    const cards = evidenceCards(s);
    expect(cards.map((c) => c.kind)).toEqual(["qr", "qr"]);
    expect(cards[0]?.qr).toEqual({ domain: "qr-short.example", followed: false, path: null });
    expect(cards[1]?.qr?.followed).toBe(true);
    expect(cards[0]?.box).toEqual([500, 500, 700, 700]);
    const md = toMarkdown(s, { caseLabel: "U1", when: null, approval: null });
    expect(md).toContain("links to qr-short.example (not followed, another site)");
  });
});
