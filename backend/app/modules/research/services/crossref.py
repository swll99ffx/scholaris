"""
Crossref adapter.

Crossref is the official DOI registry. It is excellent for accurate journal
names, volumes, pages and DOI metadata, which makes it the best source for
building citations.

Docs: https://api.crossref.org/swagger-ui/index.html
"""

from __future__ import annotations

import re
from typing import Any

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
    parse_year,
    safe_int,
    split_page_metadata,
    unique_sorted,
)

SEARCH_URL = "https://api.crossref.org/works"
limiter = RateLimiter(min_interval_seconds=0.2)

_REVIEW_TITLE_RE = re.compile(
    r"\b(systematic review|literature review|meta-analysis|scoping review|narrative review|review of)\b",
    re.IGNORECASE,
)
_CC_LICENSE_RE = re.compile(r"creativecommons\.org|/by/|/by-nc/|/by-sa/|/by-nc-sa/", re.IGNORECASE)

_SELECT = ",".join(
    [
        "DOI",
        "title",
        "author",
        "issued",
        "container-title",
        "abstract",
        "is-referenced-by-count",
        "URL",
        "type",
        "license",
        "volume",
        "issue",
        "page",
        "publisher",
        "subject",
    ]
)


async def search(
    client: httpx.AsyncClient,
    *,
    query: str,
    filters: SearchFilters,
    settings: Settings,
    limit: int,
) -> list[SourceRecord]:
    clauses = ["type:journal-article"]
    if filters.year_from:
        clauses.append(f"from-pub-date:{filters.year_from}-01-01")
    if filters.year_to:
        clauses.append(f"until-pub-date:{filters.year_to}-12-31")

    params: dict[str, Any] = {
        "query.bibliographic": query,
        "rows": max(1, min(limit, 50)),
        "filter": ",".join(clauses),
        "select": _SELECT,
        "mailto": settings.contact_email,
    }

    data = await fetch(
        client,
        provider="Crossref",
        url=SEARCH_URL,
        params=params,
        limiter=limiter,
    )

    records = [
        _to_record(item)
        for item in (data.get("message", {}).get("items") or [])
        if item and item.get("title")
    ]

    # Crossref cannot reliably label reviews or open-access status, so these
    # filters are applied to the fields it does expose.
    if filters.reviews_only:
        records = [record for record in records if record.is_review is True]
    if filters.open_access_only:
        records = [record for record in records if record.is_open_access is True]
    return records


def _to_record(item: dict[str, Any]) -> SourceRecord:
    titles = item.get("title") or []
    title = clean_text(titles[0] if titles else "")

    author_details: list[AuthorName] = []
    for author in item.get("author") or []:
        given = clean_text(author.get("given"))
        family = clean_text(author.get("family"))
        name = clean_text(author.get("name"))
        literal = clean_text(author.get("literal"))
        suffix = clean_text(author.get("suffix"))
        orcid = clean_text(author.get("ORCID"))
        if family or given:
            author_details.append(
                AuthorName(
                    family=family,
                    given=given,
                    suffix=suffix,
                    orcid=orcid,
                    source="crossref",
                )
            )
        elif literal:
            author_details.append(
                AuthorName(literal=literal, orcid=orcid, source="crossref")
            )
        elif name:
            detail = parse_flat_name(name, source="crossref")
            if orcid and not detail.orcid:
                detail.orcid = orcid
            author_details.append(detail)
    authors = display_authors(author_details)

    containers = item.get("container-title") or []
    journal = clean_text(containers[0] if containers else "")

    issued = (item.get("issued") or {}).get("date-parts") or []
    year = parse_year(issued[0][0]) if issued and issued[0] else None

    licenses = item.get("license") or []
    license_urls = " ".join(str(license.get("URL", "")) for license in licenses)
    if _CC_LICENSE_RE.search(license_urls):
        is_oa: bool | None = True
    elif license_urls.strip():
        is_oa = False
    else:
        is_oa = None

    doi = normalize_doi(item.get("DOI"))
    is_review = bool(_REVIEW_TITLE_RE.search(title))
    pages, article_number = split_page_metadata(
        clean_text(item.get("page")) or None,
        clean_text(item.get("article-number")) or None,
    )

    record = SourceRecord(
        title=title,
        authors=authors,
        year=year,
        journal=journal,
        abstract=clean_text(item.get("abstract")),
        url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
        doi=doi,
        language=str(item.get("language")) if item.get("language") else None,
        citation_count=safe_int(item.get("is-referenced-by-count")),
        is_open_access=is_oa,
        is_review=is_review,
        work_type=str(item.get("type") or "journal-article"),
        volume=str(item.get("volume")) if item.get("volume") else None,
        issue=str(item.get("issue")) if item.get("issue") else None,
        pages=pages,
        article_number=article_number,
        publisher=clean_text(item.get("publisher")),
        subjects=unique_sorted([str(subject) for subject in (item.get("subject") or [])]),
    )
    record.add_provider("crossref", doi)
    set_record_authors(record, author_details)
    return record
