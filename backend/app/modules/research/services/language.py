"""
Decide whether a source is in English.

Most providers expose a language code; when they don't (Semantic Scholar), we
fall back to a conservative heuristic. We only ever *drop* a record when we are
confident it is not English — unknown stays in, so good papers are never lost.
"""

from __future__ import annotations

import re

from ..models import SourceRecord

_ENGLISH_CODES = {"en", "eng", "english"}

# Words that are essentially never standalone English tokens. One hit is enough.
_STRONG_MARKERS = {
    # Indonesian / Malay
    "yang", "untuk", "dengan", "adalah", "tidak", "pada", "dan", "tersebut",
    "pengembangan", "pembelajaran", "penelitian", "aplikasi", "merupakan",
    "terhadap", "bahwa", "sehingga", "kepada", "beberapa", "variabel",
    # German
    "und", "für", "über", "eine", "einer", "eines", "nicht", "sowie", "durch",
    # French
    "dans", "pour", "avec", "cette", "nous", "sont", "être", "leurs",
    # Spanish / Portuguese
    "los", "las", "una", "para", "cómo", "hacia", "según", "también",
    # Italian
    "gli", "della", "delle", "degli", "nella", "sono", "anche",
    # Tagalog
    "mga", "ang", "ng", "isang", "para", "ayon",
}

# Ambiguous words — only suspicious when several appear together.
_WEAK_MARKERS = {
    "de", "la", "le", "les", "des", "du", "et", "el", "en", "que", "di", "da",
    "e", "i", "per", "con", "il", "lo", "che", "na", "sa", "ay", "no",
}

_SCRIPT_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af"
    r"\u0400-\u04ff\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f\u0590-\u05ff]"
)
_TOKEN_RE = re.compile(r"[a-zà-ÿ]+")


def is_english(record: SourceRecord) -> bool | None:
    """True (English), False (confidently not), or None (unknown)."""
    code = (record.language or "").strip().lower()
    if code:
        primary = re.split(r"[-_(]", code)[0].strip()
        return primary in _ENGLISH_CODES

    text = f"{record.title} {record.abstract[:400]}"
    if _SCRIPT_RE.search(text):
        return False

    tokens = set(_TOKEN_RE.findall(text.lower()))
    if tokens & _STRONG_MARKERS:
        return False
    if len(tokens & _WEAK_MARKERS) >= 3:
        return False
    return None
