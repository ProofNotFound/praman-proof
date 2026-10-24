"""Careful language (TRD §10.7): generated text never accuses a brand."""

from __future__ import annotations

import re

_REPLACEMENTS = [
    (r"\billegally\b", "outside the rules"),
    (r"\billegal\b", "not in line with the rules"),
    (r"\bviolations\b", "conflicts with the rules"),
    (r"\bviolation\b", "conflict with the rules"),
    (r"\bviolates\b", "conflicts with"),
    (r"\bviolated\b", "conflicted with"),
    (r"\bviolate\b", "conflict with"),
    (r"\bgreenwashing\b", "unsupported environmental claims"),
    (r"\bgreenwash(ed)?\b", "unsupported"),
    (r"\bfraudulent\b", "misleading"),
    (r"\bfraud\b", "a misleading claim"),
    (r"\blying\b", "inaccurate"),
]
BANNED = re.compile(
    r"\b(illegal|illegally|violations?|violates?|violated|greenwash(ing|ed)?|fraud(ulent)?|lying)\b",
    re.I,
)


def careful(text: str | None) -> str:
    """Rewrite banned words in model-written text into neutral wording."""
    if not text:
        return text or ""
    out = text
    for pat, rep in _REPLACEMENTS:
        out = re.sub(pat, rep, out, flags=re.I)
    return out


def has_banned(text: str) -> bool:
    return bool(BANNED.search(text or ""))
