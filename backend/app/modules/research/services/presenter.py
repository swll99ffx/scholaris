"""Convert internal SourceRecord objects into the JSON shape the UI expects."""

from __future__ import annotations

import hashlib

from ..models import SourceRecord
from .authors import ensure_author_check, ensure_author_details
from .citations import format_citations
from .ranking import credibility_checklist, is_preprint
from .text import normalize_doi

_PROVIDER_ORDER = [
    "openalex",
    "europepmc",
    "semantic_scholar",
    "crossref",
    "pubmed",
    "doaj",
    "core",
]


def source_id(record: SourceRecord) -> str:
    """A stable ID so saving the same paper twice updates the same library row."""
    doi = normalize_doi(record.doi)
    if doi:
        return f"doi:{doi}"
    for provider in _PROVIDER_ORDER:
        provider_id = record.provider_ids.get(provider)
        if provider_id:
            return f"{provider}:{provider_id}"
    digest = hashlib.sha1(f"{record.title}|{record.year}".encode("utf-8")).hexdigest()[:16]
    return f"title:{digest}"


def _ordered_providers(providers: list[str]) -> list[str]:
    known = [name for name in _PROVIDER_ORDER if name in providers]
    extra = [name for name in providers if name not in _PROVIDER_ORDER]
    return known + extra


def to_out(record: SourceRecord) -> dict:
    author_details = ensure_author_details(record)
    author_check = ensure_author_check(record)
    return {
        "id": source_id(record),
        "title": record.title,
        "authors": record.authors,
        "author_details": [
            {
                "family": author.family,
                "given": author.given,
                "literal": author.literal,
                "suffix": author.suffix,
                "orcid": author.orcid,
                "source": author.source,
            }
            for author in author_details
        ],
        "author_check": {
            "status": author_check.status,
            "reason": author_check.reason,
            "conflicts": author_check.conflicts,
        },
        "year": record.year,
        "journal": record.journal,
        "abstract": record.abstract,
        "url": record.url,
        "doi": record.doi,
        "language": record.language,
        "citation_count": record.citation_count,
        "is_open_access": record.is_open_access,
        "is_review": record.is_review,
        "is_retracted": record.is_retracted,
        "is_preprint": is_preprint(record),
        "is_non_primary": record.is_non_primary,
        "work_type": record.work_type,
        "volume": record.volume,
        "issue": record.issue,
        "pages": record.pages,
        "article_number": record.article_number,
        "publisher": record.publisher,
        "subjects": record.subjects,
        "providers": _ordered_providers(record.providers),
        "provider_ids": record.provider_ids,
        "discovery": record.discovery,
        "score": record.score,
        "score_breakdown": record.score_breakdown,
        "is_administrative": record.is_administrative,
        "matched_terms": record.matched_terms,
        "reason": record.reason,
        "ai_note": record.ai_note,
        "ai_note_source": record.ai_note_source,
        "credibility": [item.model_dump() for item in credibility_checklist(record)],
        "citation_styles": format_citations(record),
    }
