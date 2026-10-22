"""Save a generated summary into the personal library (Module 1 storage)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.research.models import SourceRecord
from app.modules.research.services import library
from app.modules.research.services.presenter import source_id, to_out

from .extract import split_sentences
from .summarize import format_notes


def _fallback_title(summary: dict[str, Any]) -> str:
    snippet = summary.get("excerpt") or ""
    first = next(iter(split_sentences(snippet)), "")
    if first:
        title = " ".join(first.split()[:14]).rstrip(",;:")
        return title[:120] or "Untitled source"
    return "Untitled source"


def _append_notes(existing: str, block: str) -> str:
    existing = (existing or "").strip()
    if not existing:
        return block
    if block and block in existing:
        return existing
    return f"{existing}\n\n{block}".strip()


def save_summary(
    path: Path,
    summary: dict[str, Any],
    library_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a library entry whose notes hold the summary."""
    block = format_notes(summary)
    source = summary.get("source") or {}
    # The summarize response stashes the full source text under a short token;
    # consume it so the library can keep the original text for future chat.
    token = str(summary.get("summary_id") or "")

    if library_id:
        current = library.get_source(path, library_id)
        if current is None:
            raise KeyError(library_id)
        full_text = library.take_source_text(path, token)
        notes = _append_notes(current.get("notes", ""), block)
        tags = list(dict.fromkeys([*(current.get("tags") or []), "summary"]))
        updated = library.update_source(path, library_id, notes=notes, tags=tags)
        if full_text:
            library.set_source_text(path, library_id, full_text)
        return {
            "library_id": library_id,
            "title": current.get("title") or _fallback_title(summary),
            "created": False,
            "message": "Summary added to the saved source.",
        }

    record = SourceRecord(
        title=(source.get("title") or "").strip() or _fallback_title(summary),
        authors=source.get("authors") or [],
        year=source.get("year"),
        journal=source.get("journal"),
        abstract=summary.get("excerpt") or "",
        doi=source.get("doi"),
        url=source.get("url"),
    )
    stable_id = source_id(record)
    current = library.get_source(path, stable_id)
    full_text = library.take_source_text(path, token)

    if current is not None:
        notes = _append_notes(current.get("notes", ""), block)
        tags = list(dict.fromkeys([*(current.get("tags") or []), "summary"]))
        library.update_source(path, stable_id, notes=notes, tags=tags)
        if full_text:
            library.set_source_text(path, stable_id, full_text)
        return {
            "library_id": stable_id,
            "title": current.get("title") or record.title,
            "created": False,
            "message": "Summary added to the saved source.",
        }

    payload = to_out(record)
    item = library.save_source(
        path, payload, notes=block, tags=["summary"], full_text=full_text
    )
    if not item:
        raise RuntimeError("The summary could not be saved.")
    return {
        "library_id": stable_id,
        "title": record.title,
        "created": True,
        "message": "Summary saved to your library.",
    }
