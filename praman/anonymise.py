"""Anonymise mode (FR-16, TRD §15.5): mask store domains, brands and aliases as "Brand A", "Brand B"…

The mapping comes from data/listings_seed.csv (brand, brand_aliases, store) and is stable:
letters follow the order in which brands first appear in the seed file.
"""

from __future__ import annotations

import csv
import io
import json
import re
import string
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter
from pydantic import BaseModel

from praman.config import CACHE_DIR, ROOT, SEED_PATH, get_settings
from praman.models import Listing


def letter_label(i: int) -> str:
    """0 → A … 25 → Z, 26 → AA, 27 → AB …"""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = string.ascii_uppercase[r] + out
    return out


@lru_cache(maxsize=1)
def _seed() -> tuple[list[tuple[str, list[str], str]], dict[str, str]]:
    """([(letter, brand names, store)], listing_id → letter) from data/listings_seed.csv. Letters
    follow the order in which brands first appear in the seed file."""
    rows = list(csv.DictReader(SEED_PATH.open()))
    letters: dict[str, str] = {}
    listing_brand: dict[str, str] = {}
    entities: list[tuple[str, list[str], str]] = []
    for r in rows:
        brand = r["brand"].strip()
        if brand not in letters:
            letters[brand] = letter_label(len(letters))
        letter = letters[brand]
        listing_brand[r["id"]] = letter
        names = [brand] + [a.strip() for a in r["brand_aliases"].split(";") if a.strip()]
        store = r["store"].strip().lower()
        names.append(store.split(".")[0])  # "letsbeco", "barenecessities", "peesafe"
        entities.append((letter, names, store))
    return entities, listing_brand


# ---------------------------------------------------------------------------
# Stores and brands outside the seed file get the next free letter, kept in SQLite (anon_names)
# so the same store keeps its letter across runs and processes.

_version = 0  # bumped when a name is registered, so the masking table is rebuilt
# Words that must never be masked even if a store or vendor is called that ("green.in")
GENERIC_NAMES = {
    "shop",
    "store",
    "default",
    "india",
    "online",
    "official",
    "products",
    "home",
    "the",
    "green",
    "eco",
    "earth",
    "natural",
    "nature",
    "organic",
    "pure",
    "bio",
    "zero",
    "waste",
    "plastic",
    "sustainable",
    "compostable",
    "biodegradable",
    "recyclable",
    "planet",
    "clean",
    "bamboo",
    "cotton",
    "jute",
    "wood",
    "paper",
    "steel",
    "glass",
    "coconut",
    "neem",
    "herbal",
    "vegan",
}


def _generic(name: str) -> bool:
    words = re.findall(r"[a-z]+", name.lower())
    return not words or len("".join(words)) < 3 or all(w in GENERIC_NAMES for w in words)


def _dynamic() -> list[dict[str, str]]:
    from praman import db

    try:
        return db.query("SELECT key, letter, kind FROM anon_names ORDER BY created_at, key")
    except Exception:  # noqa: BLE001 - no database yet: nothing registered
        return []


def register(store: str | None, names: list[str] | None = None) -> str | None:
    """The letter for a store (domain) and its brand names: the seed letter for a seed store, an
    existing letter if the store or a name was seen before, else the next free one."""
    global _version
    from praman import db
    from praman.tools.fetch import registered_domain

    domain = registered_domain(store) if store else ""
    stem = domain.split(".")[0] if domain else ""
    names = [n.strip() for n in (names or []) + [stem] if n and n.strip()]
    names = [n for n in dict.fromkeys(names) if not _generic(n)]
    seed_entities, _ = _seed()
    for letter, seed_names, seed_store in seed_entities:
        if domain and registered_domain(seed_store) == domain:
            return letter
        if any(n.lower() == s.lower() for n in names for s in seed_names):
            return letter
    keys = ([("domain", domain)] if domain else []) + [("brand", n.lower()) for n in names]
    if not keys:
        return None
    rows = {r["key"]: r for r in _dynamic()}
    letter = next((rows[k]["letter"] for _, k in keys if k in rows), None)
    if letter is None:
        used = {e[0] for e in seed_entities} | {r["letter"] for r in rows.values()}
        i = 0
        while letter_label(i) in used:
            i += 1
        letter = letter_label(i)
    from datetime import UTC, datetime

    added = False
    for kind, key in keys:
        if key not in rows:
            db.execute(
                "INSERT OR IGNORE INTO anon_names (key, letter, kind, created_at) VALUES (?, ?, ?, ?)",
                (key, letter, kind, datetime.now(UTC).isoformat()),
            )
            added = True
    if added:
        _version += 1
    return letter


