// Rule packs (reusability): one JSON rulebook per domain, read by the same engine. The list comes
// from /api/rule-packs, or from demo/rule_packs.json in recording mode.

export interface PackRule {
  id: string;
  name: string;
  summary: string;
  clause: string;
  source: string;
  terms: string[];
  evidence: string[];
}

export interface RulePack {
  name: string;
  title: string;
  domain: string;
  status: string;
  status_note: string;
  version: string | null;
  sources: string[];
  rules: PackRule[];
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}
const str = (x: unknown): string => (typeof x === "string" ? x : "");
const strs = (x: unknown): string[] => (Array.isArray(x) ? x.filter((s): s is string => typeof s === "string") : []);

export function parsePacks(x: unknown): RulePack[] {
  if (!Array.isArray(x)) return [];
  return x.filter(isRecord).map((p) => ({
    name: str(p.name),
    title: str(p.title) || str(p.name),
    domain: str(p.domain),
    status: str(p.status),
    status_note: str(p.status_note),
    version: typeof p.version === "string" ? p.version : null,
    sources: strs(p.sources),
    rules: (Array.isArray(p.rules) ? p.rules : []).filter(isRecord).map((r) => ({
      id: str(r.id),
      name: str(r.name),
      summary: str(r.summary),
      clause: str(r.clause),
      source: str(r.source),
      terms: strs(r.terms),
      evidence: strs(r.evidence),
    })),
  }));
}

const normalise = (s: string): string =>
  s.toLowerCase().replace(/[’]/g, "'").replace(/[–—]/g, "-").replace(/\s+/g, " ").trim();

const escape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Trigger terms of a rule found in the text, on word edges (as praman/rules.py matches them). */
export function matchedTerms(rule: PackRule, text: string): string[] {
  const norm = `${normalise(text)} `;
  return rule.terms.filter((t) => {
    const core = normalise(t);
    if (!core) return false;
    const tail = /[a-z]$/.test(core) ? "(?![a-z])" : "";
    return new RegExp(`(?<![a-z0-9])${escape(core)}${tail}`).test(norm);
  });
}

/** Which rules of a pack a piece of text calls on, with the words that triggered each. */
export function triggeredRules(pack: RulePack, text: string): { rule: PackRule; terms: string[] }[] {
  return pack.rules.map((rule) => ({ rule, terms: matchedTerms(rule, text) })).filter((m) => m.terms.length > 0);
}
