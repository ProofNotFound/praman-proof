"""SQLite storage (TRD §12). One shared connection per database path, guarded by a lock."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from praman.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    llm_mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    llm_calls INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    est_cost_inr REAL DEFAULT 0,
    approved_by TEXT,
    approved_at TEXT,
    status TEXT DEFAULT 'running',
    listing_json TEXT,
    provenance_json TEXT,
    approval_hash TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    run_id TEXT NOT NULL,
    n INTEGER NOT NULL,
    claim_id TEXT,
    phase TEXT NOT NULL,
    tool TEXT,
    summary TEXT NOT NULL,
    payload_json TEXT,
    ms INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, n)
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    t_ms INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS claims (
    run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    quote TEXT,
    type TEXT,
    scope TEXT,
    location TEXT,
    is_claim INTEGER,
    rule_ids_json TEXT,
    claim_json TEXT,
    PRIMARY KEY (run_id, claim_id)
);
CREATE TABLE IF NOT EXISTS evidence (
    run_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    claim_id TEXT,
    source TEXT,
    detail TEXT,
    photo_index INTEGER,
    crop_box_json TEXT,
    covers_claim TEXT,
    certifier TEXT,
    cert_scope TEXT,
    evidence_json TEXT,
    PRIMARY KEY (run_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS verdicts (
    run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    label TEXT,
    evidence_ids_json TEXT,
    rule_ids_json TEXT,
    reason TEXT,
    missing TEXT,
    rewrite TEXT,
    verdict_json TEXT,
    PRIMARY KEY (run_id, claim_id)
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    model TEXT,
    template TEXT,
    response_json TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    created_at TEXT,
    listing_id TEXT
);
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id TEXT NOT NULL,
    listing_id TEXT,
    claim_ref TEXT,
    mode TEXT,
    predicted TEXT,
    expected TEXT,
    match INTEGER
);
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    store TEXT,
    store_url TEXT,
    status TEXT,
    source TEXT,
    total INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    message TEXT,
    rows_json TEXT,
    pack TEXT
);
CREATE TABLE IF NOT EXISTS anon_names (
    key TEXT PRIMARY KEY,
    letter TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    label TEXT NOT NULL,
    ai_label TEXT,
    reason TEXT,
    reviewer TEXT NOT NULL,
    at TEXT NOT NULL,
    prev_hash TEXT,
    hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_listing ON runs(listing_id, mode, started_at);
CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews(run_id, at);
"""

# Columns added after the first release: older databases get them on open (NULL for old rows)
ADDED_COLUMNS = {
    "runs": {"provenance_json": "TEXT", "approval_hash": "TEXT"},
    "reviews": {"prev_hash": "TEXT", "hash": "TEXT"},
    "scans": {"pack": "TEXT"},
}

_lock = threading.RLock()
_conns: dict[str, sqlite3.Connection] = {}


def _path() -> Path:
    return get_settings().db_path


def conn() -> sqlite3.Connection:
    """Shared connection for the configured database (created and migrated on first use)."""
    p = _path()
    key = str(p)
    with _lock:
        c = _conns.get(key)
        if c is None:
            p.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(key, check_same_thread=False, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            _migrate(c)
            _conns[key] = c
        return c


def _migrate(c: sqlite3.Connection) -> None:
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, kind in cols.items():
            if col not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")


def close_all() -> None:
    with _lock:
        for c in _conns.values():
            c.close()
        _conns.clear()


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with _lock:
        conn().execute(sql, tuple(params))


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
