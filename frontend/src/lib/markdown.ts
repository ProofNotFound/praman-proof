// The dossier as Markdown, built in the browser from the reducer state (recording mode; live mode
// downloads the server's report.md). Same sections as the on-screen report and the PRD §8 disclaimer.

import type { VerdictLabel } from "./events";
import type { CaseState } from "./reducer";
import { decisionLog, finalCounts, finalLabel, latestReviews, reviewLine, type Approval, type Review } from "./review";
import { evidenceCards, formatDate, formatDateTime, locationLabel, type EvidenceCardModel } from "./view";

export type { Approval } from "./review";

export const CPCB_LIST_DATE = "26 Oct 2023";

/** PRD §8: every report ends with this. */
export function disclaimer(listingDate: string): string {
  return `Decision support, not legal advice. Based on what is visible on the listing on ${listingDate}. CPCB list dated ${CPCB_LIST_DATE}.`;
}

const ORDER: VerdictLabel[] = ["Backed", "Partly backed", "Not backed", "Contradicted", "Needs review", "Not a claim"];

function evidenceLine(card: EvidenceCardModel): string {
  const ids = card.ids.join(", ");
  switch (card.kind) {
    case "photo":
      return `${ids} · photo ${card.photoIndex}: \`${card.printed ?? card.first.detail}\``;
    case "certificate":
      return `${ids} · certificate (${card.first.certifier ?? "mark"}) covers the ${card.first.cert_scope ?? "unknown"}, not this product`;
    case "registry": {
      const m = card.registry?.match;
      return m
        ? `${ids} · CPCB certified list, S.No. ${m.s_no}: ${m.name}, ${m.state} (name match ${card.registry?.score.toFixed(2)})`
        : `${ids} · ${card.first.detail}`;
    }
    case "qr":
      return `${ids} · QR code on photo ${card.photoIndex}: links to ${card.qr?.domain}${card.qr?.path ?? ""} (${card.qr?.followed ? "opened, the store's own site" : "not followed, another site"})`;
    case "conflict":
      return card.conflict
        ? `${ids} · conflict: “${card.conflict.a}” (${card.conflict.aTag}) vs “${card.conflict.b}” (${card.conflict.bTag})`
        : `${ids} · ${card.first.detail}`;
    default:
      return `${ids} · ${card.location ?? "page"}: “${card.quote ?? card.first.detail}”`;
  }
}

export function toMarkdown(
  state: CaseState,
  opts: { caseLabel: string; when: string | null; approval: Approval | null; reviews?: readonly Review[] },
): string {
  const out: string[] = [];
  const reviews = opts.reviews ?? [];
  const latest = latestReviews(reviews);
  const listing = state.listing;
  out.push(`# Praman proof report: case ${opts.caseLabel}`, "");
  if (listing) {
    out.push(`**Listing:** ${listing.title}  `);
    if (listing.store) out.push(`**Store:** ${listing.store}  `);
  }
  out.push(`**Checked:** ${formatDateTime(opts.when)} · mode ${state.mode === "baseline" ? "text-only" : "agent"} · model answers ${state.llmMode ?? "unknown"}`, "");

  const counts = finalCounts(state, latest);
  out.push("## Summary", "");
  out.push(
    ORDER.filter((l) => counts[l])
      .map((l) => `- ${l}: ${counts[l]}`)
      .join("\n") || "- No claims found.",
    "",
    ...(state.finished?.quota_reached ? ["Model quota reached: claims not yet checked are marked Needs review.", ""] : []),
  );

  const cards = evidenceCards(state);
  out.push("## Claims", "");
  for (const c of state.claims) {
    const v = state.verdicts[c.id];
    out.push(`### ${c.id} · ${finalLabel(state, latest, c.id) ?? "No verdict"}`, "");
    out.push(`> ${c.quote}`, "");
    out.push(`*${locationLabel(c).toLowerCase()} · ${c.type} · ${c.scope}${c.derived_from ? ` · label check from ${c.derived_from}` : ""}*`, "");
    if (v) {
      out.push(v.reason, "");
      if (v.missing && v.label !== "Backed" && v.label !== "Not a claim") out.push(`**What would change it:** ${v.missing}`, "");
    } else if (c.not_claim_reason) {
      out.push(c.not_claim_reason, "");
    }
    const mine = cards.filter((card) => card.links.some((l) => l.claimId === c.id));
    if (mine.length) {
      out.push("**Evidence**", "");
      for (const card of mine) out.push(`- ${evidenceLine(card)}`);
      out.push("");
    }
    const rules = (v?.rules?.length ? v.rules.map((r) => r.id) : c.rule_ids).map((id) => state.rules[id] ?? null);
    const cited = rules.filter((r) => r !== null);
    if (cited.length) {
      out.push("**Rules**", "");
      for (const r of cited) out.push(`- ${r.id} · ${r.name} (${r.source}${r.clause && !/to be confirmed/i.test(r.clause) ? `, ${r.clause}` : ""})`);
      out.push("");
    }
    if (v?.rewrite && v.label !== "Backed" && v.label !== "Not a claim") out.push(`**Suggested wording:** ${v.rewrite}`, "");
    if (v?.sources_searched.length) out.push(`*Sources searched: ${v.sources_searched.join(", ")}*`, "");
    const r = latest[c.id];
    if (r) out.push(`**Human review:** ${reviewLine(r)} (${r.reviewer}, ${formatDateTime(r.at)})`, "");
  }

  if (opts.approval) {
    out.push("---", "", `Reviewed and approved by ${opts.approval.name}, ${formatDateTime(opts.approval.at)}.`, "");
  }
  const log = decisionLog(state, reviews, opts.approval);
  if (log.length) {
    out.push("## Decision log", "");
    for (const e of log) out.push(`- ${e.at ? `${formatDateTime(e.at)} · ` : ""}${e.who} · ${e.what}`);
    out.push("");
  }
  out.push("---", "", disclaimer(formatDate(opts.when)), "");
  return out.join("\n");
}
