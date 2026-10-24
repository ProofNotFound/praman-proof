"""CPCB certified compostable makers list (PDF) → data/cpcb_certified.csv.

Usage: uv run scripts/build_cpcb_csv.py [--pdf path/to/local.pdf]
Table 1 is the certified list; Table 2 lists units without a certificate. List date: 26 Oct 2023.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber  # noqa: E402

from praman.config import CACHE_DIR, CPCB_LIST_DATE, CPCB_PATH, RULES_PATH  # noqa: E402
from praman.tools.cpcb import normalise_name  # noqa: E402
from praman.tools.fetch import FetchError, PoliteClient  # noqa: E402

PDF_PATH = CACHE_DIR / "cpcb" / "certified_manufacturers_sellers.pdf"
COLUMNS = [
    "s_no",
    "name",
    "type",
    "office_address",
    "plant_address",
    "validity",
    "certificate",
    "conditions",
    "state",
    "table",
    "name_norm",
    "list_date",
    "source",
]

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Orissa", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Tamilnadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal", "Delhi", "Jammu", "Kashmir", "Puducherry", "Pondicherry",
    "Chandigarh", "Daman", "Dadra",
]  # fmt: skip


def clean(cell: str | None) -> str:
    return re.sub(r"\s+", " ", (cell or "").replace("\n", " ")).strip()


STATE_ALIASES = {
    "Orissa": "Odisha", "Tamilnadu": "Tamil Nadu", "Pondicherry": "Puducherry", "MP": "Madhya Pradesh",
    "Daman": "Dadra and Nagar Haveli and Daman and Diu",
    "Dadra": "Dadra and Nagar Haveli and Daman and Diu",
    "Jammu": "Jammu and Kashmir", "Kashmir": "Jammu and Kashmir",
    "Andaman": "Andaman and Nicobar Islands",
}  # fmt: skip


def find_state(*texts: str) -> str:
    """The last state name written in the first text that has one (word edges, so "Andaman"
    isn't "Daman")."""
    for text in texts:
        best = None
        for st in [*STATES, "Andaman", "MP"]:
            flags = 0 if st == "MP" else re.I
            for m in re.finditer(r"(?<![A-Za-z])" + re.escape(st) + r"(?![A-Za-z])", text, flags):
                if best is None or m.start() > best[0]:
                    best = (m.start(), st)
        if best:
            return STATE_ALIASES.get(best[1], best[1])
    return ""


def download(url: str) -> None:
    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(timeout_s=60)
    try:
        r = client.get(url)
    finally:
        client.close()
    PDF_PATH.write_bytes(r.content)


# First two digits of an Indian PIN code → state (fallback when no state name is written)
PIN_STATES = {
    **dict.fromkeys(["11"], "Delhi"), **dict.fromkeys(["12", "13"], "Haryana"),
    **dict.fromkeys(["14", "15", "16"], "Punjab"), "17": "Himachal Pradesh",
    **dict.fromkeys(["20", "21", "22", "23", "27", "28"], "Uttar Pradesh"),
    **dict.fromkeys(["30", "31", "32", "33", "34"], "Rajasthan"),
    **dict.fromkeys(["36", "37", "38", "39"], "Gujarat"),
    **dict.fromkeys(["40", "41", "42", "43", "44"], "Maharashtra"),
    **dict.fromkeys(["45", "46", "47", "48"], "Madhya Pradesh"), "49": "Chhattisgarh",
    "50": "Telangana", **dict.fromkeys(["51", "52", "53"], "Andhra Pradesh"),
    **dict.fromkeys(["56", "57", "58", "59"], "Karnataka"),
    **dict.fromkeys(["60", "61", "62", "63", "64"], "Tamil Nadu"),
    **dict.fromkeys(["67", "68", "69"], "Kerala"),
    **dict.fromkeys(["70", "71", "72", "73", "74"], "West Bengal"),
    **dict.fromkeys(["75", "76", "77"], "Odisha"), "78": "Assam",
    **dict.fromkeys(["80", "81", "84", "85"], "Bihar"), **dict.fromkeys(["82", "83"], "Jharkhand"),
}  # fmt: skip


def state_from_pin(*texts: str) -> str:
    for text in texts:
        pins = re.findall(r"(?<!\d)(\d{3})\s?(\d{3})(?!\d)", text)
        for a, b in reversed(pins):
            if (a + b)[:3] in ("244", "246", "247", "248", "249", "262", "263"):
                return "Uttarakhand"
            st = PIN_STATES.get(a[:2])
            if st:
                return st
    return ""


def join_lines(cell: str | None, narrow: bool = False) -> str:
    """Join a PDF cell's lines with spaces, except where a word was broken across lines
    ("Maharashtr\\na"): a short lowercase fragment (≤ 3 letters in narrow columns, ≤ 2 in the
    wide Details column) is glued to the previous word."""
    lines = [ln.strip() for ln in (cell or "").splitlines() if ln.strip()]
    out = ""
    limit = 3 if narrow else 2
    for ln in lines:
        frag = re.match(r"[a-z]+", ln)
        if (
            out
            and out[-1].isalpha()
            and frag
            and len(frag.group(0)) <= limit
            and (len(ln) == len(frag.group(0)) or not ln[len(frag.group(0))].isalpha())
        ):
            out += ln
        elif out and out[-1].isdigit() and ln[0].isdigit() and len(ln) <= 2:
            out += ln  # "05.03.202\n4"
        else:
            out = f"{out} {ln}" if out else ln
    return re.sub(r"\s+", " ", out).strip()


LABEL_RE = re.compile(
    r"(Office\s*Address|Plants?\s*Address(?:es)?|Factory\s*Address|Unit\s*Address|Address"
    r"|Contac?t?\s*Details?|Contact|Mobile|Phone|Tel\.?|Fax\s*No|Fax|E-?mail|Website)\s*[:\-–]?",
    re.I,
)
TYPE_RE = re.compile(
    r"\(?\s*((?:Brand\s*Owner|Manufacturer|Seller|Producer|Importer)[^)\n]*)\)", re.I
)
# Contact data never leaves the PDF (phones, emails, websites)
PRIVATE_RE = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*|\b(?:\+?91[-\s]?)?\d[\d\s-]{7,}\d\b|www\.\S+|https?://\S+", re.I
)


