"""API (TRD §16): offline, through FastAPI's TestClient."""

import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from praman.anonymise import has_brand
from praman.api import app
from praman.events import validate_event


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _wait_finished(client, run_id, timeout=20):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run didn't finish")


def _read_sse(client, run_id, headers=None):
    events = []
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers or {}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        cur: dict = {}
        for line in r.iter_lines():
            if line.startswith("event:"):
                cur["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("id:"):
                cur["id"] = int(line.split(":", 1)[1])
            elif line.startswith("data:"):
                cur["data"] = json.loads(line.split(":", 1)[1])
            elif line == "" and cur:
                events.append(cur)
                cur = {}
    return events


def test_health(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["llm_mode"] == "offline" and h["anonymise"] is True
    assert h["cpcb_list_date"] == "2023-10-26"


def test_listings_are_anonymised_and_demo_cases_come_first(client):
    rows = client.get("/api/listings").json()
    assert [r["id"] for r in rows[:4]] == ["L14", "L06", "L08", "L21"]
    assert not has_brand(json.dumps(rows))
    one = client.get("/api/listings/L14").json()
    assert one["photos"][6]["url"] == "/api/photos/L14/7"
    assert "example" in one["store"] and not has_brand(json.dumps(one))
    assert client.get("/api/listings/L99").status_code == 404


def test_l14_streams_valid_events_in_order(client):
    run_id = client.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).json()["run_id"]
    events = _read_sse(client, run_id)
    assert events[0]["event"] == "run_started" and events[-1]["event"] == "run_finished"
    assert [e["id"] for e in events] == list(range(1, len(events) + 1))
    for e in events:
        validate_event(e["data"])
        assert e["data"]["type"] == e["event"]
    assert not has_brand(json.dumps([e["data"] for e in events]))
    # Resume after event 10: only later events come back
    later = _read_sse(client, run_id, {"Last-Event-ID": "10"})
    assert later[0]["id"] == 11 and later[-1]["event"] == "run_finished"


REVIEWER = {"X-Praman-Role": "reviewer"}


def _review_open_claims(client, run_id):
    for v in client.get(f"/api/runs/{run_id}").json()["verdicts"]:
        if v["label"] == "Needs review":
            r = client.post(
                f"/api/runs/{run_id}/reviews/{v['claim_id']}",
                json={"name": "Test Reviewer", "decision": "agree"},
                headers=REVIEWER,
            )
            assert r.status_code == 200


def test_only_a_reviewer_decides_and_open_claims_block_approval(client):
    run_id = client.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).json()["run_id"]
    _wait_finished(client, run_id)
    verdicts = client.get(f"/api/runs/{run_id}").json()["verdicts"]
    open_ = next(v for v in verdicts if v["label"] == "Needs review")
    contra = next(v for v in verdicts if v["label"] == "Contradicted")
    url = f"/api/runs/{run_id}/reviews/{open_['claim_id']}"
    agree = {"name": "Asha", "decision": "agree"}

    # Analysts (or no role) can't decide or sign
    assert client.post(url, json=agree).status_code == 403
    assert client.post(url, json=agree, headers={"X-Praman-Role": "analyst"}).status_code == 403
    approve = f"/api/runs/{run_id}/approve"
    assert client.post(approve, json={"name": "Asha"}).status_code == 403

    # A Needs-review claim without a human decision blocks the sign-off
    r = client.post(approve, json={"name": "Asha"}, headers=REVIEWER)
    assert r.status_code == 409 and open_["claim_id"] in r.json()["detail"]

    # Changing a verdict needs a different label and a reason
    change = {"name": "Asha", "decision": "change", "label": "Not backed"}
    assert client.post(url, json=change, headers=REVIEWER).status_code == 422
    same = {**change, "label": "Needs review", "reason": "x"}
    assert client.post(url, json=same, headers=REVIEWER).status_code == 422
    r = client.post(url, json={**change, "reason": "No certificate on the pack."}, headers=REVIEWER)
    assert r.status_code == 200 and r.json()["ai_label"] == "Needs review"
    c_url = f"/api/runs/{run_id}/reviews/{contra['claim_id']}"
    assert client.post(c_url, json=agree, headers=REVIEWER).status_code == 200

    assert client.post(approve, json={"name": "Asha"}, headers=REVIEWER).status_code == 200
    # Signed reports are closed to further decisions
    assert client.post(url, json=agree, headers=REVIEWER).status_code == 409

    detail = client.get(f"/api/runs/{run_id}").json()
    assert [r["claim_id"] for r in detail["reviews"]] == [open_["claim_id"], contra["claim_id"]]
    md = client.get(f"/api/runs/{run_id}/report.md").text
    assert f"## {open_['claim_id']} · Not backed" in md
    assert "Reviewer changed the verdict from Needs review to Not backed" in md
    assert "## Decision log" in md and "approved the report" in md
    assert "Decision log" in client.get(f"/api/runs/{run_id}/report.html").text


