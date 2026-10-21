"""API request/response models for Module 2: Source Summarizer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
