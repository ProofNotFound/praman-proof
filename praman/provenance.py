"""What a run was checked with, and fingerprints that show a signed report wasn't changed later.

Each run stores the rulebook version, a hash of the prompt files, the models, the CPCB list date
and the code version, so a report from last week says which rules it applied. Reviews form a hash
chain (each one hashes the one before), and the sign-off stores a fingerprint of the verdicts, the
review chain and the signer. Editing any of them afterwards no longer matches. Tamper-evident, not
tamper-proof: someone with the database could recompute, but not match a report already exported.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from typing import Any

from praman import __version__
from praman.config import CPCB_LIST_DATE, ROOT, RULES_PATH, get_settings

PROMPTS_DIR = ROOT / "praman" / "prompts"
GENESIS = "0" * 64


def sha256(obj: Any) -> str:
    """Hash of a value's canonical JSON (sorted keys, no spaces)."""
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


@lru_cache(maxsize=1)
def prompts_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(PROMPTS_DIR.glob("*.md")):
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:12]


@lru_cache(maxsize=1)
def commit() -> str:
    """The code's git commit: the host's variable when deployed, else .git in this folder."""
    for var in ("PRAMAN_COMMIT", "RENDER_GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA"):
        if os.environ.get(var):
            return os.environ[var][:12]
    try:
        head = (ROOT / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = head[5:]
            path = ROOT / ".git" / ref
            if path.exists():
                return path.read_text().strip()[:12]
            packed = (ROOT / ".git" / "packed-refs").read_text()
            for line in packed.splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0][:12]
            return ""
        return head[:12]
    except OSError:
        return ""


def snapshot() -> dict[str, Any]:
    """The run's provenance, stored with it."""
    s = get_settings()
    rules = json.loads(RULES_PATH.read_text())
    return {
        "praman": __version__,
        "commit": commit(),
        "rules_version": rules.get("version"),
        "rules_as_of": rules.get("as_of"),
        "prompts": prompts_hash(),
        "model": s.praman_model,
        "live_model": s.praman_live_model or None,
        "fallback_model": s.praman_fallback_model or None,
        "llm_mode": s.praman_llm_mode,
        "cpcb_list_date": CPCB_LIST_DATE,
    }


def review_hash(prev: str, row: dict[str, Any]) -> str:
    keys = ("run_id", "claim_id", "decision", "label", "ai_label", "reason", "reviewer", "at")
    return sha256({"prev": prev, **{k: row.get(k) for k in keys}})


def chain_ok(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    """(every review links to the one before and matches its own hash, the last hash)."""
    prev = GENESIS
    for r in rows:
        if not r.get("hash"):
            return False, prev
        if r.get("prev_hash") != prev or review_hash(prev, r) != r["hash"]:
            return False, prev
        prev = r["hash"]
    return True, prev


def fingerprint(
    provenance: dict[str, Any] | None,
    verdicts: list[dict[str, Any]],
    review_head: str,
    approved_by: str,
    approved_at: str,
) -> str:
    """The signed report's fingerprint: what was checked with, every verdict with its cited
    evidence and rules, the review chain, and who signed when."""
    rows = sorted(
        (
            {
                "claim_id": v["claim_id"],
                "label": v["label"],
                "evidence_ids": v.get("evidence_ids", []),
                "rule_ids": v.get("rule_ids", []),
                "reason": v.get("reason", ""),
            }
            for v in verdicts
        ),
        key=lambda r: r["claim_id"],
    )
    return sha256(
        {
            "provenance": provenance or {},
            "verdicts": rows,
            "reviews": review_head,
            "approved_by": approved_by,
            "approved_at": approved_at,
        }
    )


def line(p: dict[str, Any] | None) -> str:
    """One plain line for reports: what this run was checked with."""
    if not p:
        return "Checked with: not recorded (this run predates provenance records)."
    model = p.get("live_model") if p.get("llm_mode") == "live" and p.get("live_model") else None
    parts = [
        f"rulebook {p.get('rules_version')} ({p.get('rules_as_of')})",
        f"prompts {p.get('prompts')}",
        f"model {model or p.get('model')}",
        f"CPCB list {p.get('cpcb_list_date')}",
        f"Praman {p.get('praman')}" + (f" @ {p['commit']}" if p.get("commit") else ""),
    ]
    return "Checked with: " + " · ".join(parts) + "."
