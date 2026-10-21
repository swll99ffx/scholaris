"""HTTP endpoints for Module 2: Source Summarizer."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import Settings, get_settings

from .schemas import (
    Quote,
    SaveSummaryRequest,
    SaveSummaryResponse,
    SourceMeta,
    SummarizeRequest,
    SummaryOut,
)
from .services.extract import (
    MAX_PDF_BYTES,
    Document,
    PdfError,
    document_from_text,
    read_pdf,
    split_sentences,
)
from .services.save import save_summary
from .services.summarize import quote_text, summarize_document

router = APIRouter(prefix="/api/summarize", tags=["summarize"])


def _derive_title(source: SourceMeta, document: Document) -> str:
    if source.title.strip():
        return source.title.strip()
    first = next(iter(split_sentences(document.text)), "")
    if first:
        title = " ".join(first.split()[:14]).rstrip(",;:")
        return title[:120]
    return "Untitled source"


def _build_quotes(document: Document, indices: list[int], quote_count: int) -> list[Quote]:
    if quote_count <= 0:
        return []
    quotes: list[Quote] = []
    for index in indices[:quote_count]:
        sentence = quote_text(document, index)
        if sentence is None:
            continue
        note = f"Verbatim from page {sentence.page}" if sentence.page else "Verbatim from your text"
        quotes.append(Quote(text=sentence.text, page=sentence.page, note=note))
    return quotes


async def _summarize(
    document: Document,
    source: SourceMeta,
    settings: Settings,
    quote_count: int,
) -> SummaryOut:
    title = _derive_title(source, document)
    source = source.model_copy(update={"title": title})

    draft, ai_source = await summarize_document(
        document,
        source_title=title,
        settings=settings,
        quote_count=quote_count,
    )
    warnings = list(dict.fromkeys([*document.warnings, *draft.warnings]))

    return SummaryOut(
        source=source,
        tldr=draft.tldr,
        key_points=draft.key_points,
        methods=draft.methods,
        findings=draft.findings,
        limitations=draft.limitations,
        quotes=_build_quotes(document, draft.quote_indices, quote_count),
        excerpt=document.excerpt,
        ai_source=ai_source,  # type: ignore[arg-type]
        word_count=document.word_count,
        page_count=document.page_count,
        truncated=document.truncated,
        warnings=warnings,
    )


@router.post("/text", response_model=SummaryOut)
async def summarize_text(
    request: SummarizeRequest,
    settings: Settings = Depends(get_settings),
) -> SummaryOut:
    start = time.perf_counter()
    try:
        document = await asyncio.to_thread(document_from_text, request.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    summary = await _summarize(document, request.source, settings, request.quote_count)
    summary.took_ms = int((time.perf_counter() - start) * 1000)
    return summary


def _parse_year(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        year = int(float(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Year must be a number such as 2024.",
        ) from exc
    if not 1500 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Year must be between 1500 and 2100.",
        )
    return year


@router.post("/pdf", response_model=SummaryOut)
async def summarize_pdf(
    file: UploadFile = File(...),
    title: str = Form(""),
    authors: str = Form(""),
    year: str = Form(""),
    journal: str = Form(""),
    doi: str = Form(""),
    url: str = Form(""),
    quote_count: int = Form(3),
    settings: Settings = Depends(get_settings),
) -> SummaryOut:
    start = time.perf_counter()
    data = await file.read(MAX_PDF_BYTES + 1)
    try:
        document = await asyncio.to_thread(read_pdf, data)
    except PdfError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    source = SourceMeta(
        title=title,
        authors=[part.strip() for part in authors.split(",") if part.strip()],
        year=_parse_year(year),
        journal=journal.strip() or None,
        doi=doi.strip() or None,
        url=url.strip() or None,
    )
    summary = await _summarize(document, source, settings, max(0, min(quote_count, 6)))
    summary.took_ms = int((time.perf_counter() - start) * 1000)
    return summary


@router.post("/save", response_model=SaveSummaryResponse)
async def save_to_library(
    request: SaveSummaryRequest,
    settings: Settings = Depends(get_settings),
) -> SaveSummaryResponse:
    try:
        result = await asyncio.to_thread(
            save_summary,
            settings.database_path,
            request.summary.model_dump(),
            request.library_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That saved library source was not found. It may have been deleted.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    return SaveSummaryResponse(**result)
