"""API request/response models for Module 2: Source Summarizer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

DetailLevel = Literal["quick", "standard", "deep"]
SummaryMode = Literal["academic", "plain"]


class SourceMeta(BaseModel):
    """What we know about the paper being summarized (all optional)."""

    title: str = ""
    authors: list[str] = []
    year: int | None = Field(default=None, ge=1500, le=2100)
    journal: str | None = None
    doi: str | None = None
    url: str | None = None

    @field_validator("authors")
    @classmethod
    def _clean_authors(cls, authors: list[str]) -> list[str]:
        return [author.strip() for author in authors if author.strip()]


class SummarizeRequest(BaseModel):
    text: str = Field(min_length=80, max_length=120_000)
    source: SourceMeta = Field(default_factory=SourceMeta)
    quote_count: int = Field(default=3, ge=0, le=6)
    # quick = skim, standard = normal study summary, deep = fuller synthesis.
    detail: DetailLevel = "standard"
    # academic = normal study language, plain = everyday explanations.
    mode: SummaryMode = "academic"

    @field_validator("text")
    @classmethod
    def _needs_words(cls, text: str) -> str:
        if len(text.split()) < 25:
            raise ValueError("Add at least a full abstract (about 25 words or more).")
        return text


class Quote(BaseModel):
    text: str
    page: int | None = None
    note: str = ""


class SummaryCitations(BaseModel):
    """APA helpers built only from the details the student actually entered."""

    # "Lovelace", "Lovelace & Hopper" or "Lovelace et al."
    author_label: str = ""
    # "2025" or "n.d." (APA's no-date marker).
    year_label: str = ""
    in_text: str = ""
    narrative: str = ""
    reference: str = ""
    # What is still missing before this is submission-ready.
    note: str = ""


class SummaryOut(BaseModel):
    source: SourceMeta
    tldr: str
    key_points: list[str] = []
    methods: list[str] = []
    findings: list[str] = []
    limitations: list[str] = []
    quotes: list[Quote] = []
    # The opening of the source text, kept so a saved summary has context.
    excerpt: str = ""
    ai_source: Literal["llm", "heuristic"] = "heuristic"
    word_count: int = 0
    page_count: int | None = None
    truncated: bool = False
    warnings: list[str] = []
    took_ms: int = 0
    detail: DetailLevel = "standard"
    mode: SummaryMode = "academic"
    citations: SummaryCitations = Field(default_factory=SummaryCitations)
    # Short-lived token pointing at the stashed full text, so saving to the
    # library can keep the original source (groundwork for chat over sources).
    summary_id: str = ""


class DoiLookup(BaseModel):
    """Metadata resolved from an OpenAlex record for the DOI auto-fill button."""

    title: str = ""
    authors: list[str] = []
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None


class SaveSummaryRequest(BaseModel):
    summary: SummaryOut
    # When set, the summary is appended to this saved library source instead
    # of creating a new library entry.
    library_id: str | None = None


class SaveSummaryResponse(BaseModel):
    library_id: str
    title: str
    created: bool
    message: str