def scrub(text: str) -> str:
    return re.sub(r"\s+", " ", PRIVATE_RE.sub("", text)).strip(" ,;:-–")


def parse_details(details: str) -> dict:
    """Split a Details cell into name, type, office and plant address; drop contact data."""
    text = join_lines(details)
    parts: list[tuple[str, str]] = []
    pos, label = 0, "head"
    for m in LABEL_RE.finditer(text):
        parts.append((label, text[pos : m.start()]))
        label, pos = m.group(1).lower(), m.end()
    parts.append((label, text[pos:]))
    head = parts[0][1]
    kind = ""
    tm = TYPE_RE.search(head)
    if tm:
        kind = re.sub(r"\s+", " ", tm.group(1)).strip().title()
        head = head[: tm.start()]
    else:
        tm2 = re.search(r"\b(Manufacturer|Seller|Brand Owner)\b", head, re.I)
        if tm2:
            kind = tm2.group(1).title()
            head = head[: tm2.start()]
    name = re.sub(r"^\s*M\s*/\s*s\.?\s*", "", head, flags=re.I).strip(" ,.()-–")
    office, plant = [], []
    for lab, val in parts[1:]:
        if lab.startswith(
            ("contac", "contact", "mobile", "phone", "tel", "fax", "e-mail", "email", "website")
        ):
            continue
        val = scrub(val)
        if not val:
            continue
        (plant if lab.startswith(("plant", "factory", "unit")) else office).append(val)
    return {
        "name": scrub(name),
        "type": kind,
        "office_address": "; ".join(office),
        "plant_address": "; ".join(plant),
    }


def extract(pdf_path: Path) -> list[dict]:
    """Table 1 (6 columns: S.No, Details, Validity, Certificate, Conditions, State) runs until the
    page headed "Table:2"; Table 2 has 2 columns (S.No, Details). A row with an empty S.No continues
    the previous row on a new page."""
    raw_rows: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for cells in table:
                    cells = [c or "" for c in cells]
                    # Table 1 has 6 columns, Table 2 only S.No and Details
                    table_no = 1 if len(cells) >= 5 else 2
                    first = clean(cells[0]).rstrip(".")
                    if first.lower().replace(" ", "").startswith("s.no") or not any(
                        c.strip() for c in cells
                    ):
                        continue
                    if first.isdigit():
                        raw_rows.append({"s_no": int(first), "table": table_no, "cells": cells[1:]})
                    elif raw_rows and raw_rows[-1]["table"] == table_no:
                        prev = raw_rows[-1]["cells"]
                        for i, c in enumerate(cells[1:]):
                            if i < len(prev) and c.strip():
                                prev[i] = f"{prev[i]}\n{c}" if prev[i].strip() else c
    rows = []
    for r in raw_rows:
        cells = r["cells"] + [""] * 5
        d = parse_details(cells[0])
        t1 = r["table"] == 1
        written = join_lines(cells[4], narrow=True) if t1 else ""
        state = (
            find_state(written)
            or find_state(d["plant_address"], d["office_address"])
            or state_from_pin(d["plant_address"], d["office_address"])
            or written
        )
        rows.append(
            {
                "s_no": r["s_no"],
                **d,
                "validity": join_lines(cells[1], narrow=True) if t1 else "",
                "certificate": join_lines(cells[2], narrow=True) if t1 else "",
                "conditions": scrub(join_lines(cells[3], narrow=True)) if t1 else "",
                "state": state,
                "table": r["table"],
                "name_norm": normalise_name(d["name"]),
                "list_date": CPCB_LIST_DATE,
                "source": "pdf",
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="Use a local copy of the PDF instead of downloading")
    ap.add_argument("--dump", action="store_true", help="Print the raw tables of page 1 and stop")
    args = ap.parse_args()
    pdf_path = Path(args.pdf) if args.pdf else PDF_PATH
    if not pdf_path.exists():
        url = json.loads(RULES_PATH.read_text())["sources"]["CPCB_LIST"]["official_url"]
        print(f"Downloading {url}")
        try:
            download(url)
        except FetchError as e:
            print(
                f"{e}\nDownload the PDF by hand in a browser and save it as {PDF_PATH}, "
                "or pass --pdf <path>."
            )
            return 2
    if args.dump:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"{len(pdf.pages)} pages")
            for t in pdf.pages[0].extract_tables():
                for row in t[:6]:
                    print(row)
        return 0
    rows = extract(pdf_path)
    with CPCB_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    t1 = sum(1 for r in rows if r["table"] == 1)
    t2 = len(rows) - t1
    print(f"Wrote {CPCB_PATH}: {t1} certified rows (Table 1), {t2} rows in Table 2")
    for needle, sno in (("greendotbiopak", 32), ("sunshield biotech", 2)):
        hits = [
            r for r in rows if needle in r["name_norm"].replace(" ", "") or needle in r["name_norm"]
        ]
        ok = any(r["s_no"] == sno and r["table"] == 1 for r in hits)
        print(
            f"  spot-check {needle!r} S.No. {sno}: {'OK' if ok else 'NOT FOUND'} {[(r['s_no'], r['name'], r['state']) for r in hits]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
