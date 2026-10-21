"""
DOAJ adapter (Directory of Open Access Journals).

DOAJ only indexes vetted open-access journals, so every result is free to read
and comes from a journal that meets DOAJ's quality criteria. No key required.

Docs: https://doaj.org/api/docs
"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from app.config import Settings
from app.core.http import fetch
from app.core.rate_limit import RateLimiter

from ..models import SourceRecord
from ..schemas import SearchFilters
from .authors import AuthorName, display_authors, parse_flat_name, set_record_authors
from .text import (
    clean_text,
    normalize_doi,
    normalize_journal_name,
    parse_year,
    split_page_metadata,
    unique_sorted,
)

BASE_URL = "https://doaj.org/api/search/articles/"
limiter = RateLimiter(min_interval_seconds=0.3)

_REVIEW_TITLE_RE = re.compile(
    r"\b(systematic review|literature review|meta-analysis|scoping review|narrative review|review)\b",
    re.IGNORECASE,
)


async def search(
    client: httpx.AsyncClient,
    *,
    query: str,
    filters: SearchFilters,
    settings: Settings,
    limit: int,
) -> list[SourceRecord]:
    # DOAJ takes the query in the URL path (Elasticsearch query-string syntax).
    url = BASE_URL + quote(query, safe="")
    params = {"pageSize": str(max(1, min(limit, 100)))}

    data = await fetch(
        client,
        provider="DOAJ",
        url=url,
        params=params,
        limiter=limiter,
    )
    return [to_record(item) for item in data.get("results", []) if item.get("bibjson")]


def to_record(item: dict) -> SourceRecord:
    bib = item.get("bibjson") or {}
    journal = bib.get("journal") or {}

    author_details: list[AuthorName] = []
    for author in bib.get("author") or []:
        name = clean_text(author.get("name"))
        if not name:
            continue
        detail = parse_flat_name(name, source="doaj")
        orcid = clean_text(author.get("orcid_id") or author.get("orcid"))
        if orcid:
            detail.orcid = orcid
        author_details.append(detail)
    authors = display_authors(author_details)

    doi = None
    for identifier in bib.get("identifier") or []:
        if str(identifier.get("type", "")).lower() == "doi":
            doi = normalize_doi(identifier.get("id"))
            break

    url = f"https://doi.org/{doi}" if doi else None
    for link in bib.get("link") or []:
        link_type = str(link.get("type", "")).lower()
        if link.get("url") and link_type in {"fulltext", "homepage"}:
            url = link["url"]
            break
    if not url:
        for link in bib.get("link") or []:
            if link.get("url"):
                url = link["url"]
                break

    subjects: list[str] = []
    for subject in bib.get("subject") or []:
        term = subject.get("term") if isinstance(subject, dict) else subject
        if term:
            subjects.append(str(term))
    for keyword in bib.get("keywords") or []:
        if keyword:
            subjects.append(str(keyword))

    raw_language = journal.get("language") or bib.get("language")
    if isinstance(raw_language, list):
        language = str(raw_language[0]) if raw_language else None
    else:
        language = str(raw_language) if raw_language else None

    title = clean_text(bib.get("title"))
    is_review = bool(_REVIEW_TITLE_RE.search(title))
    start_page = clean_text(bib.get("start_page"))
    end_page = clean_text(bib.get("end_page"))
    if start_page and end_page and start_page != end_page:
        page_text = f"{start_page}-{end_page}"
    else:
        page_text = start_page or end_page
    pages, article_number = split_page_metadata(page_text or None)

    record = SourceRecord(
        title=title,
        authors=authors,
        year=parse_year(bib.get("year")),
        journal=normalize_journal_name(journal.get("title")),
        abstract=clean_text(bib.get("abstract")),
        url=url,
        doi=doi,
        language=language,
        citation_count=0,  # DOAJ does not report citations.
        is_open_access=True,  # by definition: DOAJ is all open access
        is_review=is_review,
        work_type="review" if is_review else "article",
        volume=str(journal.get("volume")) if journal.get("volume") else None,
        issue=str(journal.get("number")) if journal.get("number") else None,
        pages=pages,
        article_number=article_number,
        publisher=clean_text(journal.get("publisher")),
        subjects=unique_sorted(subjects),
    )
    record.add_provider("doaj", str(bib.get("id") or doi or "") or None)
    set_record_authors(record, author_details)
    return record