def test_report_needs_approval(client):
    run_id = client.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).json()["run_id"]
    _wait_finished(client, run_id)
    assert client.get(f"/api/runs/{run_id}/report.md").status_code == 409
    assert client.get(f"/api/runs/{run_id}/report.html").status_code == 409
    _review_open_claims(client, run_id)
    r = client.post(f"/api/runs/{run_id}/approve", json={"name": "Test Reviewer"}, headers=REVIEWER)
    assert r.status_code == 200 and r.json()["approved_by"] == "Test Reviewer"
    md = client.get(f"/api/runs/{run_id}/report.md")
    assert md.status_code == 200
    text = md.text
    assert "Decision support, not legal advice. Based on what is visible on the listing on" in text
    assert "CPCB list dated 26 Oct 2023." in text
    assert "Test Reviewer" in text and "Backed" in text
    assert not has_brand(text)
    html = client.get(f"/api/runs/{run_id}/report.html").text
    assert "<!doctype html>" in html and "Test Reviewer" in html and not has_brand(html)
    # Our own words only: official citation URLs keep their file names
    prose = re.sub(r"https?://\S+", "", text).lower()
    for bad in ("illegal", "violation", "greenwashing", "fraud", "lying"):
        assert bad not in prose


def test_run_detail_recording_and_compare(client):
    a = client.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).json()["run_id"]
    b = client.post("/api/runs", json={"listing_id": "L14", "mode": "baseline"}).json()["run_id"]
    _wait_finished(client, a)
    _wait_finished(client, b)
    detail = client.get(f"/api/runs/{a}").json()
    assert {"run", "listing", "claims", "evidence", "verdicts", "steps"} <= set(detail)
    assert not has_brand(json.dumps(detail))
    rec = client.get(f"/api/runs/{a}/recording").json()
    assert rec["format"] == "praman-recording/1" and rec["synthetic"] is False
    cmp = client.get("/api/compare/L14").json()
    assert cmp["agent"]["run_id"] == a and cmp["baseline"]["run_id"] == b
    compostable = next(p for p in cmp["pairs"] if "compostable garbage" in p["quote"])
    assert compostable["agent"] == "Backed" and compostable["baseline"] == "Not backed"
    assert compostable["differs"] is True


def test_url_runs_only_in_live_mode(client):
    r = client.post("/api/runs", json={"url": "https://shop.example/products/x", "mode": "agent"})
    assert r.status_code == 409 and "live mode" in r.json()["detail"]


def test_eval_pending_or_results(client):
    data = client.get("/api/eval").json()
    assert data.get("status") in ("pending", "done")


def test_unknown_api_path_is_404_and_photo_is_served(client):
    assert client.get("/api/nope").status_code == 404
    r = client.get("/api/photos/L14/7")
    if r.status_code == 404:
        pytest.skip("photos aren't cached in this checkout")
    assert r.headers["content-type"] == "image/jpeg" and len(r.content) > 1000


def test_seed_urls_open_their_case_in_any_mode(client):
    import csv

    from praman.anonymise import brand_letter
    from praman.api import seed_for_url
    from praman.config import SEED_PATH

    row = next(r for r in csv.DictReader(SEED_PATH.open()) if r["id"] == "L14")
    letter = brand_letter("L14").lower()
    assert seed_for_url(row["url"]) == "L14"
    assert seed_for_url(row["url"] + "?variant=1") == "L14"
    assert seed_for_url(f"brand-{letter}.example/products/{row['handle']}") == "L14"
    assert seed_for_url(f"https://brand-{letter}.example/") is None  # several listings
    assert seed_for_url("https://shop.example/products/x") is None
    r = client.post("/api/runs", json={"url": row["url"], "mode": "agent"})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert run_id.startswith("L14-")
    assert _wait_finished(client, run_id)["status"] == "finished"


