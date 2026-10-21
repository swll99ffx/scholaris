"""
CORE adapter (CORE.ac.uk).

CORE aggregates open-access content from repositories and journals worldwide.
It needs a free API key; without one this adapter simply returns no results
(the other providers still work). Get a key (free) at:
https://core.ac.uk/services/api

Docs: https://api.core.ac.uk/docs/v3
"""

from __future__ import annotations

import re

import httpx

from app.config import Settings
from app.core.http import fetch
from app.core.rate_limit import RateLimiter

from ..models import SourceRecord
from ..schemas import SearchFilters
from .authors import AuthorName, display_authors, parse_flat_name, set_record_authors
from .text import clean_text, normalize_doi, normalize_journal_name, parse_year, safe_int, unique_sorted

# Trailing slash avoids an extra 301 redirect (and a Cloudflare round-trip).
BASE_URL = "https://api.core.ac.uk/v3/search/works/"
limiter = RateLimiter(min_interval_seconds=0.5)

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
    if not settings.core_api_key:
        return []

    headers = {
        "Authorization": f"Bearer {settings.core_api_key}",
        "Accept": "application/json",
    }
    # CORE responses are large and slow. Ten records are plenty for a result
    # page, and one attempt prevents a second 20-second wait.
    params = {"q": query, "limit": str(max(1, min(limit, 10)))}

    data = await fetch(
        client,
        provider="CORE",
        url=BASE_URL,
        params=params,
        limiter=limiter,
        headers=headers,
        attempts=1,
    )
    return [to_record(item) for item in data.get("results", []) if item.get("title")]


def to_record(item: dict) -> SourceRecord:
    author_details: list[AuthorName] = []
    for author in item.get("authors") or []:
        name = clean_text(author.get("name"))
        if not name:
            continue
        detail = parse_flat_name(name, source="core")
        orcid = clean_text(author.get("orcid"))
        if orcid:
            detail.orcid = orcid
        author_details.append(detail)
    authors = display_authors(author_details)

    journals = item.get("journals") or []
    journal = (
        normalize_journal_name(journals[0].get("title"))
        if journals and journals[0].get("title")
        else None
    )

    url = item.get("downloadUrl")
    for link in item.get("links") or []:
        if link.get("url"):
            url = link["url"]
            break

    raw_language = item.get("language")
    if isinstance(raw_language, dict):
        language = raw_language.get("code") or raw_language.get("name")
    else:
        language = str(raw_language) if raw_language else None

    title = clean_text(item.get("title"))
    is_review = bool(_REVIEW_TITLE_RE.search(title))

    record = SourceRecord(
        title=title,
        authors=authors,
        year=parse_year(item.get("yearPublished")),
        journal=journal,
        abstract=clean_text(item.get("abstract")),
        url=url,
        doi=normalize_doi(item.get("doi")),
        language=language,
        citation_count=safe_int(item.get("citationCount")),
        is_open_access=True,  # CORE is an open-access aggregator
        is_review=is_review,
        work_type="review" if is_review else "article",
        publisher=clean_text(item.get("publisher")),
        subjects=unique_sorted([str(t) for t in (item.get("fieldOfStudy") or []) if t]),
    )
    record.add_provider("core", str(item.get("id") or "") or None)
    set_record_authors(record, author_details)
    return record
