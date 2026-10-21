"""
Europe PMC adapter.

Europe PMC aggregates PubMed, PMC full texts, Agricola, preprints and patents.
It gives us PMC coverage plus citation counts (which plain PubMed lacks).

Docs: https://europepmc.org/RestfulWebService
"""

from __future__ import annotations

import re

import httpx

from app.config import Settings
from app.core.http import fetch
from app.core.rate_limit import RateLimiter

from ..models import SourceRecord
from ..schemas import SearchFilters
from .authors import (
    AuthorName,
    display_authors,
    parse_flat_authors,
    parse_flat_name,
    set_record_authors,
)
from .text import (
    clean_text,
    normalize_doi,
    normalize_journal_name,
    parse_year,
    safe_int,
    split_page_metadata,
    unique_sorted,
)

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
limiter = RateLimiter(min_interval_seconds=0.2)

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
    clauses = [f"({query})"]
    if filters.reviews_only:
        clauses.append('PUB_TYPE:"review"')
    if filters.open_access_only:
        clauses.append("OPEN_ACCESS:Y")
    if filters.year_from or filters.year_to:
        low = filters.year_from or 1800
        high = filters.year_to or 3000
        clauses.append(f"FIRST_PDATE:[{low}-01-01 TO {high}-12-31]")

    params: dict[str, str] = {
        "query": " AND ".join(clauses),
        "format": "json",
        "pageSize": str(max(1, min(limit, 100))),
        "resultType": "core",
        "sort": "CITED desc",
    }
    if settings.contact_email:
        params["email"] = settings.contact_email

    data = await fetch(
        client,
        provider="Europe PMC",
        url=BASE_URL,
        params=params,
        limiter=limiter,
    )
    results = ((data.get("resultList") or {}).get("result")) or []
    return [to_record(item) for item in results if item and item.get("title")]


def to_record(result: dict) -> SourceRecord:
    journal_info = result.get("journalInfo") or {}
    journal_meta = journal_info.get("journal") or {}

    author_details: list[AuthorName] = []
    author_block = (result.get("authorList") or {}).get("author") or []
    if isinstance(author_block, dict):
        author_block = [author_block]
    for entry in author_block:
        if not isinstance(entry, dict):
            continue
        collective = clean_text(entry.get("collectiveName"))
        if collective:
            author_details.append(AuthorName(literal=collective, source="europepmc"))
            continue
        family = clean_text(entry.get("lastName"))
        given = clean_text(entry.get("firstName")) or clean_text(entry.get("initials"))
        suffix = clean_text(entry.get("suffix"))
        orcid = clean_text(entry.get("orcid") or entry.get("ORCID"))
        if family or given:
            author_details.append(
                AuthorName(
                    family=family,
                    given=given,
                    suffix=suffix,
                    orcid=orcid,
                    source="europepmc",
                )
            )
            continue
        full_name = clean_text(entry.get("fullName"))
        if full_name:
            author_details.append(parse_flat_name(full_name, source="europepmc"))

    if not author_details:
        names = [
            clean_text(name)
            for name in str(result.get("authorString") or "").split(",")
            if name.strip()
        ]
        author_details = parse_flat_authors(names, source="europepmc")
    authors = display_authors(author_details)

    pub_types = [
        str(item).lower() for item in ((result.get("pubTypeList") or {}).get("pubType") or [])
    ]
    title = clean_text(result.get("title"))
    is_review = any("review" in item or "meta-analysis" in item for item in pub_types) or bool(
        _REVIEW_TITLE_RE.search(title)
    )

    subjects: list[str] = []
    for node in (result.get("keywordList") or {}).get("keyword") or []:
        if node:
            subjects.append(str(node))

    source = str(result.get("source") or "MED")
    identifier = result.get("id") or result.get("pmid") or ""
    url = None
    if identifier:
        url = f"https://europepmc.org/article/{source}/{identifier}"
    elif result.get("pmid"):
        url = f"https://pubmed.ncbi.nlm.nih.gov/{result['pmid']}/"

    page_info = str(result.get("pageInfo") or "").strip()
    pages, article_number = split_page_metadata(page_info or None)

    record = SourceRecord(
        title=title,
        authors=authors,
        year=parse_year(result.get("pubYear") or journal_info.get("yearOfPublication")),
        journal=normalize_journal_name(journal_meta.get("title") or result.get("journalTitle")),
        abstract=clean_text(result.get("abstractText")),
        url=url,
        doi=normalize_doi(result.get("doi")),
        language=str(result.get("language")) if result.get("language") else None,
        citation_count=safe_int(result.get("citedByCount")),
        is_open_access=(result.get("isOpenAccess") == "Y") if "isOpenAccess" in result else None,
        is_review=is_review,
        work_type="review" if is_review else "article",
        volume=str(journal_info.get("volume")) if journal_info.get("volume") else None,
        issue=str(journal_info.get("issue")) if journal_info.get("issue") else None,
        pages=pages,
        article_number=article_number,
        publisher=clean_text(result.get("publisher")),
        subjects=unique_sorted(subjects),
    )
    record.add_provider("europepmc", str(result.get("pmid") or result.get("id") or "") or None)
    set_record_authors(record, author_details)
    return record
