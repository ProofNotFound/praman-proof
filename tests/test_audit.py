"""Provenance and tamper evidence: each run says what it was checked with; reviews form a hash
chain; the sign-off fingerprint stops matching when a stored verdict or review is edited."""

import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from praman import db, provenance
from praman.api import app
from praman.config import RULES_PATH, reset_settings

REVIEWER = {"X-Praman-Role": "reviewer"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _signed_l14(client) -> str:
    run_id = client.post("/api/runs", json={"listing_id": "L14", "mode": "agent"}).json()["run_id"]
    t0 = time.monotonic()
    while True:  # the worker writes the run row
        r = client.get(f"/api/runs/{run_id}")
        if r.status_code == 200 and r.json()["run"]["status"] != "running":
            break
        assert time.monotonic() - t0 < 20
        time.sleep(0.05)
    for v in client.get(f"/api/runs/{run_id}").json()["verdicts"]:
        if v["label"] == "Needs review":
            r = client.post(
                f"/api/runs/{run_id}/reviews/{v['claim_id']}",
                json={"name": "Asha", "decision": "agree"},
                headers=REVIEWER,
            )
            assert r.status_code == 200
    r = client.post(f"/api/runs/{run_id}/approve", json={"name": "Asha"}, headers=REVIEWER)
    assert r.status_code == 200
    return run_id


def test_each_run_records_what_it_was_checked_with(client):
    run_id = _signed_l14(client)
    p = client.get(f"/api/runs/{run_id}").json()["audit"]["provenance"]
    rules = json.loads(RULES_PATH.read_text())
    assert p["rules_version"] == rules["version"] and p["rules_as_of"] == rules["as_of"]
    assert p["prompts"] == provenance.prompts_hash() and len(p["prompts"]) == 12
    assert p["cpcb_list_date"] == "2023-10-26" and p["model"]
    md = client.get(f"/api/runs/{run_id}/report.md").text
    assert f"rulebook {rules['version']} ({rules['as_of']})" in md and "## Audit" in md


def test_signed_report_fingerprint_matches_until_the_record_is_edited(client):
    run_id = _signed_l14(client)
    a = client.get(f"/api/runs/{run_id}").json()["audit"]
    assert a["reviews"] >= 1 and a["reviews_intact"] is True
    assert a["fingerprint"] and a["fingerprint_matches"] is True
    md = client.get(f"/api/runs/{run_id}/report.md").text
    assert a["fingerprint"] in md and "matches the stored record" in md

    # Someone edits a stored verdict after the sign-off
    row = db.query_one("SELECT rowid, verdict_json FROM verdicts WHERE run_id = ?", (run_id,))
    v = json.loads(row["verdict_json"])
    v["label"] = "Backed" if v["label"] != "Backed" else "Not backed"
    db.execute(
        "UPDATE verdicts SET verdict_json = ? WHERE rowid = ?", (json.dumps(v), row["rowid"])
    )
    assert client.get(f"/api/runs/{run_id}").json()["audit"]["fingerprint_matches"] is False
    assert "does NOT match" in client.get(f"/api/runs/{run_id}/report.md").text


def test_editing_a_review_breaks_the_chain(client):
    run_id = _signed_l14(client)
    db.execute("UPDATE reviews SET reviewer = 'Someone else' WHERE run_id = ?", (run_id,))
    a = client.get(f"/api/runs/{run_id}").json()["audit"]
    assert a["reviews_intact"] is False and a["fingerprint_matches"] is False


def test_chain_links_each_review_to_the_one_before():
    rows, prev = [], provenance.GENESIS
    for i in range(3):
        r = {"run_id": "R", "claim_id": f"C{i}", "decision": "agree", "label": "Backed",
             "ai_label": "Backed", "reason": "", "reviewer": "Asha", "at": f"2026-10-24T0{i}"}  # fmt: skip
        r["prev_hash"], r["hash"] = prev, provenance.review_hash(prev, r)
        prev = r["hash"]
        rows.append(r)
    assert provenance.chain_ok(rows) == (True, prev)
    assert provenance.chain_ok([rows[0], rows[2]])[0] is False  # one removed


def test_an_older_database_gets_the_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old_schema = db.SCHEMA
    for cols in db.ADDED_COLUMNS.values():
        for col, kind in cols.items():
            old_schema = old_schema.replace(f",\n    {col} {kind}", "")
    assert "provenance_json" not in old_schema and "prev_hash" not in old_schema
    c = sqlite3.connect(path)
    c.executescript(old_schema)
    c.commit()
    c.close()
    monkeypatch.setenv("PRAMAN_DB_PATH", str(path))
    reset_settings()
    try:
        cols = {r["name"] for r in db.query("PRAGMA table_info(runs)")}
        assert {"provenance_json", "approval_hash"} <= cols
        cols = {r["name"] for r in db.query("PRAGMA table_info(reviews)")}
        assert {"prev_hash", "hash"} <= cols
    finally:
        db.close_all()
        reset_settings()
