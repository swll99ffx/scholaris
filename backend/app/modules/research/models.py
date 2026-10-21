"""
Internal, provider-neutral representation of a scholarly source.

Every API adapter converts its own JSON/XML into SourceRecord, so the merge,
ranking, citation and library layers never need to know which API a paper
came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .services.authors import AuthorCheck, AuthorName


@dataclass(slots=True)
class SourceRecord:
    title: str
    # Display-only strings. Citations consume structured `author_details`.
    authors: list[str] = field(default_factory=list)
    author_details: list[AuthorName] = field(default_factory=list)
    author_check: AuthorCheck = field(default_factory=AuthorCheck)
    year: int | None = None
    journal: str | None = None
    abstract: str = ""
    url: str | None = None
    doi: str | None = None
    # ISO-ish language code from the provider ("en", "id", "eng", "English").
    # Used to keep the results list English-only by default.
    language: str | None = None
    citation_count: int = 0
    is_open_access: bool | None = None
    is_review: bool | None = None
    is_retracted: bool = False
    work_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    # Used by APA 7 when a journal article has an article/e-location number
    # instead of a page range (for example "Article e12345").
    article_number: str | None = None
    publisher: str | None = None
    subjects: list[str] = field(default_factory=list)
    oa_url: str | None = None

    # Which free APIs returned this record and their native identifiers.
    providers: list[str] = field(default_factory=list)
    provider_ids: dict[str, str] = field(default_factory=dict)

    # Used by "find related sources" so the UI can explain why a paper appeared.
    discovery: str | None = None

    # Filled in by ranking + presentation.
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    is_administrative: bool = False
    # A meeting/conference/workshop report is not a primary research article.
    is_non_primary: bool = False
    # Query words this record actually covers (so the UI can show "matched on …").
    matched_terms: list[str] = field(default_factory=list)
    reason: str = ""
    ai_note: str = ""
    ai_note_source: str = "heuristic"

    def add_provider(self, provider: str, provider_id: str | None = None) -> None:
        if provider not in self.providers:
            self.providers.append(provider)
        if provider_id:
            self.provider_ids[provider] = provider_id

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "doi": self.doi,
            "providers": self.providers,
            "score": self.score,
        }
