"""HTTP endpoints for Module 2: Source Summarizer."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date
from typing import Literal

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.config import Settings, get_settings
from app.core.errors import ProviderError
from app.modules.research.services import library, openalex
from app.modules.research.services.text import normalize_doi

from .schemas import (
    DoiLookup,
    Quote,
    SaveSummaryRequest,
    SaveSummaryResponse,
    SourceMeta,
    SummarizeRequest,
    SummaryOut,
)
from .services.cite import build_citations
from .services.extract import (
    MAX_DOCX_BYTES,
    MAX_PDF_BYTES,
    Document,
    DocxError,
    PdfError,
    document_from_text,
    read_docx,
    read_pdf,
    split_sentences,
)
from .services.save import save_summary
from .services.summarize import quote_text, summarize_document

router = APIRouter(prefix="/api/summarize", tags=["summarize"])
logger = logging.getLogger(__name__)

_DETAIL = Literal["quick", "standard", "deep"]
_MODE = Literal["academic", "plain"]
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


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
    *,
    detail: str = "standard",
    mode: str = "academic",
) -> SummaryOut:
    title = _derive_title(source, document)
    source = source.model_copy(update={"title": title})

    draft, ai_source = await summarize_document(
        document,
        source_title=title,
        settings=settings,
        quote_count=quote_count,
        detail=detail,
        mode=mode,
    )
    warnings = list(dict.fromkeys([*document.warnings, *draft.warnings]))
    if mode == "plain" and ai_source != "llm":
        warnings.append(
            "Plain-English mode needs the online AI. This offline summary is extracted "
            "word-for-word from your text."
        )
    citations = build_citations(source)

    # Stash the source text for the save step (groundwork for chat over your
    # library). A failed stash must never break the summary itself.
    summary_id = ""
    try:
        summary_id = await asyncio.to_thread(
            library.stash_source_text, settings.database_path, document.text
        )
    except Exception:  # noqa: BLE001 - optional storage
        logger.warning("Could not stash source text for a summary", exc_info=True)

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
        detail=detail,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        citations=citations,
        summary_id=summary_id,
    )


def _source_from_form(
    *,
    title: str,
    authors: str,
    year: str,
    journal: str,
    doi: str,
    url: str,
) -> SourceMeta:
    return SourceMeta(
        title=title,
        authors=[part.strip() for part in authors.split(",") if part.strip()],
        year=_parse_year(year),
        journal=journal.strip() or None,
        doi=doi.strip() or None,
        url=url.strip() or None,
    )


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

    summary = await _summarize(
        document,
        request.source,
        settings,
        request.quote_count,
        detail=request.detail,
        mode=request.mode,
    )
    summary.took_ms = int((time.perf_counter() - start) * 1000)
    return summary


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
    detail: _DETAIL = Form("standard"),
    mode: _MODE = Form("academic"),
    settings: Settings = Depends(get_settings),
) -> SummaryOut:
    start = time.perf_counter()
    data = await file.read(MAX_PDF_BYTES + 1)
    try:
        document = await asyncio.to_thread(read_pdf, data)
    except PdfError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    source = _source_from_form(
        title=title, authors=authors, year=year, journal=journal, doi=doi, url=url
    )
    summary = await _summarize(
        document,
        source,
        settings,
        max(0, min(quote_count, 6)),
        detail=detail,
        mode=mode,
    )
    summary.took_ms = int((time.perf_counter() - start) * 1000)
    return summary


@router.post("/docx", response_model=SummaryOut)
async def summarize_docx(
    file: UploadFile = File(...),
    title: str = Form(""),
    authors: str = Form(""),
    year: str = Form(""),
    journal: str = Form(""),
    doi: str = Form(""),
    url: str = Form(""),
    quote_count: int = Form(3),
    detail: _DETAIL = Form("standard"),
    mode: _MODE = Form("academic"),
    settings: Settings = Depends(get_settings),
) -> SummaryOut:
    start = time.perf_counter()
    data = await file.read(MAX_DOCX_BYTES + 1)
    try:
        document = await asyncio.to_thread(read_docx, data)
    except DocxError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    source = _source_from_form(
        title=title, authors=authors, year=year, journal=journal, doi=doi, url=url
    )
    summary = await _summarize(
        document,
        source,
        settings,
        max(0, min(quote_count, 6)),
        detail=detail,
        mode=mode,
    )
    summary.took_ms = int((time.perf_counter() - start) * 1000)
    return summary


@router.get("/doi", response_model=DoiLookup)
async def lookup_doi(
    doi: str = Query(..., min_length=4, max_length=300),
    settings: Settings = Depends(get_settings),
) -> DoiLookup:
    """Resolve a DOI through OpenAlex so the metadata form can be filled in."""
    normalized = normalize_doi(doi)
    if not normalized or not _DOI_RE.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a DOI such as 10.1234/abcd.5678.",
        )

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        try:
            record = await openalex.get_work(client, settings=settings, doi=normalized)
        except ProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=exc.friendly(),
            ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No OpenAlex record was found for that DOI. Check the DOI, "
                "or fill in the details by hand."
            ),
        )

    return DoiLookup(
        title=record.title or "",
        authors=list(record.authors or []),
        year=record.year,
        journal=record.journal,
        doi=normalize_doi(record.doi) or normalized,
        url=record.url,
    )


@router.post("/export/docx")
async def export_summary_docx(request: SummaryOut) -> Response:
    """Download a generated summary as an editable Word document."""
    from .services.export import summary_docx

    try:
        content = await asyncio.to_thread(summary_docx, request.model_dump())
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DOCX export is not available on this server (missing python-docx).",
        ) from exc

    filename = f"scholaris-summary-{date.today().isoformat()}.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
