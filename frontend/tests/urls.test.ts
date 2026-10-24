import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { matchDemoUrl, parseProductUrl, sha256Hex, validateUrlKeys, type DemoUrlKey } from "../src/lib/urls";

const parsed = (raw: string) => {
  const p = parseProductUrl(raw);
  if (!p.ok) throw new Error(p.error);
  return p;
};

describe("parseProductUrl", () => {
  it("accepts http(s), adds https:// to a bare address and finds the handle", () => {
    expect(parsed("https://www.Shop.example/products/Green-Bags?variant=1")).toMatchObject({
      host: "shop.example",
      handle: "green-bags",
    });
    expect(parsed("shop.example/products/green-bags.json").url).toBe("https://shop.example/products/green-bags.json");
    expect(parsed("http://shop.example/").handle).toBeNull();
  });

  it("says plainly what is wrong", () => {
    expect(parseProductUrl("  ")).toEqual({ ok: false, error: "Paste a product page URL first." });
    const ftp = parseProductUrl("ftp://shop.example/x");
    expect(ftp.ok).toBe(false);
    if (!ftp.ok) expect(ftp.error).toContain("http://");
    expect(parseProductUrl("not a url").ok).toBe(false);
  });
});

describe("matchDemoUrl", () => {
  const keysFor = async (store: string, realStore: string, handle: string, id: string): Promise<DemoUrlKey> => ({
    listing_id: id,
    store,
    store_sha256: await sha256Hex(realStore),
    handle_sha256: await sha256Hex(handle),
  });

  it("matches the real URL, the anonymised domain and the handle", async () => {
    const keys = [
      await keysFor("brand-e.example", "realstore.example", "bags-a", "L14"),
      await keysFor("brand-c.example", "otherstore.example", "brush-b", "L08"),
      await keysFor("brand-c.example", "otherstore.example", "course-c", "L21"),
    ];
    expect(await matchDemoUrl(parsed("https://realstore.example/products/bags-a"), keys)).toEqual(["L14"]);
    expect(await matchDemoUrl(parsed("www.realstore.example/products/BAGS-A/"), keys)).toEqual(["L14"]);
    expect(await matchDemoUrl(parsed("brand-c.example/products/course-c"), keys)).toEqual(["L21"]);
    expect(await matchDemoUrl(parsed("https://brand-c.example"), keys)).toEqual(["L08", "L21"]);
    expect(await matchDemoUrl(parsed("https://realstore.example/products/other"), keys)).toEqual([]);
    expect(await matchDemoUrl(parsed("https://unknown.example/products/bags-a"), keys)).toEqual([]);
  });

  it("the bundled keys cover the four demo cases and carry no store name", () => {
    const keys = validateUrlKeys(JSON.parse(readFileSync(join(__dirname, "..", "public", "demo", "urls.json"), "utf8")));
    expect(keys.map((k) => k.listing_id).sort()).toEqual(["L06", "L08", "L14", "L21"]);
    for (const k of keys) expect(k.store).toMatch(/^brand-[a-z]\.example$/);
  });
});
