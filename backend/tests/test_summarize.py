"""
Offline unit tests for Module 2 (Source Summarizer).

Run from the backend/ folder:  python -m unittest discover -s tests -v
No network, API keys or real PDFs are needed.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path

from app.config import Settings, get_settings
from app.main import app
from app.modules.research.services import library
from app.modules.summarize.services.extract import (
    PdfError,
    document_from_pages,
    document_from_text,
    read_pdf,
    split_sentences,
)
from app.modules.summarize.services.save import save_summary
from app.modules.summarize.services.summarize import (
    _draft_from_llm,
    _extract_json,
    format_notes,
    heuristic_draft,
    summarize_document,
)

OFFLINE_SETTINGS = Settings(summarize_with_llm=False, llm_keyless_fallback=False)

ABSTRACT = """Background: Sleep quality is affected by ambient temperature, but the mechanism is unclear. We conducted a survey of 412 university students during a heatwave. Participants reported sleep duration and room temperature each night for two weeks. Results showed that each 1 degree C increase in bedroom temperature was associated with 7.4 minutes less sleep (p < 0.01). Students without air conditioning were significantly more likely to report poor sleep quality. However, the sample was limited to one university and relied on self-reported data. Future research should use wearable devices. Conclusions: Warmer bedrooms reduce sleep duration, and access to cooling is an important health equity issue."""


def build_summary() -> dict:
    document = document_from_text(ABSTRACT)
    draft = heuristic_draft(document, quote_count=3)
    return {
        "source": {
            "title": "Bedroom temperature and student sleep",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "year": 2025,
            "journal": "Journal of Sleep Studies",
            "doi": "10.1000/sleep.2025.1",
            "url": None,
        },
        "tldr": draft.tldr,
        "key_points": draft.key_points,
        "methods": draft.methods,
        "findings": draft.findings,
        "limitations": draft.limitations,
        "quotes": [
            {
                "text": document.sentences[index].text,
                "page": document.sentences[index].page,
                "note": "",
            }
            for index in draft.quote_indices
        ],
        "excerpt": document.excerpt,
        "ai_source": "heuristic",
    }


class ExtractTests(unittest.TestCase):
    def test_split_keeps_abbreviations_together(self):
        sentences = split_sentences(
            "Smith et al. (2020) studied sleep. They found a small effect. "
            "The result was significant, e.g. p < 0.05."
        )
        self.assertEqual(len(sentences), 3, sentences)
        self.assertTrue(sentences[0].startswith("Smith et al. (2020)"))

    def test_page_numbers_survive(self):
        document = document_from_pages(
            [
                "We used a survey of 412 students. Results showed less sleep.",
                "However, the sample was limited to one university.",
            ]
        )
        self.assertEqual(document.page_count, 2)
        self.assertEqual([sentence.page for sentence in document.sentences], [1, 1, 2])

    def test_pdf_magic_and_blank_pdf_are_rejected(self):
        with self.assertRaises(PdfError):
            read_pdf(b"not really a pdf")

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaises(PdfError) as caught:
            read_pdf(buffer.getvalue())
        self.assertIn("selectable text", str(caught.exception))


class SummaryTests(unittest.TestCase):
    def test_heuristic_has_every_section(self):
        document = document_from_text(ABSTRACT)
        draft = heuristic_draft(document, quote_count=3)

        self.assertTrue(draft.tldr)
        self.assertTrue(draft.key_points)
        self.assertTrue(draft.methods)
        self.assertTrue(draft.findings)
        self.assertTrue(draft.limitations)
        self.assertEqual(len(draft.quote_indices), 3)
        self.assertIn("sample was limited", " ".join(draft.limitations))

    def test_quotes_are_verbatim_and_keep_pages(self):
        document = document_from_pages(
            [
                "We conducted a survey of 412 students during a heatwave. "
                "The method section explains the sampling.",
                "Results showed a 7.4 minute reduction in sleep. "
                "However, the sample was limited to one university.",
            ]
        )
        draft = heuristic_draft(document, quote_count=2)
        self.assertEqual(len(draft.quote_indices), 2)
        for index in draft.quote_indices:
            sentence = next(item for item in document.sentences if item.index == index)
            self.assertIn(sentence.text, [item.text for item in document.sentences])
            self.assertIn(sentence.page, (1, 2))

    def test_offline_summary_never_uses_network(self):
        document = document_from_text(ABSTRACT)
        draft, kind = asyncio.run(
            summarize_document(
                document,
                source_title="Sleep",
                settings=OFFLINE_SETTINGS,
                quote_count=2,
            )
        )
        self.assertEqual(kind, "heuristic")
        self.assertEqual(draft.ai_source, "heuristic")

    def test_llm_quote_numbers_map_to_real_sentences(self):
        document = document_from_text(ABSTRACT)
        answer = """```json
        {
          "tldr": "Warmer bedrooms shortened sleep in a student survey.",
          "key_points": ["Heat harms sleep."],
          "methods": ["Survey of 412 students."],
          "findings": ["Sleep fell by 7.4 minutes per degree."],
          "limitations": ["One university, self-report."],
          "quotes": [4, 99, 4]
        }
        ```"""
        draft = _draft_from_llm(answer, document, quote_count=3)
        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft.ai_source, "llm")
        self.assertEqual(draft.quote_indices, [3])
        self.assertIn("7.4 minutes", document.sentences[3].text)

    def test_extract_json_rejects_prose(self):
        self.assertIsNone(_extract_json("I could not summarize this."))
        self.assertEqual(_extract_json('{"tldr": "ok"}'), {"tldr": "ok"})


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "library.sqlite3"
        library.init_db(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_save_creates_one_library_entry_and_is_idempotent(self):
        summary = build_summary()
        first = save_summary(self.db, summary)
        second = save_summary(self.db, summary)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["library_id"], second["library_id"])

        items = library.list_sources(self.db)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("TL;DR", item["notes"])
        self.assertEqual(item["notes"].count("SUMMARY —"), 1)
        self.assertIn("summary", item["tags"])
        self.assertEqual(item["citation_styles"]["apa"].count("Lovelace"), 1)

    def test_save_appends_to_an_existing_saved_source(self):
        summary = build_summary()
        library.save_source(
            self.db,
            {
                "id": "doi:10.1000/sleep.2025.1",
                "title": summary["source"]["title"],
                "authors": summary["source"]["authors"],
                "year": 2025,
                "journal": summary["source"]["journal"],
                "doi": summary["source"]["doi"],
                "citation_styles": {"apa": "", "mla": "", "chicago": ""},
                "credibility": [],
            },
            notes="My own note.",
            tags=["key-source"],
        )
        result = save_summary(self.db, summary, library_id="doi:10.1000/sleep.2025.1")
        self.assertFalse(result["created"])
        item = library.get_source(self.db, "doi:10.1000/sleep.2025.1")
        assert item is not None
        self.assertTrue(item["notes"].startswith("My own note."))
        self.assertIn("TL;DR", item["notes"])
        self.assertEqual(set(item["tags"]), {"key-source", "summary"})

    def test_missing_library_id_raises(self):
        with self.assertRaises(KeyError):
            save_summary(self.db, build_summary(), library_id="doi:missing")

    def test_format_notes_includes_page_numbers(self):
        summary = build_summary()
        summary["quotes"] = [{"text": "A verbatim quote.", "page": 4, "note": ""}]
        notes = format_notes(summary)
        self.assertIn('"A verbatim quote." (p. 4)', notes)


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "library.sqlite3"
        library.init_db(self.db)
        self.settings = Settings(
            database_path=self.db,
            summarize_with_llm=False,
            llm_keyless_fallback=False,
        )
        app.dependency_overrides[get_settings] = lambda: self.settings
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.temp.cleanup()

    def _summarize(self) -> dict:
        response = self.client.post(
            "/api/summarize/text",
            json={
                "text": ABSTRACT,
                "quote_count": 2,
                "source": {
                    "title": "Bedroom temperature and student sleep",
                    "authors": ["Ada Lovelace"],
                    "year": 2025,
                    "journal": "Journal of Sleep Studies",
                    "doi": "10.1000/sleep.2025.1",
                    "url": None,
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_text_summary_endpoint(self):
        body = self._summarize()
        self.assertEqual(body["ai_source"], "heuristic")
        self.assertTrue(body["tldr"])
        self.assertTrue(body["findings"])
        self.assertEqual(len(body["quotes"]), 2)
        self.assertIn("page", body["quotes"][0])

    def test_short_text_is_rejected(self):
        response = self.client.post(
            "/api/summarize/text",
            json={"text": "Too short to summarize.", "source": {}, "quote_count": 2},
        )
        self.assertEqual(response.status_code, 422)

    def test_save_endpoint_writes_into_library(self):
        summary = self._summarize()
        response = self.client.post("/api/summarize/save", json={"summary": summary})
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertTrue(saved["created"])

        library_response = self.client.get("/api/research/library")
        self.assertEqual(library_response.status_code, 200)
        items = library_response.json()["sources"]
        self.assertEqual(len(items), 1)
        self.assertIn("TL;DR", items[0]["notes"])
        self.assertEqual(items[0]["library_id"], saved["library_id"])

    def test_pdf_upload_rejects_non_pdf(self):
        response = self.client.post(
            "/api/summarize/pdf",
            files={"file": ("paper.pdf", b"hello", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a PDF", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
