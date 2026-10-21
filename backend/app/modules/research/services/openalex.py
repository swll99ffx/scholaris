"""
OpenAlex adapter.

OpenAlex is a free, open catalogue of ~250M scholarly works. It is the
backbone of this module because it provides abstracts, citation counts,
open-access status, references and citing papers in one place.

Docs: https://docs.openalex.org/
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings
from app.core.errors import ProviderError
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
    reconstruct_abstract,
    safe_int,
    split_page_metadata,
    unique_sorted,
)

BASE_URL = "https://api.openalex.org/works"
limiter = RateLimiter(min_interval_seconds=0.12)

# OpenAlex concept IDs used by the subject filter. These are stable, broad
# concepts; the post-filter in ranking.py is a second safety net.
SUBJECT_CONCEPT_IDS = {
    "math": "C33923547",       # Mathematics
    "biology": "C86803240",    # Biology
    "science": "C121332964",   # Physics (science filter also post-filters)
}

_REVIEW_TITLE_RE = re.compile(
    r"\b(systematic review|literature review|meta-analysis|scoping review|narrative review)\b",
    re.IGNORECASE,
)


def _base_params(settings: Settings) -> dict[str, Any]:
    params: dict[str, Any] = {"mailto": settings.contact_email}
    if settings.openalex_api_key:
        # OpenAlex now budgets anonymous traffic per IP. A free key is strongly
        # recommended; we never log or expose it.
        params["api_key"] = settings.openalex_api_key
    return params


async def search(
    client: httpx.AsyncClient,
    *,
    query: str,
    filters: SearchFilters,
    settings: Settings,
    limit: int,
) -> list[SourceRecord]:
    clauses: list[str] = []
    if filters.year_from:
        clauses.append(f"from_publication_date:{filters.year_from}-01-01")
    if filters.year_to:
        clauses.append(f"to_publication_date:{filters.year_to}-12-31")
    if filters.reviews_only:
        clauses.append("type:review")
    if filters.open_access_only:
        clauses.append("is_oa:true")

    concept_id = SUBJECT_CONCEPT_IDS.get(filters.subject)
    if concept_id:
        clauses.append(f"concepts.id:{concept_id}")

    params = _base_params(settings)
    params.update(
        {
            "search": query,
            "per-page": max(1, min(limit, 50)),
            "sort": "relevance_score:desc",
        }
    )
    if clauses:
        params["filter"] = ",".join(clauses)

    data = await fetch(
        client,
        provider="OpenAlex",
        url=BASE_URL,
        params=params,
        limiter=limiter,
    )
    return [to_record(work) for work in data.get("results", []) if work]


def to_record(work: dict[str, Any]) -> SourceRecord:
    work_id = str(work.get("id") or "")
    openalex_id = work_id.rsplit("/", 1)[-1] if work_id else None

    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    biblio = work.get("biblio") or {}

    author_details: list[AuthorName] = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name") or authorship.get("raw_author_name")
        if not name:
            continue
        detail = parse_flat_name(clean_text(name), source="openalex")
        # OpenAlex exposes display names rather than reliable family/given
        # fields. Keep its ORCID so a later Crossref/OpenAlex merge can retain
        # the identifier, but do not pretend the flat name is structured.
        orcid = clean_text(author.get("orcid"))
        if orcid:
            detail.orcid = orcid
        author_details.append(detail)
    authors = display_authors(author_details)

    url = (
        primary.get("landing_page_url")
        or work.get("doi")
        or work_id
        or None
    )
    oa = work.get("open_access") or {}
    best_oa = work.get("best_oa_location") or {}

    work_type = str(work.get("type") or "")
    crossref_type = str(work.get("type_crossref") or "")
    title = clean_text(work.get("display_name") or work.get("title") or "")
    is_review = (
        work_type == "review"
        or crossref_type in {"review-article", "review"}
        or bool(_REVIEW_TITLE_RE.search(title))
    )

    subjects: list[str] = []
    topic = work.get("primary_topic") or {}
    if topic:
        for key in ("display_name",):
            if topic.get(key):
                subjects.append(topic[key])
        for key in ("subfield", "field", "domain"):
            nested = topic.get(key) or {}
            if nested.get("display_name"):
                subjects.append(nested["display_name"])
    for concept in (work.get("concepts") or [])[:6]:
        if concept.get("display_name"):
            subjects.append(concept["display_name"])

    first_page = biblio.get("first_page")
    last_page = biblio.get("last_page")
    if first_page and last_page and first_page != last_page:
        page_text = f"{first_page}-{last_page}"
    else:
        page_text = first_page or last_page
    pages, article_number = split_page_metadata(
        str(page_text) if page_text else None
    )

    record = SourceRecord(
        title=title,
        authors=authors,
        year=parse_year(work.get("publication_year") or work.get("publication_date")),
        journal=normalize_journal_name(source.get("display_name") or primary.get("raw_source_name")),
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        url=url,
        doi=normalize_doi(work.get("doi")),
        language=str(work.get("language")) if work.get("language") else None,
        citation_count=safe_int(work.get("cited_by_count")),
        is_open_access=bool(oa["is_oa"]) if "is_oa" in oa else None,
        is_review=is_review,
        is_retracted=bool(work.get("is_retracted")),
        work_type=work_type or crossref_type or None,
        volume=str(biblio["volume"]) if biblio.get("volume") else None,
        issue=str(biblio["issue"]) if biblio.get("issue") else None,
        pages=pages,
        article_number=article_number,
        publisher=clean_text(source.get("host_organization_name")),
        subjects=unique_sorted(subjects),
        oa_url=best_oa.get("landing_page_url") or best_oa.get("pdf_url"),
    )
    record.add_provider("openalex", openalex_id)
    set_record_authors(record, author_details)
    return record


async def get_work_raw(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    doi: str | None = None,
    openalex_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any] | None:
    """Return the raw OpenAlex work (we need referenced_works for related sources)."""
    params = _base_params(settings)
    params["per-page"] = 1

    if doi:
        params["filter"] = f"doi:{normalize_doi(doi)}"
    elif openalex_id:
        short_id = openalex_id.rsplit("/", 1)[-1]
        params["filter"] = f"ids.openalex:{short_id}"
    elif title:
        params["search"] = title
    else:
        return None

    data = await fetch(
        client,
        provider="OpenAlex",
        url=BASE_URL,
        params=params,
        limiter=limiter,
    )
    results = data.get("results") or []
    return results[0] if results else None


async def get_work(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    doi: str | None = None,
    openalex_id: str | None = None,
    title: str | None = None,
) -> SourceRecord | None:
    """Find one canonical OpenAlex work for the related-sources feature."""
    raw = await get_work_raw(
        client,
        settings=settings,
        doi=doi,
        openalex_id=openalex_id,
        title=title,
    )
    return to_record(raw) if raw else None


async def fetch_by_ids(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    openalex_ids: list[str],
    limit: int,
) -> list[SourceRecord]:
    """Batch-fetch referenced works by their OpenAlex IDs."""
    short_ids = [item.rsplit("/", 1)[-1] for item in openalex_ids if item][:25]
    if not short_ids:
        return []
    params = _base_params(settings)
    params.update(
        {
            "filter": "ids.openalex:" + "|".join(short_ids),
            "per-page": max(1, min(limit, 50)),
        }
    )
    data = await fetch(
        client,
        provider="OpenAlex",
        url=BASE_URL,
        params=params,
        limiter=limiter,
    )
    return [to_record(work) for work in data.get("results", []) if work]


async def backfill_citation_counts(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    records: list[SourceRecord],
    batch_size: int = 50,
) -> None:
    """
    Fill missing citation counts from OpenAlex (matched by DOI).

    Crossref, PubMed and DOAJ do not report citations, so without this a
    landmark paper can look uncited and never reach the top of the list.
    """
    targets = [record for record in records if record.citation_count == 0 and normalize_doi(record.doi)]
    if not targets:
        return

    dois = list({normalize_doi(record.doi) for record in targets})
    counts: dict[str, int] = {}

    for start in range(0, len(dois), batch_size):
        chunk = dois[start : start + batch_size]
        params = _base_params(settings)
        params.update(
            {
                "filter": "doi:" + "|".join(chunk),
                "per-page": len(chunk),
                "select": "doi,cited_by_count",
            }
        )
        try:
            data = await fetch(
                client,
                provider="OpenAlex",
                url=BASE_URL,
                params=params,
                limiter=limiter,
            )
        except ProviderError:
            return
        for work in data.get("results", []):
            key = normalize_doi(work.get("doi"))
            if key:
                counts[key] = safe_int(work.get("cited_by_count"))

    for record in targets:
        value = counts.get(normalize_doi(record.doi))
        if value:
            record.citation_count = value


async def fetch_citing(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    openalex_id: str,
    limit: int,
) -> list[SourceRecord]:
    short_id = openalex_id.rsplit("/", 1)[-1]
    params = _base_params(settings)
    params.update(
        {
            "filter": f"cites:{short_id}",
            "sort": "cited_by_count:desc",
            "per-page": max(1, min(limit, 50)),
        }
    )
    data = await fetch(
        client,
        provider="OpenAlex",
        url=BASE_URL,
        params=params,
        limiter=limiter,
    )
    return [to_record(work) for work in data.get("results", []) if work]
