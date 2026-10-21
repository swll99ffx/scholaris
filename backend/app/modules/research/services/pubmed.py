"""
PubMed adapter (NCBI E-utilities).

PubMed covers biomedical and life-science literature. It is especially useful
for the biology module and for review articles. No key is required, but a free
NCBI key raises the rate limit.

Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.config import Settings
from app.core.errors import ProviderError
from app.core.http import fetch
from app.core.rate_limit import RateLimiter

from ..models import SourceRecord
from ..schemas import SearchFilters
from .authors import AuthorName, display_authors, set_record_authors
from .text import (
    clean_text,
    normalize_doi,
    parse_year,
    split_page_metadata,
    unique_sorted,
)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_ANON_LIMITER = RateLimiter(min_interval_seconds=0.35)
_KEY_LIMITER = RateLimiter(min_interval_seconds=0.11)


def _limiter(settings: Settings) -> RateLimiter:
    return _KEY_LIMITER if settings.ncbi_api_key else _ANON_LIMITER


async def search(
    client: httpx.AsyncClient,
    *,
    query: str,
    filters: SearchFilters,
    settings: Settings,
    limit: int,
) -> list[SourceRecord]:
    term = f"({query})"
    if filters.reviews_only:
        term += ' AND ("review"[Publication Type] OR "systematic review"[Publication Type] OR "meta-analysis"[Publication Type])'
    if filters.open_access_only:
        term += " AND free full text[sb]"

    common: dict[str, Any] = {
        "db": "pubmed",
        "tool": "Scholaris",
        "email": settings.contact_email,
    }
    if settings.ncbi_api_key:
        common["api_key"] = settings.ncbi_api_key

    search_params = {
        **common,
        "term": term,
        "retmode": "json",
        "retmax": max(1, min(limit, 50)),
        "sort": "relevance",
    }
    if filters.year_from:
        search_params["mindate"] = str(filters.year_from)
        search_params["maxdate"] = str(filters.year_to or 3000)
        search_params["datetype"] = "pdat"
    elif filters.year_to:
        search_params["mindate"] = "1500"
        search_params["maxdate"] = str(filters.year_to)
        search_params["datetype"] = "pdat"

    data = await fetch(
        client,
        provider="PubMed",
        url=ESEARCH_URL,
        params=search_params,
        limiter=_limiter(settings),
    )
    ids = ((data.get("esearchresult") or {}).get("idlist") or [])[:50]
    if not ids:
        return []

    fetch_params = {
        **common,
        "id": ",".join(ids),
        "retmode": "xml",
    }
    xml_text = await fetch(
        client,
        provider="PubMed",
        url=EFETCH_URL,
        params=fetch_params,
        limiter=_limiter(settings),
        parse="text",
    )
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProviderError("PubMed", "returned invalid XML") from exc

    records: list[SourceRecord] = []
    for article in root.findall(".//PubmedArticle"):
        record = _to_record(article, filters=filters)
        if record:
            records.append(record)
    return records


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return clean_text("".join(element.itertext()))


def _to_record(article: ET.Element, *, filters: SearchFilters) -> SourceRecord | None:
    title = _text(article.find(".//ArticleTitle"))
    if not title:
        return None

    pmid = _text(article.find(".//PMID"))

    abstract_parts: list[str] = []
    for abstract in article.findall(".//Abstract/AbstractText"):
        label = (abstract.get("Label") or "").strip()
        body = _text(abstract)
        if body:
            abstract_parts.append(f"{label}: {body}" if label else body)
    abstract = " ".join(abstract_parts)

    author_details: list[AuthorName] = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            author_details.append(AuthorName(literal=collective, source="pubmed"))
            continue
        fore = _text(author.find("ForeName"))
        last = _text(author.find("LastName"))
        suffix = _text(author.find("Suffix"))
        orcid = ""
        for identifier in author.findall("Identifier"):
            if (identifier.get("Source") or "").strip().upper() == "ORCID":
                orcid = _text(identifier)
                break
        if last or fore:
            author_details.append(
                AuthorName(
                    family=last,
                    given=fore,
                    suffix=suffix,
                    orcid=orcid,
                    source="pubmed",
                )
            )
    authors = display_authors(author_details)

    journal = _text(article.find(".//Journal/Title"))

    year = parse_year(_text(article.find(".//JournalIssue/PubDate/Year")))
    if year is None:
        year = parse_year(_text(article.find(".//JournalIssue/PubDate/MedlineDate")))

    doi = normalize_doi(
        _text(article.find(".//PubmedData/ArticleIdList/ArticleId[@IdType='doi']"))
    )
    pmc_id = _text(article.find(".//PubmedData/ArticleIdList/ArticleId[@IdType='pmc']"))

    pub_types = [
        _text(node).lower() for node in article.findall(".//PublicationTypeList/PublicationType")
    ]
    is_review = any("review" in item or "meta-analysis" in item for item in pub_types)

    subjects = []
    for node in article.findall(".//MeshHeading/DescriptorName"):
        label = _text(node)
        if label:
            subjects.append(label)

    volume = _text(article.find(".//JournalIssue/Volume"))
    issue = _text(article.find(".//JournalIssue/Issue"))
    raw_pages = _text(article.find(".//Pagination/MedlinePgn"))
    elocation = ""
    for node in article.findall(".//ELocationID"):
        if (node.get("EIdType") or "").strip().lower() in {"elocation", "pii"}:
            elocation = _text(node)
            break
    pages, article_number = split_page_metadata(raw_pages or None, elocation or None)

    language = _text(article.find(".//Article/Language")) or _text(
        article.find(".//MedlineJournalInfo/Language")
    )

    # PMC means a free full text version exists. When the user explicitly
    # filtered for free full text, every returned record satisfies that filter.
    is_oa: bool | None
    if pmc_id:
        is_oa = True
    elif filters.open_access_only:
        is_oa = True
    else:
        is_oa = None

    record = SourceRecord(
        title=title,
        authors=authors,
        year=year,
        journal=journal,
        abstract=abstract,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        doi=doi,
        language=language or None,
        citation_count=0,  # PubMed does not expose citation counts.
        is_open_access=is_oa,
        is_review=is_review,
        work_type="review" if is_review else "article",
        volume=volume or None,
        issue=issue or None,
        pages=pages,
        article_number=article_number,
        subjects=unique_sorted(subjects),
    )
    record.add_provider("pubmed", pmid or None)
    set_record_authors(record, author_details)
    return record
