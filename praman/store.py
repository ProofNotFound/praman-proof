"""Read a run back from SQLite: run row, listing, claims, evidence, verdicts and steps."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from praman import db, provenance
from praman.models import Claim, Evidence, Listing, Step, Verdict


def get_run(run_id: str) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))


def latest_run(listing_id: str, mode: str, finished_only: bool = True) -> dict[str, Any] | None:
    status = "AND status = 'finished'" if finished_only else ""
    return db.query_one(
        f"SELECT * FROM runs WHERE listing_id = ? AND mode = ? {status} "
        "ORDER BY started_at DESC LIMIT 1",
        (listing_id, mode),
    )


def photo_reads(listing_id: str) -> list[dict[str, Any]]:
    """The photo_read events of every agent run of a listing, oldest first: once any run has read
    a photo's print, that photo's brand marks are known, whichever run is looked at."""
    import json

    rows = db.query(
        "SELECT e.data_json FROM events e JOIN runs r ON r.id = e.run_id "
        "WHERE r.listing_id = ? AND r.mode = 'agent' AND e.type = 'photo_read' "
        "ORDER BY r.started_at, e.seq",
        (listing_id,),
    )
    return [{"type": "photo_read", "data": json.loads(r["data_json"])} for r in rows]


def run_listing_model(run: dict[str, Any]) -> Listing | None:
    raw = run.get("listing_json")
    return Listing.model_validate_json(raw) if raw else None


def claims(run_id: str) -> list[Claim]:
    rows = db.query("SELECT claim_json FROM claims WHERE run_id = ? ORDER BY rowid", (run_id,))
    out = [Claim.model_validate_json(r["claim_json"]) for r in rows]
    return sorted(out, key=lambda c: int(c.id[1:]) if c.id[1:].isdigit() else 0)


def evidence(run_id: str) -> list[Evidence]:
    rows = db.query("SELECT evidence_json FROM evidence WHERE run_id = ?", (run_id,))
    out = [Evidence.model_validate_json(r["evidence_json"]) for r in rows]
    return sorted(out, key=lambda e: int(e.id[1:]))


def verdicts(run_id: str) -> dict[str, Verdict]:
    rows = db.query("SELECT verdict_json FROM verdicts WHERE run_id = ?", (run_id,))
    return {v.claim_id: v for v in (Verdict.model_validate_json(r["verdict_json"]) for r in rows)}


def steps(run_id: str) -> list[Step]:
    rows = db.query("SELECT * FROM steps WHERE run_id = ? ORDER BY n", (run_id,))
    return [
        Step(
            run_id=run_id,
            claim_id=r["claim_id"],
            n=r["n"],
            phase=r["phase"],
            tool=r["tool"],
            summary=r["summary"],
            payload=json.loads(r["payload_json"] or "{}"),
            ms=r["ms"] or 0,
            tokens_in=r["tokens_in"] or 0,
            tokens_out=r["tokens_out"] or 0,
        )
        for r in rows
    ]


def add_review(
    run_id: str, claim_id: str, decision: str, label: str, ai_label: str, reason: str, name: str
) -> dict[str, Any]:
    """Append a reviewer's decision on one claim; the history is kept, the latest one counts.
    Each decision hashes the one before it (provenance.chain_ok checks the chain)."""
    row = {
        "run_id": run_id,
        "claim_id": claim_id,
        "decision": decision,
        "label": label,
        "ai_label": ai_label,
        "reason": reason.strip(),
        "reviewer": name.strip(),
        "at": datetime.now(UTC).isoformat(),
    }
    with db._lock:
        last = db.query_one(
            "SELECT hash FROM reviews WHERE run_id = ? ORDER BY at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        prev = (last or {}).get("hash") or provenance.GENESIS
        digest = provenance.review_hash(prev, row)
        db.execute(
            "INSERT INTO reviews (run_id, claim_id, decision, label, ai_label, reason, reviewer, "
            "at, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*row.values(), prev, digest),
        )
    return row


def reviews(run_id: str) -> list[dict[str, Any]]:
    """Every reviewer decision on a run, oldest first (the audit trail)."""
    return db.query(
        "SELECT claim_id, decision, label, ai_label, reason, reviewer, at FROM reviews "
        "WHERE run_id = ? ORDER BY at, rowid",
        (run_id,),
    )


def _review_rows(run_id: str) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM reviews WHERE run_id = ? ORDER BY at, rowid", (run_id,))


def latest_reviews(run_id: str) -> dict[str, dict[str, Any]]:
    return {r["claim_id"]: r for r in reviews(run_id)}


def pending_reviews(run_id: str) -> list[str]:
    """Claims the agent marked Needs review that no reviewer has decided yet."""
    done = latest_reviews(run_id)
    return [
        cid for cid, v in verdicts(run_id).items() if v.label == "Needs review" and cid not in done
    ]


def run_provenance(run: dict[str, Any]) -> dict[str, Any] | None:
    raw = run.get("provenance_json")
    return json.loads(raw) if raw else None


def _fingerprint(run_id: str, run: dict[str, Any], approved_by: str, approved_at: str) -> str:
    _, head = provenance.chain_ok(_review_rows(run_id))
    return provenance.fingerprint(
        run_provenance(run),
        [v.model_dump(mode="json") for v in verdicts(run_id).values()],
        head,
        approved_by,
        approved_at,
    )


def approve(run_id: str, name: str) -> dict[str, Any] | None:
    run = get_run(run_id)
    if not run:
        return None
    at = datetime.now(UTC).isoformat()
    digest = _fingerprint(run_id, run, name.strip(), at)
    db.execute(
        "UPDATE runs SET approved_by = ?, approved_at = ?, approval_hash = ? WHERE id = ?",
        (name.strip(), at, digest, run_id),
    )
    return get_run(run_id)


def audit(run_id: str) -> dict[str, Any]:
    """Whether the review chain and the signed fingerprint still match what is stored."""
    run = get_run(run_id) or {}
    rows = _review_rows(run_id)
    chained = [r for r in rows if r.get("hash")]
    intact, head = provenance.chain_ok(chained)
    out: dict[str, Any] = {
        "provenance": run_provenance(run),
        "reviews": len(rows),
        "reviews_chained": len(chained) == len(rows),
        "reviews_intact": intact and len(chained) == len(rows),
        "review_head": head[:16] if rows else None,
        "fingerprint": run.get("approval_hash"),
        "fingerprint_matches": None,
    }
    if run.get("approved_by") and run.get("approval_hash"):
        now = _fingerprint(run_id, run, run["approved_by"], run["approved_at"])
        out["fingerprint_matches"] = now == run["approval_hash"]
    return out


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    """The run row without internal columns."""
    keep = (
        "id", "listing_id", "mode", "llm_mode", "started_at", "finished_at", "llm_calls",
        "tokens_in", "tokens_out", "est_cost_inr", "approved_by", "approved_at", "status",
    )  # fmt: skip
    return {k: run.get(k) for k in keep}
