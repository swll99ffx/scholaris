"""
De-duplicate and merge records returned by different free APIs.

The same paper is often in OpenAlex, Semantic Scholar, Crossref and PubMed.
We match on DOI first, then a normalised title, then a fuzzy title match (only
when at least one record is missing a DOI). Fields are merged so the final
record has the best available abstract, citation count, journal metadata, etc.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from ..models import SourceRecord
from .authors import (
    display_authors,
    ensure_author_details,
    merge_author_details,
    set_record_authors,
)
from .text import clean_article_number, normalize_doi, normalize_title

# Lower number = more trustworthy for bibliographic fields.
PROVIDER_PRIORITY = {
    "pubmed": 0,
    "crossref": 1,
    "openalex": 2,
    "semantic_scholar": 3,
}


def _priority(record: SourceRecord) -> int:
    if not record.providers:
        return 9
    return min(PROVIDER_PRIORITY.get(provider, 9) for provider in record.providers)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if value.strip() and key not in seen:
            seen.add(key)
            result.append(value.strip())
    return result


def _merge_bool(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    if a is False or b is False:
        return False
    return None


def merge_pair(base: SourceRecord, other: SourceRecord) -> SourceRecord:
    """Merge two records describing the same work. Mutates and returns base."""
    prefer_other = _priority(other) < _priority(base)
    base_source = ", ".join(base.providers) or "provider record"
    other_source = ", ".join(other.providers) or "provider record"

    def pick(primary: str | None, secondary: str | None) -> str | None:
        if prefer_other:
            return secondary or primary
        return primary or secondary

    # Titles: keep the longer (usually more complete) version.
    if len(other.title) > len(base.title):
        base.title = other.title

    # Abstracts: keep the longest non-empty abstract.
    if len(other.abstract) > len(base.abstract):
        base.abstract = other.abstract

    base.year = base.year or other.year
    if prefer_other and other.year:
        base.year = other.year

    base.journal = pick(base.journal, other.journal)
    base.doi = base.doi or other.doi
    base.url = base.url or other.url
    base.oa_url = base.oa_url or other.oa_url
    base.volume = pick(base.volume, other.volume)
    base.issue = pick(base.issue, other.issue)
    base.pages = pick(base.pages, other.pages)
    base.article_number = pick(base.article_number, other.article_number)
    base.publisher = pick(base.publisher, other.publisher)

    # Providers sometimes repeat the article number in the page field. Do not
    # let that duplicate hide the \"Article [number]\" APA formatting.
    if base.article_number and base.pages:
        page_value = clean_article_number(base.pages)
        number_value = clean_article_number(base.article_number)
        if page_value and number_value and page_value.lower() == number_value.lower():
            base.pages = None

    base.citation_count = max(base.citation_count, other.citation_count)
    base.is_open_access = _merge_bool(base.is_open_access, other.is_open_access)
    base.is_review = _merge_bool(base.is_review, other.is_review)
    base.is_retracted = base.is_retracted or other.is_retracted

    if base.is_review:
        base.work_type = "review"
    elif not base.work_type:
        base.work_type = other.work_type

    base.subjects = _unique(base.subjects + other.subjects)
    base.providers = _unique(base.providers + other.providers)
    base.provider_ids.update(other.provider_ids)

    discovery = [value for value in (base.discovery, other.discovery) if value]
    base.discovery = " · ".join(_unique(discovery)) or None

    # Author metadata is compared, not just length-selected. If the providers
    # disagree on a name, keep the more complete list but mark the citations
    # for a human check.
    merged_authors, author_check = merge_author_details(
        ensure_author_details(base),
        ensure_author_details(other),
        prefer_second=prefer_other,
        first_check=base.author_check,
        second_check=other.author_check,
        first_source=base_source,
        second_source=other_source,
    )
    set_record_authors(base, merged_authors, display_names=display_authors(merged_authors))
    base.author_check = author_check
    return base


def merge_records(records: list[SourceRecord]) -> list[SourceRecord]:
    clusters: list[SourceRecord] = []
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}

    for record in records:
        if not record.title:
            continue

        title_key = normalize_title(record.title)
        doi = normalize_doi(record.doi)

        index: int | None = None
        if doi and doi in by_doi:
            index = by_doi[doi]
        if index is None and title_key and title_key in by_title:
            candidate = clusters[by_title[title_key]]
            candidate_doi = normalize_doi(candidate.doi)
            # Same title but two different DOIs means two different works.
            if not (candidate_doi and doi and candidate_doi != doi):
                index = by_title[title_key]

        # Fuzzy title matching only when we cannot compare DOIs; two papers with
        # different DOIs are different papers even if their titles look alike.
        if index is None:
            for candidate_index, candidate in enumerate(clusters):
                candidate_doi = normalize_doi(candidate.doi)
                if candidate_doi and doi and candidate_doi != doi:
                    continue
                if candidate.year and record.year and abs(candidate.year - record.year) > 1:
                    continue
                ratio = SequenceMatcher(
                    None, title_key, normalize_title(candidate.title)
                ).ratio()
                if ratio >= 0.95:
                    index = candidate_index
                    break

        if index is None:
            clusters.append(record)
            index = len(clusters) - 1
        else:
            clusters[index] = merge_pair(clusters[index], record)

        merged = clusters[index]
        merged_doi = normalize_doi(merged.doi)
        if merged_doi:
            by_doi[merged_doi] = index
        merged_title = normalize_title(merged.title)
        if merged_title:
            by_title[merged_title] = index

    return clusters
