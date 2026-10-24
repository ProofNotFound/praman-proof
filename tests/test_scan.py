"""W3 store scan: code-only triage scores, the offline API and the sitemap path (no network)."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from praman import llm
from praman import scan as scans
from praman.anonymise import has_brand
from praman.api import app
from praman.config import reset_settings
from tests.helpers import listing


def row(title, body, tags=None, links=None):
    lst = listing(title=title, body=body, tags=tags, links=links)
    return scans.triage(lst)


def test_vague_terms_point_to_r01():
    r = row("Eco-friendly kitchen towel", "A sustainable towel.")
    assert {t.term for t in r.terms} == {"Eco-friendly".lower(), "sustainable"}
    assert r.score == 4 and r.band == "medium"
    assert all("R01" in t.rule_ids for t in r.terms)
    assert any("R01" in reason for reason in r.reasons)


def test_compostable_plastic_needs_the_registry_and_proof_lowers_the_score():
    bare = row("Compostable garbage bags", "100% compostable.")
    assert bare.terms[0].term == "compostable" and "R07" in bare.terms[0].rule_ids
    assert bare.terms[0].weight == 4
    proven = row(
        "Compostable garbage bags",
        "100% compostable. Tested to IS/ISO 17088. CPCB-UPC-II/TEST MAKER/Gujarat/123",
    )
    kinds = {p.kind for p in proven.proof}
    assert {"cpcb_code", "standard"} <= kinds
    assert not any(p.text == "ISO 17088" for p in proven.proof)  # counted once as IS/ISO 17088
    assert proven.score == 0 and proven.band == "low"
    assert any(reason.startswith("Proof signal:") for reason in proven.reasons)


def test_not_a_claim_word_and_name_lookalikes():
    r = row("Cotton tee", "Only ₹299. Will be delivered soon. Free of charge returns.")
    assert r.terms == [] and r.band == "none" and r.score == 0
    candle = row("Cosmos gin candle", "An eco-friendly candle named after the Cosmos.")
    assert not any(p.text == "COSMOS" for p in candle.proof)
    cert = row("Face cream", "Natural cream, COSMOS certified organic.")
    assert any(p.text == "COSMOS" and p.kind == "certifier" for p in cert.proof)


def test_certificate_numbers_links_and_company_marks():
    r = row(
        "Recyclable bottle",
        "Recyclable PET. Certificate No: ABC-12345. We are a B Corp.",
        links=["https://shop.example/pages/certificates"],
    )
    kinds = [p.kind for p in r.proof]
    assert "certificate_number" in kinds and "company_mark" in kinds
    assert "certificate_link" in kinds


def test_rank_puts_most_unproven_first():
    rows = [
        row("Soap", "Pure soap."),
        row("Bags", "Compostable bags, biodegradable and eco-friendly."),
        row("Tee", "Cotton."),
    ]
    ranked = scans.rank(rows)
    assert [r.title for r in ranked] == ["Bags", "Soap", "Tee"]
    assert [r.rank for r in ranked] == [1, 2, 3]


# ---------------------------------------------------------------------------
# API, offline: the store's products.json comes from the scan cache (a fixture here)


@pytest.fixture
def client(monkeypatch, fixtures_dir):
    monkeypatch.setattr(scans, "SCANS_CACHE", fixtures_dir / "scan")
    with TestClient(app) as c:
        yield c


def _wait(client, scan_id, timeout=20):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        body = client.get(f"/api/scans/{scan_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("scan didn't finish")


def test_scan_api_ranks_a_store_with_zero_model_calls(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "call", lambda *a, **k: calls.append(a))
    r = client.post("/api/scans", json={"url": "https://www.shop.example/collections/all"})
    assert r.status_code == 200
    body = _wait(client, r.json()["scan_id"])
    assert body["status"] == "finished", body["message"]
    assert body["label"] == "Triage, not a verdict" and body["model_calls"] == 0 and calls == []
    assert body["source"] == "shopify" and body["total"] == body["done"] == 5
    titles = [row["title"] for row in body["rows"]]
    assert titles[0] == "Compostable Garbage Bags"
    assert titles[-1] == "Cotton T-shirt"
    assert [row["rank"] for row in body["rows"]] == [1, 2, 3, 4, 5]
    first = body["rows"][0]
    assert first["band"] == "high" and any("R07" in t["rule_ids"] for t in first["terms"])
    assert first["url"].endswith("/products/compostable-garbage-bags")
    assert "shop.example" not in json.dumps(body)  # the store domain is anonymised
    assert not has_brand(json.dumps(body))


def test_check_this_product_needs_live_mode_for_a_new_store(client):
    sid = client.post("/api/scans", json={"url": "shop.example"}).json()["scan_id"]
    _wait(client, sid)
    r = client.post("/api/runs", json={"scan_id": sid, "product": 0, "mode": "agent"})
    assert r.status_code == 409 and "live mode" in r.json()["detail"]
    assert client.post("/api/runs", json={"scan_id": sid, "product": 99}).status_code == 404


def test_scan_needs_the_network_offline_and_a_web_address(client):
    r = client.post("/api/scans", json={"url": "https://nowhere.example"})
    assert r.status_code == 409 and "offline" in r.json()["detail"]
    assert client.post("/api/scans", json={"url": "ftp://shop.example"}).status_code == 422
    assert client.get("/api/scans/S0000").status_code == 404


# ---------------------------------------------------------------------------
# Sitemap path over a fake network (replay mode, httpx.MockTransport)


def test_sitemap_scan_reads_product_pages(monkeypatch, tmp_path, fixtures_dir):
    monkeypatch.setenv("PRAMAN_LLM_MODE", "replay")
    reset_settings()
    monkeypatch.setattr(scans, "SCANS_CACHE", tmp_path)
    page = (fixtures_dir / "html" / "jsonld.html").read_text()
    shell = (fixtures_dir / "html" / "js_shell.html").read_text()
    xml = "application/xml"
    routes = {
        "/robots.txt": httpx.Response(
            200, text="User-agent: *\nSitemap: https://shop.example/sitemap_index.xml\n"
        ),
        "/sitemap_index.xml": httpx.Response(
            200,
            headers={"content-type": xml},
            text="<sitemapindex><sitemap><loc>https://shop.example/sitemap_pages.xml</loc></sitemap>"
            "<sitemap><loc>https://shop.example/sitemap_products_1.xml</loc></sitemap></sitemapindex>",
        ),
        "/sitemap_products_1.xml": httpx.Response(
            200,
            headers={"content-type": xml},
            text="<urlset><url><loc>https://shop.example/products/cutlery</loc></url>"
            "<url><loc>https://shop.example/product/app-item</loc></url>"
            "<url><loc>https://other.example/products/x</loc></url>"
            "<url><loc>https://shop.example/pages/about</loc></url></urlset>",
        ),
        "/sitemap_pages.xml": httpx.Response(200, headers={"content-type": xml}, text="<urlset/>"),
        "/products/cutlery": httpx.Response(200, headers={"content-type": "text/html"}, text=page),
        "/product/app-item": httpx.Response(200, headers={"content-type": "text/html"}, text=shell),
    }

    def handler(request):
        return routes.get(request.url.path, httpx.Response(404))

    from praman.tools.fetch import PoliteClient

    client = PoliteClient(min_gap_s=0)
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    sc = scans.run_scan(scans.new_scan("https://shop.example"), client=client)
    assert sc.status == "finished", sc.message
    assert sc.source == "sitemap" and sc.total == 2
    first, second = sc.rows
    assert first.title == "Bamboo Cutlery Set" and first.score > 0
    assert {t.term for t in first.terms} >= {"biodegradable", "plastic-free"}
    assert second.error and second.band == "none"


def test_the_same_triage_runs_on_the_food_label_pack():
    page = listing(
        "Organic Jaggery Powder",
        "100% natural and farm fresh. Boosts immunity. No added sugar.",
    )
    row = scans.triage(page, pack="food_labels")
    rules = {r for t in row.terms for r in t.rule_ids}
    assert {"F01", "F02", "F03", "F04"} <= rules and row.band == "high"
    assert all(r.startswith("F") for r in rules)
    assert not scans.triage(page).terms or all(  # the green pack sees no food rules
        not r.startswith("F") for t in scans.triage(page).terms for r in t.rule_ids
    )
    proven = listing("Organic Jaggery Powder", "Certified organic: India Organic, NPOP.")
    assert scans.triage(proven, pack="food_labels").proof  # the certifier lowers the score


def test_scan_api_takes_a_rule_pack(client, monkeypatch):
    monkeypatch.setattr(llm, "call", lambda *a, **k: pytest.fail("no model calls in a scan"))
    r = client.post("/api/scans", json={"url": "https://www.shop.example/", "pack": "food_labels"})
    assert r.status_code == 200
    body = _wait(client, r.json()["scan_id"])
    assert body["status"] == "finished" and body["pack"] == "food_labels"
    assert all(
        rid.startswith("F") for row in body["rows"] for t in row["terms"] for rid in t["rule_ids"]
    )
    bad = client.post("/api/scans", json={"url": "https://www.shop.example/", "pack": "nope"})
    assert bad.status_code == 422