def listing_brand_names(listing: Listing) -> list[str]:
    """The names to hide for a listing: its vendor, plus the short form titles use ("Plum Color
    Affair" for the vendor "Plum Goodness" at plumgoodness.com): a word of the vendor, or the
    title's first word, that begins the store's domain name."""
    from praman.tools.fetch import registered_domain

    stem = registered_domain(listing.store).split(".")[0].lower() if listing.store else ""
    names = [listing.vendor] if listing.vendor else []
    words = re.findall(r"[A-Za-z]+", listing.vendor) + re.findall(r"[A-Za-z]+", listing.title)[:1]
    for w in words:
        if len(w) >= 3 and w.lower() != stem and stem.startswith(w.lower()):
            names.append(w)
    return list(dict.fromkeys(names))


def register_listing(listing: Listing) -> str | None:
    """Give a listing's store and brand (vendor) a letter before anything about it is shown."""
    return register(listing.store, listing_brand_names(listing))


_table_cache: dict[tuple[str, int], tuple[list[tuple[re.Pattern[str], str]], dict[str, str]]] = {}


def _table() -> tuple[list[tuple[re.Pattern[str], str]], dict[str, str]]:
    """(patterns → replacement, listing_id → brand letter): seed brands plus registered ones."""
    key = (str(get_settings().db_path), _version)
    hit = _table_cache.get(key)
    if hit is not None:
        return hit
    seed_entities, listing_brand = _seed()
    terms: list[tuple[str, str, bool]] = []  # (term, replacement, is_domain)
    for letter, names, store in seed_entities:
        for n in names:
            terms.append((n, f"Brand {letter}", False))
        terms.append((store, f"brand-{letter.lower()}.example", True))
    for r in _dynamic():
        if r["kind"] == "domain":
            terms.append((r["key"], f"brand-{r['letter'].lower()}.example", True))
        else:
            terms.append((r["key"], f"Brand {r['letter']}", False))
    # Longest first so "Bare Necessities" wins over shorter overlaps
    terms.sort(key=lambda t: -len(t[0]))
    patterns: list[tuple[re.Pattern[str], str]] = []
    seen: set[str] = set()
    for term, rep, is_domain in terms:
        k = term.lower()
        if k in seen:
            continue
        seen.add(k)
        if is_domain:
            pat = re.compile(r"(?:www\.)?" + re.escape(term), re.I)
        else:
            parts = [re.escape(p) for p in re.split(r"\s+", term)]
            body = r"[\s_\-]*".join(parts)  # "Pee Safe", "PeeSafe", "pee_safe"
            # Trailing check is case-sensitive so CamelCase handles still match ("PeeSafeIndia")
            pat = re.compile(r"(?<![A-Za-z0-9])" + body + r"(?-i:(?![a-z]))", re.I)
        patterns.append((pat, rep))
    _table_cache.clear()
    _table_cache[key] = (patterns, listing_brand)
    return patterns, listing_brand


def enabled() -> bool:
    return get_settings().praman_anonymise


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<![\w/])(?:\+?91[\s-]?)?\d(?:[\s-]?\d){9,}(?![\w/])")


def mask_text(text: str) -> str:
    """Brands and stores become "Brand A", "brand-a.example"; emails and phone numbers are hidden."""
    if not text:
        return text
    text = EMAIL_RE.sub("[email hidden]", text)
    text = PHONE_RE.sub("[number hidden]", text)
    patterns, _ = _table()
    for pat, rep in patterns:
        text = pat.sub(rep, text)
    return text


