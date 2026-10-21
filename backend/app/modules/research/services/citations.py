"""
APA 7, MLA 9 and Chicago 17 citation formatting.

Citations consume structured author names whenever a provider supplied them.
Flat names are parsed by ``authors.py`` only as a fallback, and a suspicious
parse or a cross-provider disagreement is surfaced with a copyable
``[NEEDS CHECKING: author names]`` prefix rather than silently guessing.
"""

from __future__ import annotations

import re

from ..models import SourceRecord
from .authors import (
    AuthorCheck,
    AuthorName,
    ensure_author_check,
    ensure_author_details,
    initials,
    parse_flat_name,
)
from .text import clean_text, expand_page_range, normalize_journal_name


def split_name(name: str) -> tuple[str, str]:
    """Split a flat display name into (family, given) as best we can."""
    detail = parse_flat_name(name)
    if detail.literal:
        return detail.literal, ""
    return detail.family, detail.given


def _apa_author(author: AuthorName) -> str:
    if author.literal:
        return clean_text(author.literal)
    family = clean_text(author.family)
    if not family:
        return clean_text(author.given) or clean_text(author.literal)
    given = initials(author.given)
    base = f"{family}, {given}".rstrip(", ") if given else family
    if author.suffix:
        base += f", {author.suffix}"
    return base


def _apa_authors(authors: list[AuthorName]) -> str:
    formatted = [_apa_author(author) for author in authors]
    formatted = [name for name in formatted if name]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    return ", ".join(formatted[:19]) + ", ... " + formatted[-1]


def _given_first(author: AuthorName) -> str:
    if author.literal:
        return clean_text(author.literal)
    family = clean_text(author.family)
    given = clean_text(author.given)
    if not family:
        return given
    base = f"{given} {family}".strip() if given else family
    if author.suffix:
        base = f"{base} {author.suffix}"
    return base


def _family_first(author: AuthorName) -> str:
    if author.literal:
        return clean_text(author.literal)
    family = clean_text(author.family)
    given = clean_text(author.given)
    if not family:
        return given
    base = f"{family}, {given}".rstrip(", ") if given else family
    if author.suffix:
        base += f", {author.suffix}"
    return base


def _mla_authors(authors: list[AuthorName]) -> str:
    usable = [author for author in authors if author.literal or author.family or author.given]
    if not usable:
        return ""
    first = _family_first(usable[0])
    if len(usable) == 1:
        return first
    if len(usable) == 2:
        return f"{first}, and {_given_first(usable[1])}".strip()
    return f"{first}, et al."


def _chicago_authors(authors: list[AuthorName]) -> str:
    usable = [author for author in authors if author.literal or author.family or author.given]
    if not usable:
        return ""
    first = _family_first(usable[0])
    if len(usable) == 1:
        return first
    if len(usable) == 2:
        return f"{first}, and {_given_first(usable[1])}".strip()
    if len(usable) == 3:
        return (
            f"{first}, {_given_first(usable[1])}, and {_given_first(usable[2])}".strip()
        )
    return f"{first}, et al."


def _title(text: str | None) -> str:
    cleaned = clean_text(text).rstrip(".")
    return re.sub(r"\s+:", ":", cleaned)


def _year(record: SourceRecord) -> str:
    return str(record.year) if record.year else "n.d."


def _period(text: str) -> str:
    """Append a period only when the text doesn't already end with one."""
    return text if text.endswith(".") else f"{text}."


def _link(record: SourceRecord) -> str:
    if record.doi:
        return f"https://doi.org/{record.doi}"
    return record.url or ""


def _pages(record: SourceRecord) -> str:
    raw = expand_page_range(record.pages)
    return raw.replace("--", "–").replace("-", "–") if raw else ""


def _article_number(record: SourceRecord) -> str:
    """APA 7: journal articles without a page range use 'Article [number]'."""
    raw = clean_text(record.article_number)
    if not raw:
        return ""
    if raw.lower().startswith("article "):
        return raw
    return f"Article {raw}"


def _prefix(check: AuthorCheck) -> str:
    return "[NEEDS CHECKING: author names] " if check.status == "needs_checking" else ""


def _apa_body(record: SourceRecord, authors: list[AuthorName]) -> str:
    author_text = _apa_authors(authors)
    title = _title(record.title)
    year = _year(record)

    pieces: list[str] = []
    pieces.append(f"{_period(author_text)} " if author_text else "")
    pieces.append(f"({year}). ")
    pieces.append(f"{_period(title)} " if title else "")

    if record.journal:
        journal = normalize_journal_name(record.journal) or ""
        if record.volume:
            journal += f", {record.volume}"
        if record.issue:
            journal += f"({record.issue})"
        if _pages(record):
            journal += f", {_pages(record)}"
        elif _article_number(record):
            journal += f", {_article_number(record)}"
        pieces.append(f"{journal}. ")

    link = _link(record)
    if link:
        pieces.append(link)

    return "".join(pieces).strip()


def _mla_body(record: SourceRecord, authors: list[AuthorName]) -> str:
    author_text = _mla_authors(authors)
    title = _title(record.title)
    year = _year(record)

    pieces: list[str] = []
    if author_text:
        pieces.append(f"{_period(author_text)} ")
    if title:
        pieces.append(f'"{title}." ')

    if record.journal:
        journal = normalize_journal_name(record.journal) or ""
        if record.volume:
            journal += f", vol. {record.volume}"
        if record.issue:
            journal += f", no. {record.issue}"
        if record.year:
            journal += f", {year}"
        if _pages(record):
            journal += f", pp. {_pages(record)}"
        pieces.append(f"{journal}. ")

    link = _link(record)
    if link:
        pieces.append(link)

    return "".join(pieces).strip()


def _chicago_body(record: SourceRecord, authors: list[AuthorName]) -> str:
    author_text = _chicago_authors(authors)
    title = _title(record.title)
    year = _year(record)

    pieces: list[str] = []
    if author_text:
        pieces.append(f"{_period(author_text)} ")
    if title:
        pieces.append(f'"{title}." ')

    if record.journal:
        journal = normalize_journal_name(record.journal) or ""
        if record.volume:
            journal += f" {record.volume}"
        if record.issue:
            journal += f", no. {record.issue}"
        journal += f" ({year})"
        if _pages(record):
            journal += f": {_pages(record)}"
        pieces.append(f"{journal}. ")

    link = _link(record)
    if link:
        pieces.append(link)

    return "".join(pieces).strip()


def format_apa(record: SourceRecord) -> str:
    authors = ensure_author_details(record)
    check = ensure_author_check(record)
    return _prefix(check) + _apa_body(record, authors)


def format_mla(record: SourceRecord) -> str:
    authors = ensure_author_details(record)
    check = ensure_author_check(record)
    return _prefix(check) + _mla_body(record, authors)


def format_chicago(record: SourceRecord) -> str:
    authors = ensure_author_details(record)
    check = ensure_author_check(record)
    return _prefix(check) + _chicago_body(record, authors)


def format_citations(record: SourceRecord) -> dict[str, str]:
    authors = ensure_author_details(record)
    check = ensure_author_check(record)
    prefix = _prefix(check)
    return {
        "apa": prefix + _apa_body(record, authors),
        "mla": prefix + _mla_body(record, authors),
        "chicago": prefix + _chicago_body(record, authors),
    }
