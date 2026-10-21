"""
Semantic Scholar adapter.

Semantic Scholar's free API adds strong relevance search and citation counts.
Anonymous traffic is limited to roughly one request per second, so we space
requests out and cache results.

Docs: https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.core.errors import ProviderError
from app.core.http import fetch
from app.core.rate_limit import RateLimiter

from ..models import SourceRecord
from ..schemas import SearchFilters
from .authors import display_authors, parse_flat_authors, set_record_authors
from .text import (
    clean_text,
    normalize_doi,
    normalize_journal_name,
    parse_year,
    safe_int,
    split_page_metadata,
    split_volume_issue,
    unique_sorted,
)

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

# Without a key we stay well under the ~1 request/second anonymous limit; the
# free key allows roughly 3/second. (A free key is the real cure — see README.)
_ANON_LIMITER = RateLimiter(min_interval_seconds=1.6)
_KEY_LIMITER = RateLimiter(min_interval_seconds=0.35)

FIELDS = ",".join(
    [
        "title",
        "abstract",
        "year",
        "publicationDate",
        "authors",
        "venue",
        "journal",
        "externalIds",
        "citationCount",
        "openAccessPdf",
        "isOpenAccess",
        "publicationTypes",
        "fieldsOfStudy",
        "url",
    ]
)

SUBJECT_FIELDS = {
    "math": "Mathematics",
    "biology": "Biology",
    # "science" is intentionally broad: Semantic Scholar accepts a comma list.
    "science": "Physics,Chemistry,Biology,Medicine,Environmental Science,Earth Sciences",
}


def _limiter(settings: Settings) -> RateLimiter:
    return _KEY_LIMITER if settings.semantic_scholar_api_key else _ANON_LIMITER


async def search(
    client: httpx.AsyncClient,
    *,
    query: str,
    filters: SearchFilters,
    settings: Settings,
    limit: int,
) -> list[SourceRecord]:
    params: dict[str, Any] = {
        "query": query,
        "limit": max(1, min(limit, 50)),
        "fields": FIELDS,
    }

    if filters.year_from or filters.year_to:
        params["year"] = f"{filters.year_from or ''}-{filters.year_to or ''}"
    if filters.reviews_only:
        params["publicationTypes"] = "Review"
    subject_fields = SUBJECT_FIELDS.get(filters.subject)
    if subject_fields:
        params["fieldsOfStudy"] = subject_fields

    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key

    # Anonymous traffic is rate-limited hard, so one attempt only: retrying a
    # 429 just makes it worse. With a key we can safely retry transient errors.
    attempts = 3 if settings.semantic_scholar_api_key else 1

    try:
        data = await fetch(
            client,
            provider="Semantic Scholar",
            url=SEARCH_URL,
            params=params,
            limiter=_limiter(settings),
            headers=headers or None,
            attempts=attempts,
        )
    except ProviderError as exc:
        # Some deployments reject the publicationTypes/fieldsOfStudy filters.
        # Retry once without the optional filters rather than losing the source.
        if exc.status == 400:
            params.pop("publicationTypes", None)
            params.pop("fieldsOfStudy", None)
            data = await fetch(
                client,
                provider="Semantic Scholar",
                url=SEARCH_URL,
                params=params,
                limiter=_limiter(settings),
                headers=headers or None,
                attempts=attempts,
            )
        else:
            raise

    records = [
        _to_record(paper)
        for paper in (data.get("data") or [])
        if paper and paper.get("title")
    ]

    if filters.open_access_only:
        records = [record for record in records if record.is_open_access is True]
    return records


def _to_record(paper: dict[str, Any]) -> SourceRecord:
    external = paper.get("externalIds") or {}
    journal = paper.get("journal") or {}
    open_access_pdf = paper.get("openAccessPdf") or {}

    publication_types = [str(item) for item in (paper.get("publicationTypes") or [])]
    is_review = any("review" in item.lower() for item in publication_types)

    author_details = parse_flat_authors(
        [
            clean_text(author.get("name"))
            for author in (paper.get("authors") or [])
            if author.get("name")
        ],
        source="semantic_scholar",
    )
    authors = display_authors(author_details)

    doi = normalize_doi(external.get("DOI"))
    url = paper.get("url") or (f"https://doi.org/{doi}" if doi else None)
    is_oa = paper.get("isOpenAccess")
    if is_oa is None:
        is_oa = bool(open_access_pdf.get("url"))
    pages, article_number = split_page_metadata(
        clean_text(journal.get("pages")) or None
    )
    volume, issue = split_volume_issue(
        str(journal.get("volume")) if journal.get("volume") else None
    )

    record = SourceRecord(
        title=clean_text(paper.get("title")),
        authors=authors,
        year=parse_year(paper.get("year") or paper.get("publicationDate")),
        journal=normalize_journal_name(journal.get("name") or paper.get("venue")),
        abstract=clean_text(paper.get("abstract")),
        url=url,
        doi=doi,
        citation_count=safe_int(paper.get("citationCount")),
        is_open_access=bool(is_oa) if is_oa is not None else None,
        is_review=is_review,
        work_type="review" if is_review else "article",
        volume=volume,
        issue=issue,
        pages=pages,
        article_number=article_number,
        subjects=unique_sorted([str(item) for item in (paper.get("fieldsOfStudy") or [])]),
        oa_url=open_access_pdf.get("url"),
    )
    record.add_provider("semantic_scholar", paper.get("paperId"))
    set_record_authors(record, author_details)
    return record
