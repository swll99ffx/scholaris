"""
"AI relevance note" generation.

Two tiers so the app never breaks and never costs money unexpectedly:
  1. heuristic  -> always available, built from the query and source metadata.
  2. LLM        -> used for the top results only, if an API key is configured.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from app.config import Settings
from app.core.llm import LLMClient

from ..models import SourceRecord
from ..schemas import SourceOut
from .ranking import relevance_score
from .text import clean_text

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
logger = logging.getLogger(__name__)
_SYSTEM_PROMPT = (
    "You are a concise academic study assistant. Write exactly two plain-English "
    "sentences that explain how a source connects to a student's research topic. "
    "Use only the information given. Do not invent findings, numbers or claims. "
    "No markdown, no bullet points, no quotes."
)


def _key_terms(query: str, record: SourceRecord, maximum: int = 3) -> list[str]:
    query_terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
    haystack = f"{record.title} {record.abstract[:2000]} {record.journal or ''}".lower()
    return [term for term in query.lower().split() if term in query_terms and term in haystack][:maximum]


def heuristic_note(query: str, record: SourceRecord) -> str:
    relevance = relevance_score(query, record)
    terms = _key_terms(query, record)
    focus = ", ".join(f"“{term}”" for term in terms) if terms else "your topic"

    if relevance >= 0.55:
        first = f"This source directly addresses “{query}”, with content on {focus}."
    elif relevance >= 0.3:
        first = f"This source is related to “{query}” and can support the {focus} part of your research."
    else:
        first = f"This source provides broader background that may help frame “{query}”."

    words = ["a"]
    if record.is_review:
        words.append("review")
    else:
        words.append("study")
    year_text = f" from {record.year}" if record.year else ""
    if record.citation_count >= 50:
        impact = f"with {record.citation_count:,} citations"
    elif record.citation_count > 0:
        impact = f"with {record.citation_count:,} citations so far"
    else:
        impact = "with limited citation data available"
    access = "open access" if record.is_open_access else "likely paywalled"

    second = f"It is {' '.join(words)}{year_text} {impact} and is {access}, so use it for the {focus} angle."
    return clean_text(f"{first} {second}")


def _two_sentences(text: str) -> str:
    text = clean_text(text.replace("*", ""))
    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(text) if sentence.strip()]
    return " ".join(sentences[:2])[:600]


async def _enrich_with_llm(
    query: str,
    records: list[SourceRecord],
    settings: Settings,
    *,
    budget_seconds: float | None = None,
) -> None:
    client = LLMClient(settings)
    if not client.available:
        return

    # The user's own endpoint handles parallel requests. Free models and the
    # keyless fallback rate-limit parallel calls, so serialise those.
    free_model = ":free" in (settings.llm_model or "").lower()
    concurrency = 3 if settings.llm_enabled and not free_model else 1
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(record: SourceRecord) -> None:
        prompt = (
            f"Student's research topic: {query}\n\n"
            f"Source title: {record.title}\n"
            f"Authors: {', '.join(record.authors[:4]) or 'unknown'}\n"
            f"Year: {record.year or 'unknown'}\n"
            f"Journal: {record.journal or 'unknown'}\n"
            f"Review article: {'yes' if record.is_review else 'no'}\n"
            f"Citations: {record.citation_count}\n"
            f"Abstract: {record.abstract[:1200] or 'not available'}\n\n"
            "Write the two sentences now."
        )
        async with semaphore:
            try:
                answer = await asyncio.wait_for(
                    client.complete(system=_SYSTEM_PROMPT, user=prompt, max_tokens=180),
                    timeout=settings.llm_note_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - a failed note must never break search
                logger.info("AI note skipped: %s", exc)
                return
        note = _two_sentences(answer)
        if note:
            record.ai_note = note
            record.ai_note_source = "llm"

    targets = sorted(records, key=lambda item: item.score, reverse=True)[
        : settings.llm_enrich_limit
    ]
    # A hard budget so the background note call never waits on a slow provider.
    try:
        await asyncio.wait_for(
            asyncio.gather(*(worker(record) for record in targets)),
            timeout=budget_seconds or settings.llm_notes_budget_seconds,
        )
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        pass


async def apply_notes(
    query: str,
    records: list[SourceRecord],
    settings: Settings,
    *,
    enrich_llm: bool = True,
) -> None:
    for record in records:
        record.ai_note = heuristic_note(query, record)
        record.ai_note_source = "heuristic"

    if enrich_llm and settings.llm_enrich_notes and records:
        await _enrich_with_llm(query, records, settings)


def _record_from_source(source: SourceOut) -> SourceRecord:
    """Rebuild just enough of a record to write a note for it."""
    return SourceRecord(
        title=source.title,
        authors=source.authors,
        year=source.year,
        journal=source.journal,
        abstract=source.abstract,
        url=source.url,
        doi=source.doi,
        language=source.language,
        citation_count=source.citation_count,
        is_open_access=source.is_open_access,
        is_review=source.is_review,
        is_retracted=source.is_retracted,
        work_type=source.work_type,
        subjects=source.subjects,
        providers=source.providers,
        score=source.score,
    )


async def generate_notes(
    query: str,
    sources: list[SourceOut],
    settings: Settings,
) -> list[dict[str, str]]:
    """Fill notes lazily after search results are already on screen.

    The endpoint returns a heuristic note immediately for every requested source
    and upgrades the top few with the LLM when one is configured. The search
    response itself never waits for this.
    """
    if not sources:
        return []

    records = [_record_from_source(source) for source in sources]
    for record in records:
        record.ai_note = heuristic_note(query, record)
        record.ai_note_source = "heuristic"

    if settings.llm_enrich_notes:
        await _enrich_with_llm(
            query,
            records,
            settings,
            budget_seconds=settings.llm_notes_api_budget_seconds,
        )

    return [
        {
            "id": source.id,
            "note": record.ai_note,
            "source": record.ai_note_source,
        }
        for source, record in zip(sources, records)
    ]