def mask(obj: Any) -> Any:
    """Mask every string inside dicts and lists (keys are left alone)."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    if isinstance(obj, tuple):
        return [mask(v) for v in obj]
    return obj


def maybe_mask(obj: Any) -> Any:
    return mask(obj) if enabled() else obj


def has_brand(text: str) -> bool:
    return mask_text(text) != text


def brand_letter(listing_id: str) -> str | None:
    return _table()[1].get(listing_id)


MASKED_RE = re.compile(r"\bBrand [A-Z]\b|brand-[a-z]\.example|\[(?:email|number) hidden\]")
MASKS_DIR = CACHE_DIR / "masks"


class BrandMark(BaseModel):
    text: str
    box_2d: list[int] | None = None


class BrandMarksPhoto(BaseModel):
    photo: int
    marks: list[BrandMark]


class BrandMarksOut(BaseModel):
    photos: list[BrandMarksPhoto]


def brand_names(listing_id: str) -> list[str]:
    for r in csv.DictReader(SEED_PATH.open()):
        if r["id"] == listing_id:
            names = [r["brand"]] + [a.strip() for a in r["brand_aliases"].split(";") if a.strip()]
            return names + [r["store"], r["store"].split(".")[0]]
    return []


def find_brand_marks(listing: Listing, meter: Any = None) -> dict[int, list[dict]]:
    """Boxes of brand names and logos in every photo (one vision call, cached in
    data/cache/masks/<id>.json). Used only for masking photos, never as evidence."""
    path = MASKS_DIR / f"{listing.id}.json"
    if path.exists():
        return {int(k): v for k, v in json.loads(path.read_text()).items()}
    from praman import llm

    names = brand_names(listing.id)
    photos = [p for p in listing.photos if p.local_path]
    if not names or not photos:
        return {}
    res = llm.call(
        "find_brand_marks",
        BrandMarksOut,
        variables={"n_photos": len(photos), "names": "\n".join(f"- {n}" for n in names)},
        images=[llm.image_ref(listing.id, p.index, p.url, p.local_path) for p in photos],
        listing_id=listing.id,
        meter=meter,
    )
    out: dict[int, list[dict]] = {}
    for ph in res.data.photos:
        for m in ph.marks:
            if m.box_2d and len(m.box_2d) == 4:
                # Every mark is a brand mark, so tag it for mask_photo
                out.setdefault(ph.photo, []).append({"text": "Brand mark", "box_2d": m.box_2d})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return out


# Contact data printed on packs: emails, web addresses or bare domains, phone-like digit runs
CONTACT_RE = re.compile(
    r"@|https?://|www\.|\b[\w-]+\.(?:com|in|co|net|org|shop|store|io)\b|\d(?:[\s-]?\d){6,}",
    re.I,
)
OCR_MIN_SCORE = 0.5


_keys_cache: dict[tuple[str, int], tuple[str, ...]] = {}


def _brand_keys() -> tuple[str, ...]:
    """Every brand, alias and store stem (seed file and registered), lowercased, letters only."""
    ck = (str(get_settings().db_path), _version)
    if ck in _keys_cache:
        return _keys_cache[ck]
    keys: set[str] = set()
    names = [n for _, ns, _ in _seed()[0] for n in ns]
    names += [r["key"].split(".")[0] if r["kind"] == "domain" else r["key"] for r in _dynamic()]
    for n in names:
        k = re.sub(r"[^a-z]", "", n.lower())
        if len(k) >= 3:
            keys.add(k)
    _keys_cache.clear()
    _keys_cache[ck] = tuple(sorted(keys))
    return _keys_cache[ck]


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def names_brand(text: str, fuzzy: bool = False) -> bool:
    """A brand or alias appears in the text once both are lowercased and stripped to letters
    ("BareNecessitiesZeroWaste", "shop@beco.co.in"). `fuzzy` tolerates OCR misreads."""
    letters = _letters(text)
    if not letters:
        return False
    if any(k in letters for k in _brand_keys()):
        return True
    if fuzzy:
        from rapidfuzz import fuzz

        # partial_ratio aligns the shorter string inside the longer one, so a short fragment
        # ("t") would "match" any brand: the text must be about as long as the brand name
        return any(
            len(k) >= 6 and len(letters) >= len(k) - 2 and fuzz.partial_ratio(k, letters) >= 82
            for k in _brand_keys()
        )
    return False


def brand_item(text: str) -> bool:
    """A printed item to blur: a brand mark, contact data, or a brand or alias in any form."""
    return (
        text == "Brand mark"
        or bool(MASKED_RE.search(text))
        or bool(CONTACT_RE.search(text))
        or names_brand(text)
        or has_brand(text)
    )


def ocr_marks(listing: Listing) -> dict[int, list[dict]]:
    """Lines read by local OCR that hold contact data or a brand, per photo (cached in
    data/cache/masks/<id>.ocr.json). A safety net for small print the vision model skipped;
    no model call. Needs the dev dependency rapidocr-onnxruntime when the cache is cold."""
    path = MASKS_DIR / f"{listing.id}.ocr.json"
    if path.exists():
        return {int(k): v for k, v in json.loads(path.read_text()).items()}
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    out: dict[int, list[dict]] = {}
    for p in listing.photos:
        if not p.local_path:
            continue
        img = Image.open(ROOT / p.local_path).convert("RGB")
        w, h = img.size
        scale = 2 if max(w, h) < 1600 else 1  # small print on low-res photos needs upscaling
        if scale > 1:
            img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
        W, H = img.size
        # Upright, then turned both ways: pack ends often print the brand vertically
        views = [
            (img, lambda x, y: (x, y)),
            (img.transpose(Image.Transpose.ROTATE_90), lambda x, y, W=W: (W - y, x)),
            (img.transpose(Image.Transpose.ROTATE_270), lambda x, y, H=H: (y, H - x)),
        ]
        for view, back in views:
            buf = io.BytesIO()
            view.save(buf, "PNG")
            result, _ = engine(buf.getvalue())
            for quad, text, score in result or []:
                if float(score) < OCR_MIN_SCORE:
                    continue
                if not (CONTACT_RE.search(text) or names_brand(text, fuzzy=True)):
                    continue
                pts = [back(pt[0], pt[1]) for pt in quad]
                xs = [x / scale for x, _ in pts]
                ys = [y / scale for _, y in pts]
                box = [
                    int(min(ys) / h * 1000),
                    int(min(xs) / w * 1000),
                    int(max(ys) / h * 1000) + 1,
                    int(max(xs) / w * 1000) + 1,
                ]
                # Store why, not what: the file must not keep contact data
                why = "contact" if CONTACT_RE.search(text) else "brand"
                out.setdefault(p.index, []).append(
                    {"text": "Brand mark", "box_2d": box, "why": why}
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def masked_photo_bytes(
    listing: Listing, index: int, items: list[dict], max_edge: int | None = None
) -> bytes | None:
    """The photo with brand and contact text blurred: printed items that name a brand or hold
    contact data, plus the cached brand marks, OCR marks and reviewed manual marks."""
    photo = next((p for p in listing.photos if p.index == index), None)
    if not photo or not photo.local_path:
        return None
    marks: list[dict] = []
    # Model brand marks, local OCR marks, and boxes added by hand after a visual review
    for name in (f"{listing.id}.json", f"{listing.id}.ocr.json", f"{listing.id}.manual.json"):
        path = MASKS_DIR / name
        if path.exists():
            marks += json.loads(path.read_text()).get(str(index), [])
    return mask_photo(ROOT / photo.local_path, items + marks, max_edge)


def has_mask_files(listing_id: str) -> bool:
    """Whether reviewed or cached brand marks exist for this listing's photos."""
    return any(
        (MASKS_DIR / f"{listing_id}{ext}").exists()
        for ext in (".json", ".ocr.json", ".manual.json")
    )


