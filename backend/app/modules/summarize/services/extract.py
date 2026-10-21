"""
Turn pasted text or a PDF into clean sentences that keep their page numbers.

The rest of Module 2 only works with `Document`, so the summary generator and
the quote finder never need to know whether the words came from a textarea or
from page 4 of a PDF.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

# Guard rails so a huge PDF cannot make a request slow or fill the RAM.
MAX_PDF_PAGES = 60
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 120_000
MIN_PDF_TEXT_CHARS = 40

_WHITESPACE_RE = re.compile(r"[ \t\f\v\u00a0]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“”‘’(])")
_INLINE_CITATION_RE = re.compile(r"\s*\[(?:\d+[\s,;–-]*)+]")
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}
_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "et al.",
    "vs.",
    "cf.",
    "approx.",
    "fig.",
    "figs.",
    "eq.",
    "no.",
    "dr.",
    "prof.",
    "st.",
    "inc.",
    "ltd.",
    "jr.",
    "sr.",
    "etc.",
    "vol.",
)


@dataclass(slots=True)
class Sentence:
    text: str
    page: int | None
    index: int


@dataclass(slots=True)
class Document:
    sentences: list[Sentence]
    text: str
    word_count: int
    kind: str = "text"
    page_count: int | None = None
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def excerpt(self) -> str:
        return excerpt(self.text)


class PdfError(ValueError):
    """A PDF could not be read (encrypted, scanned, not a PDF, ...)."""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    text = text.replace("\u00ad", "").replace("\r\n", "\n").replace("\r", "\n")
    # Re-join words that were hyphenated across a line break.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # A single newline is usually a wrapped line; keep blank lines as breaks.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def clean_text(text: str) -> str:
    """Public helper for already-extracted text."""
    return _normalize(text)


def _is_abbreviation(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(lowered.endswith(abbreviation) for abbreviation in _ABBREVIATIONS)


def split_sentences(text: str) -> list[str]:
    """Split clean prose into sentences without breaking common abbreviations."""
    text = clean_text(text)
    if not text:
        return []

    chunks = [chunk.strip() for chunk in _SENTENCE_SPLIT_RE.split(text) if chunk.strip()]
    sentences: list[str] = []
    for chunk in chunks:
        if sentences and (
            _is_abbreviation(sentences[-1])
            or len(chunk.split()) < 4
            or chunk[0].islower()
        ):
            sentences[-1] = f"{sentences[-1]} {chunk}"
        else:
            sentences.append(chunk)

    # A trailing fragment with no terminal punctuation is still useful.
    return [sentence for sentence in sentences if sentence]


def sentences_from_text(text: str, *, offset: int = 0) -> list[Sentence]:
    return [
        Sentence(text=sentence, page=None, index=offset + position)
        for position, sentence in enumerate(split_sentences(text))
    ]


def document_from_text(text: str) -> Document:
    cleaned = clean_text(text)
    if not cleaned:
        raise ValueError("The text was empty after cleaning. Paste a little more of the source.")
    truncated = len(cleaned) > MAX_TEXT_CHARS
    cleaned = cleaned[:MAX_TEXT_CHARS]
    sentences = sentences_from_text(cleaned)
    if not sentences:
        raise ValueError("No complete sentences were found in the text.")
    return Document(
        sentences=sentences,
        text=cleaned,
        word_count=len(cleaned.split()),
        kind="text",
        truncated=truncated,
        warnings=(
            ["Only the first part of the text was summarized (the limit is 120,000 characters)."]
            if truncated
            else []
        ),
    )


def document_from_pages(pages: list[str], *, kind: str = "pdf") -> Document:
    """Build a document from per-page strings, preserving page numbers."""
    sentences: list[Sentence] = []
    kept_pages: list[str] = []
    total_chars = 0
    truncated = False

    for page_number, raw_page in enumerate(pages, start=1):
        cleaned = clean_text(raw_page)
        if not cleaned:
            continue
        remaining = MAX_TEXT_CHARS - total_chars
        if remaining <= 0:
            truncated = True
            break
        if len(cleaned) > remaining:
            cleaned = cleaned[:remaining]
            truncated = True
        kept_pages.append(cleaned)
        total_chars += len(cleaned)
        offset = len(sentences)
        sentences.extend(
            Sentence(text=sentence, page=page_number, index=offset + position)
            for position, sentence in enumerate(split_sentences(cleaned))
        )

    if not sentences:
        raise PdfError(
            "This PDF has no selectable text. It may be a scan or an image export — "
            "paste the text instead, or run OCR on the file first."
        )

    warnings: list[str] = []
    if truncated:
        warnings.append(
            "Only part of the PDF was summarized (the limit is 120,000 characters)."
        )
    return Document(
        sentences=sentences,
        text=" ".join(kept_pages),
        word_count=sum(len(sentence.text.split()) for sentence in sentences),
        kind=kind,
        page_count=len(pages),
        truncated=truncated,
        warnings=warnings,
    )


def read_pdf(data: bytes) -> Document:
    """Extract text page by page from a PDF using pypdf (lazy import)."""
    if not data:
        raise PdfError("The uploaded file was empty.")
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("That PDF is larger than 15 MB. Try a smaller file or paste the text.")
    if not data.lstrip().startswith(b"%PDF"):
        raise PdfError("That file is not a PDF. Upload a .pdf file or paste the text instead.")

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise PdfError("PDF support is not installed on the server (missing pypdf).") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PdfError("That PDF is password-protected. Export an unlocked copy and try again.")
        pages = [page.extract_text() or "" for page in reader.pages[:MAX_PDF_PAGES]]
    except PdfError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises several different errors
        raise PdfError("That PDF could not be read. It may be damaged or use an unsupported format.") from exc

    if len(reader.pages) > MAX_PDF_PAGES:
        document = document_from_pages(pages)
        document.page_count = len(reader.pages)
        document.warnings.append(
            f"Only the first {MAX_PDF_PAGES} pages were read (the PDF has {len(reader.pages)})."
        )
        document.truncated = True
        return document

    if sum(len(page.strip()) for page in pages) < MIN_PDF_TEXT_CHARS:
        raise PdfError(
            "This PDF has almost no selectable text. It may be a scan — paste the text instead, "
            "or run OCR on the file first."
        )
    return document_from_pages(pages)


def excerpt(text: str, limit: int = 700) -> str:
    cleaned = remove_citations(clean_text(text))
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    tail = cut[limit // 2 :]
    if "." in tail:
        cut = cut[: limit // 2 + tail.rfind(".") + 1]
    return cut.rstrip() + " …"


def remove_citations(text: str) -> str:
    """Drop bracketed numeric citations for summary bullets (quotes keep them)."""
    return _INLINE_CITATION_RE.sub("", text).strip()
