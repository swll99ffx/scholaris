"""HTTP endpoints for Module 1: Research Source Finder."""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import Settings, get_settings

from .schemas import (
    LibraryItem,
    LibraryListResponse,
    LibrarySaveRequest,
    LibraryUpdateRequest,
    NotesRequest,
    NotesResponse,
    RelatedRequest,
    RelatedResponse,
    ResultsExportRequest,
    SearchRequest,
    SearchResponse,
)
from .services import library
from .services.notes import generate_notes
from .services.related import find_related
from .services.search import run_search

router = APIRouter(prefix="/api/research", tags=["research"])

EXPORT_FORMATS = Literal["bibtex", "txt", "docx", "csv"]
EXPORT_META = {
    "bibtex": "application/x-bibtex",
    "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "csv": "text/csv; charset=utf-8",
}
EXPORT_EXTENSION = {"bibtex": "bib", "txt": "txt", "docx": "docx", "csv": "csv"}


def _export_filename(format: str) -> str:
    """e.g. scholaris-rrl-2026-10-19.bib — dated so multiple exports never clash."""
    return f"scholaris-rrl-{date.today().isoformat()}.{EXPORT_EXTENSION[format]}"


def _results_filename(format: str) -> str:
    return f"scholaris-results-{date.today().isoformat()}.{EXPORT_EXTENSION[format]}"


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    start = time.perf_counter()
    data = await run_search(request, settings)
    data["took_ms"] = int((time.perf_counter() - start) * 1000)
    return SearchResponse(**data)


@router.post("/notes", response_model=NotesResponse)
async def notes(
    request: NotesRequest,
    settings: Settings = Depends(get_settings),
) -> NotesResponse:
    """Lazily upgrade the visible cards with AI notes after search returns."""
    items = await generate_notes(request.query, request.sources, settings)
    return NotesResponse(notes=items)  # type: ignore[arg-type]


@router.post("/export")
async def export_results(request: ResultsExportRequest) -> Response:
    """Export the current result set without saving it to the library first."""
    if not request.sources:
        raise HTTPException(status_code=400, detail="There are no results to export.")

    items = [source.model_dump() for source in request.sources]
    if request.format == "bibtex":
        content: str | bytes = library.export_bibtex(items)
    elif request.format == "csv":
        content = library.export_csv(items)
    else:
        content = library.export_txt(items)

    return Response(
        content=content,
        media_type=EXPORT_META[request.format],
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_results_filename(request.format)}"'
            )
        },
    )


@router.post("/related", response_model=RelatedResponse)
async def related(
    request: RelatedRequest,
    settings: Settings = Depends(get_settings),
) -> RelatedResponse:
    start = time.perf_counter()
    data = await find_related(request, settings)
    data["took_ms"] = int((time.perf_counter() - start) * 1000)
    data["cached"] = False
    return RelatedResponse(**data)


@router.get("/library", response_model=LibraryListResponse)
async def get_library(settings: Settings = Depends(get_settings)) -> LibraryListResponse:
    items = await asyncio.to_thread(library.list_sources, settings.database_path)
    return LibraryListResponse(count=len(items), sources=items)  # type: ignore[arg-type]


@router.post("/library", response_model=LibraryItem, status_code=status.HTTP_201_CREATED)
async def save_to_library(
    request: LibrarySaveRequest,
    settings: Settings = Depends(get_settings),
) -> LibraryItem:
    item = await asyncio.to_thread(
        library.save_source,
        settings.database_path,
        request.source.model_dump(),
        request.notes,
        request.tags,
    )
    if not item:
        raise HTTPException(status_code=500, detail="The source could not be saved.")
    return LibraryItem(**item)


@router.patch("/library/{library_id:path}", response_model=LibraryItem)
async def update_library_item(
    library_id: str,
    request: LibraryUpdateRequest,
    settings: Settings = Depends(get_settings),
) -> LibraryItem:
    item = await asyncio.to_thread(
        library.update_source,
        settings.database_path,
        library_id,
        notes=request.notes,
        tags=request.tags,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="That saved source was not found.")
    return LibraryItem(**item)


@router.delete("/library/{library_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_item(
    library_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    deleted = await asyncio.to_thread(library.delete_source, settings.database_path, library_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="That saved source was not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/library/export")
async def export_library(
    format: EXPORT_FORMATS = Query(default="bibtex"),
    settings: Settings = Depends(get_settings),
) -> Response:
    items = await asyncio.to_thread(library.list_sources, settings.database_path)
    if not items:
        raise HTTPException(
            status_code=400,
            detail="Your library is empty. Save at least one source before exporting.",
        )

    if format == "bibtex":
        content: str | bytes = library.export_bibtex(items)
    elif format == "txt":
        content = library.export_txt(items)
    elif format == "csv":
        content = library.export_csv(items)
    else:
        content = library.export_docx(items)

    return Response(
        content=content,
        media_type=EXPORT_META[format],
        headers={"Content-Disposition": f'attachment; filename="{_export_filename(format)}"'},
    )