def pending_photo_bytes(path: Path) -> bytes:
    """A small, heavily blurred copy, for a photo whose printed brand text isn't known yet: the
    brand must never show while it is still being read."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((320, 320))
    img = img.filter(ImageFilter.GaussianBlur(14))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def mask_photo(path: Path, items: list[dict], max_edge: int | None = None) -> bytes:
    """Blur every item that brand_item() flags: its box plus 6% padding, with a blur radius that
    grows with the box so large logo letters are unreadable too."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    for it in items:
        box = it.get("box_2d")
        if not box or not brand_item(it.get("text", "")):
            continue
        ymin, xmin, ymax, xmax = box
        pad_y, pad_x = 0.06 * (ymax - ymin) + 6, 0.06 * (xmax - xmin) + 6
        x0 = max(0, int((xmin - pad_x) / 1000 * w))
        y0 = max(0, int((ymin - pad_y) / 1000 * h))
        x1 = min(w, int((xmax + pad_x) / 1000 * w))
        y1 = min(h, int((ymax + pad_y) / 1000 * h))
        if x1 <= x0 or y1 <= y0:
            continue
        radius = max(12, int(min(x1 - x0, y1 - y0) * 0.3))
        region = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(radius))
        img.paste(region, (x0, y0))
    if max_edge and max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()
