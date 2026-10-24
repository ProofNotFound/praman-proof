"""Contract (TRD §16): every event in every recording validates against praman/events.py."""

import json

import pytest

from praman.anonymise import has_brand
from praman.config import RECORDINGS_DIR, ROOT
from praman.events import validate_event

FRONTEND_DEMO = ROOT / "frontend" / "public" / "demo"
# JSON files next to the recordings that aren't recordings
NOT_RECORDINGS = {"index.json", "eval.json", "urls.json", "scan_demo.json", "rule_packs.json"}


def _recordings(folder):
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob("*.json") if p.name not in NOT_RECORDINGS)


def _check(path):
    doc = json.loads(path.read_text())
    if doc.get("synthetic"):
        pytest.skip(f"{path.name} is synthetic")
    assert doc["format"] == "praman-recording/1"
    assert doc["mode"] in ("agent", "baseline")
    events = doc["events"]
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    for e in events:
        validate_event(e)
    listing = next(e for e in events if e["type"] == "listing")["data"]
    for p in listing["photos"]:
        assert p["url"].startswith("demo/photos/"), p["url"]
        assert (path.parent / p["url"].removeprefix("demo/")).exists(), p["url"]
    assert not has_brand(path.read_text())


@pytest.mark.parametrize("path", _recordings(RECORDINGS_DIR), ids=lambda p: p.name)
def test_core_recordings_follow_the_contract(path):
    _check(path)


@pytest.mark.parametrize("path", _recordings(FRONTEND_DEMO), ids=lambda p: p.name)
def test_frontend_recordings_follow_the_contract(path):
    _check(path)


def test_index_lists_every_recording():
    index = json.loads((RECORDINGS_DIR / "index.json").read_text())
    files = {e["file"] for e in index}
    assert files == {p.name for p in _recordings(RECORDINGS_DIR)}
    for e in index:
        assert set(e) >= {"listing_id", "mode", "title", "file", "claim_count", "synthetic"}


def test_demo_url_keys_cover_the_bundled_cases():
    for folder in (RECORDINGS_DIR, FRONTEND_DEMO):
        keys = json.loads((folder / "urls.json").read_text())
        index = json.loads((folder / "index.json").read_text())
        assert {k["listing_id"] for k in keys} == {e["listing_id"] for e in index}
        assert not has_brand(json.dumps(keys))
        assert all(len(k["store_sha256"]) == 64 and k["store"].endswith(".example") for k in keys)


def test_recorded_store_scan_is_anonymised_triage():
    for folder in (RECORDINGS_DIR, FRONTEND_DEMO):
        text = (folder / "scan_demo.json").read_text()
        doc = json.loads(text)
        assert doc["format"] == "praman-scan/1" and doc["label"] == "Triage, not a verdict"
        assert doc["model_calls"] == 0 and doc["status"] == "finished"
        assert not has_brand(text)
        assert [r["rank"] for r in doc["rows"]] == list(range(1, len(doc["rows"]) + 1))
