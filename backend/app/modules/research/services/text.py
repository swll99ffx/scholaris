"""Text normalisation helpers shared by every source adapter."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_ARTICLE_PREFIX_RE = re.compile(r"^(?:article|e-?location|elocation)\s*[:#]?\s*", re.IGNORECASE)
_ARTICLE_VALUE_RE = re.compile(r"^e\d{3,}$|^[A-Za-z]{1,3}\d{3,}$|^0\d{2,}$", re.IGNORECASE)
_PAGE_RANGE_RE = re.compile(r"\d\s*[-–—]\s*\d")
_PAGE_RANGE_FULL_RE = re.compile(r"^(\d+)\s*[-–—]\s*(\d+)$")
_VOLUME_ISSUE_RE = re.compile(r"^(\d+)\s+(\d+)$")
_SPACE_BEFORE_COLON_RE = re.compile(r"\s+:")
_JOURNAL_ABBR_RE = re.compile(r"\s*:\s*[A-Z]{2,8}\.?\s*$")
_JOURNAL_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "nor",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "via",
    "versus",
    "vs",
    "with",
}


def clean_text(value: str | None, *, limit: int | None = None) -> str:
    """Remove HTML/JATS tags, decode entities and collapse whitespace."""
    if not value:
        return ""
    text = html.unescape(value)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    text = _SPACE_BEFORE_COLON_RE.sub(":", text)
    if limit is not None and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = _DOI_PREFIX_RE.sub("", value.strip()).strip().lower()
    return doi or None


def normalize_title(value: str | None) -> str:
    """Fingerprint used for de-duplicating the same paper across providers."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    # Drop leading articles so "The role of..." and "Role of..." match.
    text = re.sub(r"^(a|an|the)\s+", "", text)
    return _WS_RE.sub(" ", text).strip()


def fingerprint(value: str | None) -> str:
    return normalize_title(value)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2100 else None
    match = re.search(r"(1[5-9]\d{2}|20\d{2}|21\d{2})", str(value))
    return int(match.group(1)) if match else None


def clean_article_number(value: str | None) -> str | None:
    if not value:
        return None
    number = clean_text(value)
    number = _ARTICLE_PREFIX_RE.sub("", number).strip(" .,;:")
    return number or None


def expand_page_range(value: str | None) -> str | None:
    """
    Expand PubMed-style abbreviated ranges: ``8571-6`` becomes ``8571-8576``.

    PubMed's ``MedlinePgn`` and Semantic Scholar shorten the last page to the
    digits that differ from the first page. Only expand when the result is a
    valid forward range; otherwise leave the value untouched.
    """
    text = clean_text(value)
    if not text:
        return None
    match = _PAGE_RANGE_FULL_RE.fullmatch(text)
    if not match:
        return text
    start, end = match.groups()
    if len(end) >= len(start):
        return f"{start}-{end}"
    candidate = start[: len(start) - len(end)] + end
    try:
        if int(candidate) <= int(start):
            return f"{start}-{end}"
    except ValueError:
        return f"{start}-{end}"
    return f"{start}-{candidate}"


def split_volume_issue(value: str | None) -> tuple[str | None, str | None]:
    """Split Semantic Scholar's combined ``"15 20"`` volume/issue field."""
    text = clean_text(value)
    if not text:
        return None, None
    match = _VOLUME_ISSUE_RE.fullmatch(text)
    if match:
        return match.group(1), match.group(2)
    return text, None


def normalize_journal_name(value: str | None) -> str | None:
    """
    Clean a provider-supplied journal title for display and citation.

    PubMed and Semantic Scholar sometimes append the NLM abbreviation to the
    full title (``"Phytotherapy research : PTR"``). Strip that suffix, then
    apply conservative title case so the journal reads as a proper name
    (``"Phytotherapy Research"``). Acronyms and deliberate mixed-case names
    such as ``PLoS ONE`` or ``eLife`` are left alone.
    """
    text = clean_text(value)
    if not text:
        return None
    text = _JOURNAL_ABBR_RE.sub("", text).strip()
    if not text:
        return None
    words = text.split(" ")
    return " ".join(_title_case_word(word, index == 0) for index, word in enumerate(words))


def _title_case_word(word: str, first: bool) -> str:
    core = word.strip("()[]{}\"'.,;:")
    if not core:
        return word
    # Preserve deliberate mixed case: eLife, PLoS, McDonald, U.S.A.
    if len(core) > 1 and any(character.isupper() for character in core[1:]):
        return word
    if core.isupper() and len(core) > 1:
        return word
    if not first and core.lower() in _JOURNAL_SMALL_WORDS:
        return word.replace(core, core.lower(), 1)
    if core[0].isalpha():
        return word.replace(core, core[0].upper() + core[1:], 1)
    return word


def split_page_metadata(
    pages: str | None,
    article_number: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Separate a page range from an article/e-location number.

    Providers are inconsistent: some put "e12345" in `page`, some expose an
    explicit article number, and some use a single page. Only values that look
    like an article/e-location number are moved; a short single page such as
    "42" stays a page.
    """
    page_text = clean_text(pages) or None
    if page_text:
        page_text = expand_page_range(page_text)
    number = clean_article_number(article_number)

    if number:
        # Some records expose both fields with the article number repeated in
        # \"page\". Keep a real page range, but do not treat the duplicate as one.
        if page_text and not _PAGE_RANGE_RE.search(page_text):
            page_candidate = clean_article_number(page_text)
            if page_candidate and page_candidate.lower() == number.lower():
                page_text = None
        return page_text, number
    if not page_text:
        return None, None

    # Some providers put the full label in the page field.
    if _ARTICLE_PREFIX_RE.match(page_text):
        return None, clean_article_number(page_text)

    if not _PAGE_RANGE_RE.search(page_text):
        candidate = clean_article_number(page_text)
        if candidate and _ARTICLE_VALUE_RE.fullmatch(candidate):
            return None, candidate

    return page_text, None


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """OpenAlex stores abstracts as word -> positions. Rebuild the sentence."""
    if not inverted_index:
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for position in positions or []:
            positioned.append((int(position), word))
    positioned.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned)


def unique_sorted(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
