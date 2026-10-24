// The intake URL box: validate what was typed, and recognise a demo listing's URL without the
// backend. public/demo/urls.json holds each demo case's anonymised store domain plus SHA-256
// hashes of its real store domain and product handle, so no brand domain ships in the app.

export interface DemoUrlKey {
  listing_id: string;
  /** anonymised domain the app shows, e.g. "brand-e.example" */
  store: string;
  store_sha256: string;
  handle_sha256: string;
}

export type ParsedUrl = { ok: true; url: string; host: string; handle: string | null } | { ok: false; error: string };

/** http(s) only; a bare "store.example/products/x" gets https:// in front. */
export function parseProductUrl(raw: string): ParsedUrl {
  const text = raw.trim();
  if (!text) return { ok: false, error: "Paste a product page URL first." };
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(text) ? text : `https://${text}`;
  let u: URL;
  try {
    u = new URL(withScheme);
  } catch {
    return { ok: false, error: "That doesn't look like a web address. Paste the product page's URL." };
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    return { ok: false, error: "Enter a web address that starts with http:// or https://." };
  }
  if (!u.hostname.includes(".")) {
    return { ok: false, error: "That doesn't look like a web address. Paste the product page's URL." };
  }
  const m = /\/products\/([^/?#]+?)(?:\.json)?\/?$/.exec(u.pathname);
  let handle: string | null = null;
  if (m?.[1]) {
    try {
      handle = decodeURIComponent(m[1]).toLowerCase();
    } catch {
      handle = m[1].toLowerCase();
    }
  }
  return { ok: true, url: u.toString(), host: u.hostname.toLowerCase().replace(/^www\./, ""), handle };
}

export async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text.trim().toLowerCase());
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Listing ids whose URL this is: by store (real or anonymised), then by handle when given. */
export async function matchDemoUrl(parsed: Extract<ParsedUrl, { ok: true }>, keys: readonly DemoUrlKey[]): Promise<string[]> {
  const hostHash = await sha256Hex(parsed.host);
  let hits = keys.filter((k) => k.store === parsed.host || k.store_sha256 === hostHash);
  if (parsed.handle) {
    const handleHash = await sha256Hex(parsed.handle);
    hits = hits.filter((k) => k.handle_sha256 === handleHash);
  }
  return [...new Set(hits.map((k) => k.listing_id))];
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

export function validateUrlKeys(x: unknown): DemoUrlKey[] {
  if (!Array.isArray(x)) return [];
  return x.filter(
    (k): k is DemoUrlKey =>
      isRecord(k) &&
      typeof k.listing_id === "string" &&
      typeof k.store === "string" &&
      typeof k.store_sha256 === "string" &&
      typeof k.handle_sha256 === "string",
  );
}
