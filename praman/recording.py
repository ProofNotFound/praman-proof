"""Recordings (TRD §15.4): every event of a run in one JSON document the frontend can replay."""

from __future__ import annotations

import copy
from typing import Any

from praman import db
from praman.events import load_events

FORMAT = "praman-recording/1"


def build_recording(run_id: str, photo_url: str | None = None) -> dict[str, Any] | None:
    """The run's events as a recording. `photo_url` (e.g. "demo/photos/{listing_id}/{n}.jpg")
    rewrites the photo URLs in the listing event; by default they point at the API."""
    run = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if not run:
        return None
    events = load_events(run_id)
    title = ""
    for ev in events:
        if ev["type"] == "listing":
            title = ev["data"].get("title", "")
            if photo_url:
                ev["data"] = copy.deepcopy(ev["data"])
                for p in ev["data"]["photos"]:
                    p["url"] = photo_url.format(listing_id=run["listing_id"], n=p["index"])
    return {
        "format": FORMAT,
        "synthetic": False,
        "listing_id": run["listing_id"],
        "mode": run["mode"],
        "title": title,
        "recorded_at": run["started_at"],
        "llm_mode": run["llm_mode"],
        "run_id": run_id,
        "events": events,
    }


def final_claims(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev["type"] == "claims":
            for c in ev["data"]["claims"]:
                claims[c["id"]] = c
    return list(claims.values())


def final_verdicts(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev["type"] == "verdict":
            out[ev["data"]["claim_id"]] = ev["data"]
    return out


def photo_items(events: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Printed items per photo index from the run's photo_read event."""
    out: dict[int, list[dict[str, Any]]] = {}
    for ev in events:
        if ev["type"] == "photo_read":
            for p in ev["data"]["photos"]:
                out.setdefault(p["index"], []).extend(p["items"])
    return out
