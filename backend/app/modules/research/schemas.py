"""API request/response models for Module 1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SubjectFilter = Literal["any", "science", "math", "biology", "general"]
CredibilityStatus = Literal["good", "warn", "unknown"]
# How aggressively off-topic results are removed.
RelevanceMode = Literal["strict", "balanced"]
ResultsExportFormat = Literal["bibtex", "txt", "csv"]


class SearchFilters(BaseModel):
    year_from: int | None = Field(default=None, ge=1500, le=2100)
    year_to: int | None = Field(default=None, ge=1500, le=2100)
    reviews_only: bool = False
    open_access_only: bool = False
    # Keep the list English-only by default (scholarly databases are multilingual).
    english_only: bool = True
    subject: SubjectFilter = "any"
    # "strict" drops everything below a relevance floor; "balanced" keeps the
    # borderline ones for broad or exploratory topics.
    relevance_mode: RelevanceMode = "strict"
    # Hidden feed cap. The UI renders progressive pages of 20 and no longer
    # exposes a "max sources" control.
    limit: int = Field(default=20, ge=1, le=100)
    # Opt-in slow repository coverage (mainly CORE). Normal searches stay fast.
    deep_search: bool = False
    exclude_preprints: bool = False

    @field_validator("year_to")
    @classmethod
    def _year_order(cls, value: int | None, info):
        year_from = info.data.get("year_from")
        if value is not None and year_from is not None and value < year_from:
            raise ValueError("year_to must be greater than or equal to year_from")
        return value


class SearchRequest(BaseModel):
    # max_length is generous so a whole pasted activity/lab brief is accepted;
    # the backend reduces it to a real topic before searching.
    query: str = Field(min_length=2, max_length=8000)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class CitationStyles(BaseModel):
    apa: str = ""
    mla: str = ""
    chicago: str = ""


class AuthorOut(BaseModel):
    family: str = ""
    given: str = ""
    literal: str = ""
    suffix: str = ""
    orcid: str | None = None
    source: str = ""


class AuthorCheckOut(BaseModel):
    status: Literal["ok", "needs_checking"] = "ok"
    reason: str = ""
    conflicts: list[str] = []


class CredibilityItem(BaseModel):
    label: str
    status: CredibilityStatus
    detail: str


class ConceptOut(BaseModel):
    label: str
    historical: str | None = None
    current: str
    alternate_names: list[str] = []
    obsolete: bool = False
    primary: bool = False
    source: Literal["curated", "heuristic", "llm"] = "heuristic"


class SourceOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    # Display-only names. Structured fields below drive the citation styles.
    authors: list[str] = []
    author_details: list[AuthorOut] = []
    author_check: AuthorCheckOut = Field(default_factory=AuthorCheckOut)
    year: int | None = None
    journal: str | None = None
    abstract: str = ""
    url: str | None = None
    doi: str | None = None
    language: str | None = None
    citation_count: int = 0
    is_open_access: bool | None = None
    is_review: bool | None = None
    is_retracted: bool = False
    is_preprint: bool = False
    is_non_primary: bool = False
    work_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    article_number: str | None = None
    publisher: str | None = None
    subjects: list[str] = []
    providers: list[str] = []
    provider_ids: dict[str, str] = {}
    discovery: str | None = None

    score: float = 0.0
    score_breakdown: dict[str, float] = {}
    is_administrative: bool = False
    matched_terms: list[str] = []
    reason: str = ""
    ai_note: str = ""
    ai_note_source: Literal["llm", "heuristic"] = "heuristic"
    credibility: list[CredibilityItem] = []
    citation_styles: CitationStyles = Field(
        default_factory=lambda: CitationStyles(apa="", mla="", chicago="")
    )


InputMode = Literal["direct", "keywords", "title", "heuristic", "llm"]


class SearchResponse(BaseModel):
    query: str
    # The topic we actually searched for (may differ from `query` when the
    # student pasted a long assignment brief).
    topic: str = ""
    input_mode: InputMode = "direct"
    keywords: list[str] = []
    concepts: list[ConceptOut] = []
    count: int
    sources: list[SourceOut]
    warnings: list[str] = []
    took_ms: int = 0
    cached: bool = False


class NoteItem(BaseModel):
    id: str
    note: str
    source: Literal["llm", "heuristic"] = "heuristic"


class NotesRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    sources: list[SourceOut] = Field(default_factory=list, max_length=12)


class NotesResponse(BaseModel):
    notes: list[NoteItem] = []


class ResultsExportRequest(BaseModel):
    sources: list[SourceOut] = Field(default_factory=list, max_length=100)
    format: ResultsExportFormat = "bibtex"


class RelatedRequest(BaseModel):
    doi: str | None = None
    openalex_id: str | None = None
    title: str | None = None
    limit: int = Field(default=15, ge=1, le=30)


class RelatedResponse(SearchResponse):
    parent_title: str = ""


class LibrarySaveRequest(BaseModel):
    source: SourceOut
    notes: str = ""
    tags: list[str] = []

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str]) -> list[str]:
        return [tag.strip() for tag in tags if tag.strip()]


class LibraryUpdateRequest(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        return [tag.strip() for tag in tags if tag.strip()]


class LibraryItem(SourceOut):
    library_id: str
    notes: str = ""
    tags: list[str] = []
    saved_at: str


class LibraryListResponse(BaseModel):
    count: int
    sources: list[LibraryItem]
