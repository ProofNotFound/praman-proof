"""cpcb_lookup (TRD §7.2): fuzzy match a maker name or CPCB code against the certified list."""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from rapidfuzz import fuzz

from praman.config import CPCB_LIST_DATE, CPCB_PATH

CODE_RE = re.compile(r"CPCB[-\s]*UPC[-\s]*[IV]+\s*/\s*([^/]+?)\s*/\s*([^/]+?)\s*/\s*(\d+)", re.I)


def normalise_name(name: str) -> str:
    s = name.lower()
    s = s.replace("m/s.", " ").replace("m/s", " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split()
    drop = {"pvt", "ltd", "private", "limited", "llp", "ms"}
    words = [w for w in words if w not in drop]
    return " ".join(words)


class CpcbRow(BaseModel):
    s_no: int
    name: str
    type: str
    state: str
    validity: str
    certificate: str = ""
    table: int
    office_address: str = ""
    plant_address: str = ""


class CpcbResult(BaseModel):
    query: str
    name_queried: str
    state_queried: str | None
    rows_scanned: int  # rows on the certified list (Table 1)
    rows_uncertified: int = 0  # Table 2 rows, also checked
    list_date: str
    match: CpcbRow | None
    score: float
    code: str | None = None


@lru_cache(maxsize=4)
def load_rows(path: Path = CPCB_PATH) -> tuple[dict, ...]:
    if not path.exists():
        return ()
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["s_no"] = int(r["s_no"])
        r["table"] = int(r["table"])
    return tuple(rows)


def _state_in(query: str) -> str | None:
    low = query.lower()
    for st in _STATES:
        if st.lower() in low:
            return st
    return None


_STATES = [
    "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra",
    "Odisha", "Punjab", "Rajasthan", "Tamil Nadu", "Telangana", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Puducherry",
]  # fmt: skip


def certified_count(path: Path = CPCB_PATH) -> int:
    return sum(1 for r in load_rows(path) if r["table"] == 1)


def split_query(query: str) -> tuple[str, str | None, str | None]:
    """Split a CPCB code or 'Name, City, State' into (name, state, code)."""
    m = CODE_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(0).strip()
    name = query.split(",")[0].strip()
    return name, _state_in(query), None


def score_names(a: str, b: str) -> float:
    """Best of token-set similarity and space-insensitive similarity ("Green Dot" vs "Greendot")."""
    if not a or not b:
        return 0.0
    return max(
        fuzz.token_set_ratio(a, b),
        fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")),
    )


def cpcb_lookup(query: str, path: Path = CPCB_PATH) -> CpcbResult:
    name, state, code = split_query(query)
    norm = normalise_name(name)
    rows = load_rows(path)
    best: tuple[float, dict] | None = None
    for r in rows:
        s = score_names(norm, r["name_norm"])
        if best is None or s > best[0] or (s == best[0] and r["table"] < best[1]["table"]):
            best = (s, r)
    match = None
    score = 0.0
    if best:
        score, r = best
        state_ok = bool(state) and state.lower() in (r["state"] or "").lower()
        if score >= 90 or (score >= 80 and state_ok):
            match = CpcbRow(
                s_no=r["s_no"],
                name=r["name"],
                type=r["type"],
                state=r["state"],
                validity=r["validity"],
                certificate=r.get("certificate", ""),
                table=r["table"],
                office_address=r["office_address"],
                plant_address=r["plant_address"],
            )
    return CpcbResult(
        query=query,
        name_queried=name,
        state_queried=state,
        rows_scanned=sum(1 for r in rows if r["table"] == 1),
        rows_uncertified=sum(1 for r in rows if r["table"] == 2),
        list_date=CPCB_LIST_DATE,
        match=match,
        score=round(float(score), 1),
        code=code,
    )


def find_codes(text: str) -> list[str]:
    """Every CPCB registration code printed in some text, exact, in order."""
    out: list[str] = []
    for m in CODE_RE.finditer(text):
        code = m.group(0).strip()
        if code not in out:
            out.append(code)
    return out