def test_url_must_be_http(client):
    r = client.post("/api/runs", json={"url": "ftp://shop.example/x", "mode": "agent"})
    assert r.status_code == 422


def test_a_photo_nobody_has_read_yet_is_served_blurred_and_uncached(client, tmp_path, monkeypatch):
    """A new page's pack photo can show a brand: until the agent has read it, only a blurred copy
    leaves the server, and the browser must not keep it."""
    from datetime import UTC, datetime

    from PIL import Image

    from praman import anonymise, config
    from praman.models import Listing, Photo
    from praman.tools import fetch

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "LISTINGS_DIR", tmp_path / "listings")
    monkeypatch.setattr(fetch, "LISTINGS_DIR", tmp_path / "listings")
    monkeypatch.setattr(fetch, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(fetch, "ROOT", tmp_path)
    monkeypatch.setattr("praman.api.ROOT", tmp_path)
    monkeypatch.setattr(anonymise, "MASKS_DIR", tmp_path / "masks")
    img = tmp_path / "images" / "Unew" / "1.jpg"
    img.parent.mkdir(parents=True)
    Image.new("RGB", (900, 900), "white").save(img)
    lst = Listing(
        id="Unew",
        source="html",
        store="shop.example",
        title="Pack",
        body_text="x",
        fetched_at=datetime.now(UTC),
        photos=[Photo(index=1, url="https://cdn.example/1.jpg")],
    )
    fetch.save_cached(lst)
    r = client.get("/api/photos/Unew/1")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert max(Image.open(__import__("io").BytesIO(r.content)).size) <= 320  # a small blurred copy


def test_a_newer_run_that_has_not_read_the_photos_does_not_blur_an_older_runs_photos(
    client, tmp_path, monkeypatch
):
    """Starting another run of a page must not turn the first run's evidence crops blank."""
    import io
    import json

    from PIL import Image

    from praman import anonymise, config, db
    from praman.models import Listing, Photo
    from praman.tools import fetch

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(fetch, "LISTINGS_DIR", tmp_path / "listings")
    monkeypatch.setattr(fetch, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(fetch, "ROOT", tmp_path)
    monkeypatch.setattr("praman.api.ROOT", tmp_path)
    monkeypatch.setattr(anonymise, "MASKS_DIR", tmp_path / "masks")
    monkeypatch.setattr(anonymise, "ROOT", tmp_path)
    img = tmp_path / "images" / "Unew2" / "1.jpg"
    img.parent.mkdir(parents=True)
    Image.new("RGB", (900, 900), "white").save(img)
    lst = Listing(
        id="Unew2",
        source="html",
        store="shop.example",
        title="Pack",
        body_text="x",
        fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        photos=[Photo(index=1, url="https://cdn.example/1.jpg")],
    )
    fetch.save_cached(lst)
    for run_id, started in (
        ("Unew2-a-1", "2026-10-23T01:00:00"),
        ("Unew2-a-2", "2026-10-23T02:00:00"),
    ):
        db.execute(
            "INSERT INTO runs (id, listing_id, mode, llm_mode, started_at) VALUES (?, ?, 'agent', 'replay', ?)",
            (run_id, "Unew2", started),
        )
    read = {"photos": [{"index": 1, "items": [], "qr_present": False}]}
    db.execute(
        "INSERT INTO events (run_id, seq, type, t_ms, data_json) VALUES (?, 1, 'photo_read', 0, ?)",
        ("Unew2-a-1", json.dumps(read)),
    )  # the older run read photo 1; the newer one hasn't yet
    r = client.get("/api/photos/Unew2/1")
    assert r.headers["cache-control"] != "no-store"
    assert Image.open(io.BytesIO(r.content)).size == (
        900,
        900,
    )  # the real photo, not the 320 px blur


def test_rule_packs_endpoint(client):
    packs = client.get("/api/rule-packs").json()
    names = [p["name"] for p in packs]
    assert names[0] == "green_claims" and "food_labels" in names
    assert all(p["rules"] and p["rules"][0]["terms"] for p in packs)
