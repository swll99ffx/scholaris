"""
Offline unit tests for Module 1 (no network calls, no API keys needed).

Run from the backend/ folder:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import hashlib
import unittest
from unittest.mock import patch

from app.config import Settings
from app.modules.research.models import SourceRecord
from app.modules.research.schemas import SearchFilters, SearchRequest, SourceOut
from app.modules.research.services import doaj, europepmc, library
from app.modules.research.services.authors import (
    AuthorCheck,
    AuthorName,
    merge_author_details,
    parse_flat_name,
    validate_author_names,
)
from app.modules.research.services.citations import (
    format_citations,
    initials,
    split_name,
)
from app.modules.research.services.concepts import build_concept_plan
from app.modules.research.services.interpret import (
    extract_keywords,
    interpret_topic,
    is_long_input,
)
from app.modules.research.services.language import is_english
from app.modules.research.services.merge import merge_records
from app.modules.research.services.ranking import (
    apply_filters,
    credibility_checklist,
    idf_weights,
    is_administrative,
    is_non_primary_report,
    is_preprint,
    rank_feed,
    rank_records,
    relevance_score,
    same_story,
    scope_score,
)
from app.modules.research.services.notes import generate_notes
from app.modules.research.services.search import _gather
from app.modules.research.services.text import (
    normalize_doi,
    normalize_title,
    reconstruct_abstract,
    split_page_metadata,
)

# Interpretation tests must never touch the network.
OFFLINE_SETTINGS = Settings(interpret_topic_with_llm=False, llm_keyless_fallback=False)

MONERA_BRIEF = """ctivity 5 in Biology 4
Title: Taxonomic Classification of Kingdom Monera Samples Using Binomial Nomenclature
Objectives:
1. Determine the common and scientific names of different representatives of Kingdom Monera using binomial nomenclature;
2. Examine their differences and similarities using their anatomical and physiological characteristics.
Background Information:
(Provide your own background information based on your own understanding and knowledge.)
Materials:
10 areas in the school where Monera species could live
Procedure:
1. Collect 10 or more pictures of your monera specimens from internet.
References: (All references used in naming and classifying the Monera species)
"""


def sample_record(**overrides) -> SourceRecord:
    base = dict(
        title="Attention, Joint Attention, and Social Cognition",
        authors=["Peter Clive Mundy", "Lisa C. Newell"],
        year=2007,
        journal="Current Directions in Psychological Science",
        abstract="This review discusses joint attention and social cognition.",
        url="https://doi.org/10.1111/j.1467-8721.2007.00518.x",
        doi="10.1111/j.1467-8721.2007.00518.x",
        citation_count=899,
        is_open_access=True,
        is_review=True,
        work_type="review",
        volume="16",
        issue="5",
        pages="269-274",
        publisher="SAGE Publishing",
        subjects=["Psychology", "Cognition"],
        providers=["openalex"],
        provider_ids={"openalex": "W2144576651"},
    )
    base.update(overrides)
    return SourceRecord(**base)


class TextHelpersTest(unittest.TestCase):
    def test_normalize_doi_strips_prefixes(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1/ABC"), "10.1/abc")
        self.assertEqual(normalize_doi("doi:10.2/XYZ"), "10.2/xyz")
        self.assertIsNone(normalize_doi(""))

    def test_normalize_title_ignores_articles_and_punctuation(self):
        self.assertEqual(normalize_title("The Role of AI!"), "role of ai")
        self.assertEqual(normalize_title("The role of  AI"), "role of ai")

    def test_reconstruct_abstract_orders_words(self):
        inverted = {"world": [1], "Hello": [0], "!": [2]}
        self.assertEqual(reconstruct_abstract(inverted), "Hello world !")
        self.assertEqual(reconstruct_abstract(None), "")


class NameHelpersTest(unittest.TestCase):
    def test_split_name(self):
        self.assertEqual(split_name("Peter Clive Mundy"), ("Mundy", "Peter Clive"))
        self.assertEqual(split_name("Mundy, Peter Clive"), ("Mundy", "Peter Clive"))
        self.assertEqual(split_name("Aristotle"), ("Aristotle", ""))

    def test_initials_handles_hyphenated_names(self):
        self.assertEqual(initials("Jean-Luc Marie"), "J.-L. M.")
        self.assertEqual(initials(""), "")

    def test_flat_names_keep_particles_and_suffixes(self):
        beethoven = parse_flat_name("Ludwig van Beethoven")
        self.assertEqual((beethoven.family, beethoven.given), ("van Beethoven", "Ludwig"))

        cruz = parse_flat_name("Maria de la Cruz")
        self.assertEqual((cruz.family, cruz.given), ("de la Cruz", "Maria"))

        suffix = parse_flat_name("John Smith Jr.")
        self.assertEqual((suffix.family, suffix.given, suffix.suffix), ("Smith", "John", "Jr."))

        initials_first = parse_flat_name("Smith J. A.")
        self.assertEqual((initials_first.family, initials_first.given), ("Smith", "J. A."))

        accents = parse_flat_name("José García-López")
        self.assertEqual(
            (accents.family, accents.given),
            ("García-López", "José"),
        )

        given_first_suffix = parse_flat_name("John Smith, Jr.")
        self.assertEqual(
            (given_first_suffix.family, given_first_suffix.given, given_first_suffix.suffix),
            ("Smith", "John", "Jr."),
        )

        degree = parse_flat_name("Jane Doe, PhD")
        self.assertEqual((degree.family, degree.given, degree.suffix), ("Doe", "Jane", ""))

        honorific = parse_flat_name("Dr. John Smith")
        self.assertEqual((honorific.family, honorific.given), ("Smith", "John"))

    def test_corporate_authors_are_not_split_into_people(self):
        organization = parse_flat_name("World Health Organization")
        self.assertEqual(organization.literal, "World Health Organization")
        self.assertEqual(organization.family, "")

        acronym = parse_flat_name("WHO")
        self.assertEqual(acronym.literal, "WHO")
        self.assertEqual(validate_author_names([acronym]).status, "ok")

    def test_uppercase_initials_are_rejected_as_a_surname(self):
        bad = parse_flat_name("JA")
        self.assertEqual(bad.family, "JA")
        check = validate_author_names([bad])
        self.assertEqual(check.status, "needs_checking")
        self.assertIn("initials", check.reason)

        record = sample_record(authors=["JA"], author_details=[bad])
        styles = format_citations(record)
        for text in styles.values():
            self.assertTrue(text.startswith("[NEEDS CHECKING: author names] "))

        non_latin = AuthorName(family="李", given="伟")
        self.assertEqual(validate_author_names([non_latin]).status, "ok")

    def test_structured_names_win_over_a_flat_display_string(self):
        record = sample_record(
            authors=["Wrong, Person"],
            author_details=[AuthorName(family="Mundy", given="Peter Clive")],
        )
        styles = format_citations(record)
        self.assertTrue(styles["apa"].startswith("Mundy, P. C. (2007)."))
        self.assertNotIn("Wrong", styles["apa"])

    def test_cross_provider_disagreement_marks_every_citation(self):
        crossref = sample_record(
            authors=["John Smith"],
            providers=["crossref"],
            provider_ids={"crossref": "10.1/x"},
            author_details=[AuthorName(family="Smith", given="John", source="crossref")],
        )
        openalex = sample_record(
            authors=["Jane Smith"],
            providers=["openalex"],
            provider_ids={"openalex": "W1"},
            author_details=[AuthorName(family="Smith", given="Jane", source="openalex")],
        )
        merged = merge_records([crossref, openalex])[0]
        self.assertEqual(merged.author_check.status, "needs_checking")
        self.assertIn("disagree", merged.author_check.reason)
        styles = format_citations(merged)
        for text in styles.values():
            self.assertTrue(text.startswith("[NEEDS CHECKING: author names] "))

    def test_initial_variants_agree_and_keep_orcid(self):
        merged, check = merge_author_details(
            [AuthorName(family="Smith", given="John", source="crossref")],
            [
                AuthorName(
                    family="Smith",
                    given="J",
                    orcid="0000-0002-1825-0097",
                    source="openalex",
                )
            ],
        )
        self.assertEqual(check.status, "ok")
        self.assertEqual(merged[0].orcid, "0000-0002-1825-0097")

    def test_unicode_dashes_and_particles_do_not_create_false_conflicts(self):
        hyphenated, hyphen_check = merge_author_details(
            [parse_flat_name("Hans\u2010Peter Klenk", source="openalex")],
            [AuthorName(family="Klenk", given="Hans-Peter", source="pubmed")],
        )
        self.assertEqual(hyphen_check.status, "ok")
        self.assertEqual(hyphenated[0].family, "Klenk")

        particles, particle_check = merge_author_details(
            [parse_flat_name("Maria Asuncion de los Rios", source="openalex")],
            [
                AuthorName(
                    family="de Los Rios",
                    given="Maria Asuncion",
                    source="pubmed",
                )
            ],
        )
        self.assertEqual(particle_check.status, "ok")
        self.assertEqual((particles[0].family, particles[0].given), ("de los Rios", "Maria Asuncion"))

        compound, compound_check = merge_author_details(
            [
                AuthorName(
                    family="los Santos",
                    given="Paulina Estrada-de",
                    source="openalex",
                )
            ],
            [
                AuthorName(
                    family="Estrada-de Los Santos",
                    given="Paulina",
                    source="pubmed",
                )
            ],
        )
        self.assertEqual(compound_check.status, "ok")
        self.assertEqual(compound[0].family, "los Santos")

        _, dotless_check = merge_author_details(
            [AuthorName(family="Parro", given="V\u0131\u0301ctor", source="openalex")],
            [AuthorName(family="Parro", given="Victor", source="pubmed")],
        )
        self.assertEqual(dotless_check.status, "ok")

        _, real_conflict = merge_author_details(
            [AuthorName(family="Wang", given="Fengping", source="openalex")],
            [AuthorName(family="Wang", given="Feng-Ping", source="crossref")],
        )
        self.assertEqual(real_conflict.status, "needs_checking")
        self.assertIn("Fengping", real_conflict.reason)

        existing_conflict = "#1: Jane Smith vs John Smith."
        merged_again, duplicate_check = merge_author_details(
            [AuthorName(family="Smith", given="John")],
            [AuthorName(family="Smith", given="Jane")],
            first_check=AuthorCheck(
                status="needs_checking",
                reason=f"Author names disagree between providers: {existing_conflict}",
                conflicts=[existing_conflict],
            ),
        )
        self.assertEqual(len(merged_again), 1)
        self.assertEqual(duplicate_check.conflicts, [existing_conflict])
        self.assertEqual(duplicate_check.reason.count("Author names disagree"), 1)

    def test_author_check_serializes_with_source_out(self):
        record = sample_record(
            author_details=[AuthorName(family="Mundy", given="Peter Clive")],
            author_check=AuthorCheck(
                status="needs_checking",
                reason="Provider records disagree.",
                conflicts=["#1: Mundy vs Munday."],
            ),
        )
        payload = SourceOut(
            id="doi:10.1/x",
            title=record.title,
            authors=record.authors,
            author_details=[
                {
                    "family": author.family,
                    "given": author.given,
                    "literal": author.literal,
                    "suffix": author.suffix,
                    "orcid": author.orcid,
                    "source": author.source,
                }
                for author in record.author_details
            ],
            author_check={
                "status": record.author_check.status,
                "reason": record.author_check.reason,
                "conflicts": record.author_check.conflicts,
            },
        )
        self.assertEqual(payload.author_details[0].family, "Mundy")
        self.assertEqual(payload.author_check.status, "needs_checking")


class CitationsTest(unittest.TestCase):
    def setUp(self):
        self.styles = format_citations(sample_record())

    def test_apa(self):
        expected = (
            "Mundy, P. C., & Newell, L. C. (2007). Attention, Joint Attention, and "
            "Social Cognition. Current Directions in Psychological Science, 16(5), "
            "269–274. https://doi.org/10.1111/j.1467-8721.2007.00518.x"
        )
        self.assertEqual(self.styles["apa"], expected)

    def test_mla(self):
        self.assertIn('Mundy, Peter Clive, and Lisa C. Newell. "Attention', self.styles["mla"])
        self.assertIn("vol. 16, no. 5, 2007, pp. 269–274", self.styles["mla"])

    def test_chicago(self):
        self.assertIn("Current Directions in Psychological Science 16, no. 5 (2007): 269–274", self.styles["chicago"])
        self.assertIn("https://doi.org/", self.styles["chicago"])

    def test_missing_year_uses_nd(self):
        styles = format_citations(sample_record(year=None))
        self.assertIn("(n.d.)", styles["apa"])

    def test_apa_uses_article_number_when_there_are_no_pages(self):
        styles = format_citations(sample_record(pages=None, article_number="e12345"))
        self.assertIn("16(5), Article e12345.", styles["apa"])

    def test_apa_prefers_a_page_range_over_an_article_number(self):
        styles = format_citations(
            sample_record(pages="269-274", article_number="e12345")
        )
        self.assertIn("16(5), 269–274.", styles["apa"])
        self.assertNotIn("Article e12345", styles["apa"])

    def test_page_metadata_separates_article_numbers(self):
        self.assertEqual(split_page_metadata("e12345"), (None, "e12345"))
        self.assertEqual(split_page_metadata("Article 12345"), (None, "12345"))
        self.assertEqual(split_page_metadata("269-274"), ("269-274", None))
        self.assertEqual(split_page_metadata("42"), ("42", None))
        self.assertEqual(split_page_metadata(None, "e999"), (None, "e999"))


class MergeTest(unittest.TestCase):
    def test_merge_by_doi_keeps_best_fields(self):
        a = sample_record(
            providers=["openalex"],
            provider_ids={"openalex": "W1"},
            abstract="short",
            citation_count=10,
        )
        b = sample_record(
            providers=["pubmed"],
            provider_ids={"pubmed": "123"},
            abstract="a much longer and more detailed abstract than before",
            citation_count=899,
            journal="Current Directions in Psychological Science",
        )
        merged = merge_records([a, b])
        self.assertEqual(len(merged), 1)
        self.assertCountEqual(merged[0].providers, ["openalex", "pubmed"])
        self.assertEqual(merged[0].citation_count, 899)
        self.assertEqual(merged[0].abstract, b.abstract)

    def test_merge_clears_the_article_number_from_the_page_field(self):
        first = SourceRecord(
            title="A study of article numbering",
            year=2024,
            pages="e12345",
            providers=["openalex"],
        )
        second = SourceRecord(
            title="A study of article numbering",
            year=2024,
            article_number="e12345",
            providers=["crossref"],
        )
        merged = merge_records([first, second])[0]
        self.assertIsNone(merged.pages)
        self.assertEqual(merged.article_number, "e12345")

    def test_merge_by_fuzzy_title_without_doi(self):
        a = sample_record(title="Deep learning for cancer detection", doi=None)
        b = sample_record(title="Deep Learning for Cancer Detection!", doi=None)
        merged = merge_records([a, b])
        self.assertEqual(len(merged), 1)

    def test_different_dois_are_not_merged(self):
        a = sample_record(doi="10.1/a")
        b = sample_record(doi="10.1/b")
        merged = merge_records([a, b])
        self.assertEqual(len(merged), 2)


class RankingTest(unittest.TestCase):
    def test_ranking_prefers_relevant_review(self):
        query = "joint attention social cognition"
        relevant = sample_record(score=0, is_review=True, citation_count=899)
        irrelevant = SourceRecord(
            title="Thermodynamics of diesel engines",
            abstract="Combustion and efficiency.",
            year=2005,
            citation_count=500,
            providers=["openalex"],
        )
        ranked = rank_records(query, [irrelevant, relevant])
        # The precision gate drops a paper that shares no distinctive word with
        # the query, even though it is highly cited.
        self.assertNotIn(irrelevant, ranked)
        self.assertIs(ranked[0], relevant)
        self.assertTrue(ranked[0].reason)
        self.assertIn("attention", ranked[0].matched_terms)

    def test_filters_reviews_only(self):
        review = sample_record(is_review=True)
        article = sample_record(is_review=False, doi="10.1/other", title="Other work")
        filters = SearchFilters(reviews_only=True)
        self.assertEqual(apply_filters([review, article], filters), [review])

    def test_subject_filter(self):
        bio = sample_record(title="Cellular respiration in yeast", subjects=["Biology"])
        maths = sample_record(
            title="Prime number theorems",
            subjects=["Mathematics"],
            doi="10.1/m",
        )
        filters = SearchFilters(subject="math")
        self.assertEqual(apply_filters([bio, maths], filters), [maths])


class CredibilityTest(unittest.TestCase):
    def test_well_cited_review_scores_well(self):
        items = {item.label: item for item in credibility_checklist(sample_record())}
        self.assertEqual(items["Peer reviewed"].status, "good")
        self.assertEqual(items["Citation impact"].status, "good")
        self.assertEqual(items["Reputable journal"].status, "good")

    def test_preprint_is_flagged(self):
        preprint = sample_record(journal="arXiv", work_type="preprint", providers=["openalex"])
        items = {item.label: item for item in credibility_checklist(preprint)}
        self.assertEqual(items["Peer reviewed"].status, "warn")


class ExportTest(unittest.TestCase):
    def test_bibtex_contains_entry_and_escapes(self):
        item = sample_record().to_debug_dict()
        entry = {
            "id": "doi:10.1/x",
            "title": "Power & Politics",
            "authors": ["Peter Clive Mundy"],
            "year": 2007,
            "journal": "Journal of Testing",
            "citation_styles": format_citations(sample_record()),
        }
        bibtex = library.export_bibtex([entry])
        self.assertIn("@article", bibtex)
        self.assertIn("mundy2007power", bibtex)
        self.assertIn(r"Power \& Politics", bibtex)

    def test_bibtex_uses_structured_authors_and_marks_uncertain_names(self):
        entry = {
            "id": "doi:10.1/x",
            "title": "A Paper",
            "authors": ["Wrong Flat Name"],
            "author_details": [
                {
                    "family": "Mundy",
                    "given": "Peter Clive",
                    "literal": "",
                    "suffix": "",
                    "orcid": None,
                    "source": "crossref",
                }
            ],
            "author_check": {
                "status": "needs_checking",
                "reason": "Provider records disagree.",
                "conflicts": ["#1: Mundy vs Munday."],
            },
            "year": 2007,
            "journal": "Journal of Testing",
            "citation_styles": format_citations(sample_record()),
        }
        bibtex = library.export_bibtex([entry])
        self.assertIn("Mundy, Peter Clive", bibtex)
        self.assertNotIn("Wrong Flat Name", bibtex)
        self.assertIn("NEEDS CHECKING: author names", bibtex)

    def test_bibtex_uses_eid_for_an_article_number(self):
        entry = {
            "id": "doi:10.1/x",
            "title": "Article numbering",
            "authors": ["Jane Doe"],
            "year": 2024,
            "journal": "Journal of Testing",
            "volume": "12",
            "issue": "3",
            "article_number": "e12345",
        }
        bibtex = library.export_bibtex([entry])
        self.assertIn("eid = {e12345}", bibtex)

    def test_csv_export_contains_metadata_and_apa(self):
        item = {
            "title": "Prokaryotic taxonomy",
            "authors": ["Jane Doe", "John Roe"],
            "year": 2021,
            "journal": "Journal of Testing",
            "doi": "10.1/x",
            "citation_styles": {"apa": "Doe, J. (2021). Prokaryotic taxonomy."},
        }
        text = library.export_csv([item])
        self.assertIn("Title,Authors,Year", text)
        self.assertIn("Prokaryotic taxonomy", text)
        self.assertIn("Doe, J. (2021)", text)

    def test_txt_export_lists_apa(self):
        item = {
            "title": "Something",
            "citation_styles": {"apa": "APA citation text."},
        }
        text = library.export_txt([item])
        self.assertIn("APA citation text.", text)
        self.assertIn("Scholaris", text)


class InterpretTest(unittest.TestCase):
    def test_short_question_is_reduced_to_keywords_offline(self):
        # Even with no AI, the question words are stripped so the search finds
        # papers about the topic instead of papers containing "feel/we/when".
        topic = "why do we feel sleepy when it's hot"
        result = asyncio.run(interpret_topic(topic, OFFLINE_SETTINGS))
        self.assertEqual(result.mode, "keywords")
        self.assertIn("sleepy", result.topic)
        self.assertIn("hot", result.topic)
        self.assertNotIn("why", result.topic)
        self.assertFalse(result.is_long_paste)

    def test_two_word_topic_is_left_alone(self):
        result = asyncio.run(interpret_topic("quantum entanglement", OFFLINE_SETTINGS))
        self.assertEqual(result.mode, "direct")
        self.assertEqual(result.topic, "quantum entanglement")

    def test_long_assignment_uses_the_title_line(self):
        result = asyncio.run(interpret_topic(MONERA_BRIEF, OFFLINE_SETTINGS))
        self.assertEqual(result.mode, "title")
        self.assertIn("Kingdom Monera", result.topic)
        self.assertIn("Binomial Nomenclature", result.topic)
        # The boilerplate must not leak into the search topic.
        self.assertNotIn("Objectives", result.topic)

    def test_long_input_without_title_picks_first_content_line(self):
        brief = "Activity 1 in Science\nObjectives:\nExplain photosynthesis in plants\nProcedure:\nDo the thing"
        result = asyncio.run(interpret_topic(brief, OFFLINE_SETTINGS))
        self.assertTrue(result.is_long_paste)
        self.assertIn("photosynthesis", result.topic.lower())

    def test_is_long_input_detection(self):
        self.assertFalse(is_long_input("sleep and memory"))
        self.assertTrue(is_long_input(MONERA_BRIEF))

    def test_keywords_drop_assignment_boilerplate(self):
        keywords = extract_keywords("Title Objectives Procedure materials Monera binomial")
        self.assertIn("monera", keywords)
        self.assertIn("binomial", keywords)
        self.assertNotIn("objectives", keywords)
        self.assertNotIn("procedure", keywords)


class ConceptExpansionTest(unittest.TestCase):
    def test_monera_title_expands_history_and_modern_replacement(self):
        result = asyncio.run(interpret_topic(MONERA_BRIEF, OFFLINE_SETTINGS))
        labels = [concept.label for concept in result.plan.concepts]
        self.assertIn("Kingdom Monera", labels)
        self.assertIn("Binomial nomenclature", labels)

        monera = next(c for c in result.plan.concepts if c.label == "Kingdom Monera")
        self.assertTrue(monera.obsolete)
        self.assertTrue(monera.primary)
        self.assertIn("Whittaker", monera.historical or "")
        self.assertIn("Bacteria", monera.current)
        self.assertIn("prokaryote", monera.alternate_names)

        kinds = {query.kind for query in result.plan.queries}
        self.assertIn("modern", kinds)
        self.assertIn("historical", kinds)
        self.assertIn("relationship", kinds)

        modern = next(q for q in result.plan.queries if q.kind == "modern")
        historical = next(q for q in result.plan.queries if q.kind == "historical")
        self.assertIn("bacteria", modern.query.lower())
        self.assertIn("monera", historical.query.lower())

    def test_llm_concepts_are_used_and_validated(self):
        plan = build_concept_plan(
            "photosynthesis",
            ["photosynthesis"],
            llm_concepts=[
                {
                    "label": "Photosynthesis",
                    "historical": "The process was described as the reverse of respiration.",
                    "current": "Light-driven carbon fixation in chloroplasts and cyanobacteria.",
                    "alternate_names": ["carbon fixation", "photosynthetic"],
                    "obsolete": False,
                }
            ],
            max_queries=3,
        )
        self.assertEqual(plan.concepts[0].label, "Photosynthesis")
        self.assertEqual(plan.concepts[0].source, "llm")
        self.assertIn("carbon fixation", plan.concepts[0].alternate_names)
        self.assertLessEqual(len(plan.queries), 3)

    def test_query_budget_is_enforced(self):
        plan = build_concept_plan("kingdom monera binomial nomenclature", max_queries=2)
        self.assertLessEqual(len(plan.queries), 2)
        self.assertEqual(plan.queries[0].kind, "modern")

    def test_unknown_topic_falls_back_to_a_concept(self):
        plan = build_concept_plan("quantum entanglement")
        self.assertEqual(len(plan.concepts), 1)
        self.assertEqual(plan.concepts[0].label, "quantum entanglement")
        self.assertEqual(plan.concepts[0].source, "heuristic")

    def test_casual_sleep_question_gets_a_real_concept(self):
        plan = build_concept_plan("sleepy hot")
        self.assertEqual(plan.concepts[0].label, "Sleep and ambient temperature")
        self.assertIn("thermoregulation", plan.concepts[0].alternate_names)
        self.assertIn("temperature", plan.queries[0].query.lower())


class ConceptRankingTest(unittest.TestCase):
    def test_subject_only_match_is_not_core(self):
        plan = build_concept_plan("kingdom monera")
        record = SourceRecord(
            title="Parents' Sociodemographic Characteristics and Childhood Vaccination",
            abstract="We studied sociodemographic characteristics and vaccine uptake.",
            subjects=["Monera", "Biology"],
            year=2019,
            citation_count=500,
            providers=["crossref"],
        )
        self.assertEqual(rank_records("kingdom monera", [record], plan=plan), [])

    def test_casual_sleep_question_rejects_incidental_words(self):
        plan = build_concept_plan("sleepy hot")
        junk = SourceRecord(
            title="Class Big, Room Hot, Students Sleepy? HAVE A DEBATE!",
            abstract="A classroom debate activity.",
            year=1979,
            providers=["crossref"],
        )
        relevant = SourceRecord(
            title="Relationship between oral temperature and sleepiness among night workers in a hot industry",
            abstract="We measured sleepiness and body temperature across shifts.",
            year=2015,
            citation_count=40,
            providers=["europepmc"],
        )
        ranked = rank_records("sleepy hot", [junk, relevant], plan=plan)
        self.assertEqual(ranked, [relevant])

    def test_generic_nomenclature_does_not_pass_the_monera_gate(self):
        plan = build_concept_plan("kingdom monera")
        record = SourceRecord(
            title="Nomenclature rules for biology",
            abstract="A guide to kingdom nomenclature and classification.",
            year=2022,
            citation_count=100,
            providers=["crossref"],
        )
        self.assertEqual(rank_records("kingdom monera", [record], plan=plan), [])

    def test_history_slot_is_reserved_for_an_obsolete_primary(self):
        plan = build_concept_plan("kingdom monera classification")
        modern_one = SourceRecord(
            title="Prokaryotic taxonomy and nomenclature in the age of big sequence data",
            abstract="Modern prokaryote classification.",
            year=2021,
            citation_count=200,
            providers=["openalex"],
        )
        modern_two = SourceRecord(
            title="Genome-based classification of Archaea and Bacteria",
            abstract="Modern archaeal and bacterial taxonomy.",
            year=2020,
            citation_count=150,
            providers=["openalex"],
        )
        historical = SourceRecord(
            title="Five Kingdoms, More or Less: Robert Whittaker and the Broad Classification of Organisms",
            abstract="A history of Whittaker's five-kingdom system.",
            year=2012,
            citation_count=0,
            discovery="Historical term: Kingdom Monera",
            providers=["openalex"],
        )
        ranked = rank_records(
            "kingdom monera classification",
            [modern_one, modern_two, historical],
            limit=2,
            plan=plan,
        )
        self.assertIn(historical, ranked)
        self.assertTrue(any("Historical term" in (item.discovery or "") for item in ranked))

    def test_concept_match_is_not_dropped_by_the_lexical_floor(self):
        plan = build_concept_plan("Taxonomic Classification of Kingdom Monera Samples Using Binomial Nomenclature")
        historical = SourceRecord(
            title="The prokaryote-eukaryote dichotomy: meanings and mythology",
            abstract="Prokaryotes were once called Kingdom Monera.",
            year=2006,
            citation_count=192,
            providers=["openalex"],
        )
        ranked = rank_records(
            "Taxonomic Classification of Kingdom Monera Samples Using Binomial Nomenclature",
            [historical],
            plan=plan,
        )
        self.assertEqual(ranked, [historical])

    def test_incidental_concept_match_is_dropped_for_recent_sources(self):
        plan = build_concept_plan("sleepy hot")
        statistics = SourceRecord(
            title="Annual Heart Disease and Stroke Statistics",
            abstract="The report lists sleepiness as one of many cardiovascular risk factors.",
            year=2024,
            citation_count=5000,
            is_review=True,
            providers=["crossref"],
        )
        ranked = rank_records("sleepy hot", [statistics], plan=plan)
        self.assertEqual(ranked, [])

    def test_related_sources_skip_the_search_gate(self):
        record = SourceRecord(
            title="A completely different title that cites the parent paper",
            abstract="This paper builds on earlier work.",
            year=2024,
            citation_count=10,
            providers=["openalex"],
        )
        parent = "Taxonomic classification of Kingdom Monera samples"
        self.assertEqual(rank_records(parent, [record]), [])
        self.assertEqual(
            rank_records(parent, [record], apply_gate=False),
            [record],
        )

    def test_balanced_mode_accepts_a_secondary_concept(self):
        plan = build_concept_plan("kingdom monera binomial nomenclature")
        record = SourceRecord(
            title="Binomial nomenclature: rules and practice",
            abstract="A guide to scientific naming.",
            year=2022,
            citation_count=20,
            providers=["crossref"],
        )
        self.assertEqual(
            rank_records("kingdom monera binomial nomenclature", [record], plan=plan),
            [],
        )
        self.assertEqual(
            rank_records(
                "kingdom monera binomial nomenclature",
                [record],
                mode="balanced",
                plan=plan,
            ),
            [record],
        )

    def test_administrative_notice_is_downranked_and_capped(self):
        plan = build_concept_plan("kingdom monera classification")
        normal = SourceRecord(
            title="Taxonomic classification of Kingdom Monera",
            abstract="A review of Kingdom Monera classification and prokaryote taxonomy.",
            year=2022,
            citation_count=20,
            is_review=True,
            providers=["openalex"],
        )
        admin_one = SourceRecord(
            title="Ballot Results: Proposal 2024-A on Kingdom Monera nomenclature",
            abstract="Results of the ballot on Kingdom Monera nomenclature.",
            year=2022,
            citation_count=5000,
            providers=["crossref"],
        )
        admin_two = SourceRecord(
            title="Ballot Results: Proposal 2024-B on Kingdom Monera nomenclature",
            abstract="Results of the ballot on Kingdom Monera nomenclature.",
            year=2022,
            citation_count=4000,
            providers=["crossref"],
        )
        ranked = rank_records(
            "kingdom monera classification",
            [admin_one, admin_two, normal],
            plan=plan,
        )
        self.assertIs(ranked[0], normal)
        self.assertLessEqual(sum(record.is_administrative for record in ranked), 1)
        self.assertTrue(is_administrative(admin_one))
        self.assertTrue(
            is_administrative(
                SourceRecord(
                    title="List of Recommended Names: report of the Ad Hoc Committee"
                )
            )
        )

    def test_proposal_and_ballot_are_one_story(self):
        proposal = SourceRecord(
            title="Proposal 2024-A: Amend the nomenclature rule for Kingdom Monera",
            abstract="Proposal text.",
        )
        ballot = SourceRecord(
            title="Ballot Results: Proposal 2024-A",
            abstract="Ballot results.",
        )
        unrelated = SourceRecord(
            title="Prokaryote cell morphology and classification",
            abstract="Cell structure.",
        )
        self.assertTrue(same_story(proposal, ballot))
        self.assertFalse(same_story(proposal, unrelated))

    def test_broad_topic_keeps_distinct_studies(self):
        query = "quantum entanglement"
        plan = build_concept_plan(query)
        records = [
            SourceRecord(
                title="Quantum entanglement in photosynthetic light harvesting",
                abstract="Quantum entanglement between chromophores assists energy transfer.",
                year=2020,
                citation_count=80,
                providers=["openalex"],
            ),
            SourceRecord(
                title="Quantum entanglement and quantum computing",
                abstract="Entanglement is a resource for quantum computation.",
                year=2021,
                citation_count=90,
                providers=["openalex"],
            ),
            SourceRecord(
                title="Quantum entanglement in black holes",
                abstract="Entanglement across a black-hole horizon and the information paradox.",
                year=2019,
                citation_count=70,
                providers=["openalex"],
            ),
        ]
        ranked = rank_records(query, records, plan=plan)
        self.assertEqual(len(ranked), 3)

    def test_duplicate_substory_is_collapsed(self):
        plan = build_concept_plan("kingdom monera classification")
        first = SourceRecord(
            title="Taxonomic classification of Kingdom Monera",
            abstract="A review of Kingdom Monera classification.",
            year=2022,
            citation_count=50,
            providers=["openalex"],
        )
        duplicate = SourceRecord(
            title="Taxonomic classification of Kingdom Monera samples",
            abstract="A review of Kingdom Monera classification.",
            year=2022,
            citation_count=50,
            providers=["openalex"],
        )
        different = SourceRecord(
            title="Prokaryote cell morphology and classification",
            abstract="Prokaryote and bacteria cell structure.",
            year=2020,
            citation_count=50,
            providers=["openalex"],
        )
        ranked = rank_records(
            "kingdom monera classification",
            [first, duplicate, different],
            plan=plan,
        )
        self.assertEqual(len(ranked), 2)
        self.assertIn(first, ranked)
        self.assertIn(different, ranked)
        self.assertNotIn(duplicate, ranked)


class M1RegressionTest(unittest.TestCase):
    """Regression fixtures for the final M1 quality/latency pass."""

    query = "kingdom monera binomial nomenclature"

    def _plan(self):
        return build_concept_plan(self.query)

    def test_candidatus_pair_is_one_substory(self):
        first = SourceRecord(
            title="Uncultivated microbes in need of their own taxonomy",
            abstract=(
                "Uncultivated microbes have no cultured representative. Candidatus "
                "names and GTDB taxonomy are needed to describe prokaryotes."
            ),
            year=2020,
            citation_count=500,
            providers=["openalex"],
        )
        second = SourceRecord(
            title=(
                "Naming the unnamed: over 65,000 Candidatus names for unnamed "
                "Archaea and Bacteria in the Genome Taxonomy Database"
            ),
            abstract=(
                "We propose Candidatus names for unnamed Bacteria and Archaea in "
                "the Genome Taxonomy Database (GTDB)."
            ),
            year=2022,
            citation_count=120,
            providers=["openalex"],
        )
        strong = SourceRecord(
            title="Prokaryotic taxonomy and nomenclature in the age of big sequence data",
            abstract=(
                "A review of prokaryote taxonomy, classification and nomenclature, "
                "including Bacteria and Archaea."
            ),
            year=2021,
            citation_count=800,
            is_review=True,
            providers=["openalex"],
        )
        ranked = rank_records(self.query, [first, second, strong], limit=2, plan=self._plan())
        self.assertIn(strong, ranked)
        self.assertFalse(first in ranked and second in ranked)
        self.assertEqual(len(ranked), 2)

    def test_monera_top_six_are_broad_and_on_topic(self):
        strong = [
            SourceRecord(
                title="Prokaryotic taxonomy and nomenclature in the age of big sequence data",
                abstract="A review of prokaryote taxonomy, classification and nomenclature.",
                year=2021,
                citation_count=206,
                is_review=True,
                providers=["openalex"],
            ),
            SourceRecord(
                title="Towards a natural system of organisms: proposal for the domains Archaea, Bacteria, and Eucarya",
                abstract="A foundational proposal for the domains of life, including Bacteria and Archaea.",
                year=1990,
                citation_count=10000,
                providers=["openalex"],
            ),
            SourceRecord(
                title="On monospecific genera in prokaryotic taxonomy",
                abstract="A taxonomic discussion of prokaryote genera and classification.",
                year=2020,
                citation_count=100,
                providers=["openalex"],
            ),
            SourceRecord(
                title="Five Kingdoms, More or Less: Robert Whittaker and the Broad Classification of Organisms",
                abstract="A history of Whittaker's five-kingdom system and Kingdom Monera.",
                year=2012,
                citation_count=50,
                discovery="Historical term: Kingdom Monera",
                providers=["openalex"],
            ),
            SourceRecord(
                title="Bergey's manuals and the classification of prokaryotes",
                abstract="A review of prokaryote classification, Bacteria and Archaea.",
                year=2015,
                citation_count=200,
                is_review=True,
                providers=["openalex"],
            ),
            SourceRecord(
                title="Toward DNA-based taxonomy of prokaryotes and microeukaryotes",
                abstract="A broad discussion of taxonomy and classification of prokaryotes.",
                year=2020,
                citation_count=100,
                providers=["openalex"],
            ),
        ]
        candidatus_one = SourceRecord(
            title="Uncultivated microbes in need of their own taxonomy",
            abstract="Candidatus names and GTDB taxonomy for uncultivated prokaryotes.",
            year=2020,
            citation_count=500,
            providers=["openalex"],
        )
        candidatus_two = SourceRecord(
            title="Naming the unnamed: over 65,000 Candidatus names in the Genome Taxonomy Database",
            abstract="We propose Candidatus names for unnamed Bacteria and Archaea in GTDB.",
            year=2022,
            citation_count=120,
            providers=["openalex"],
        )
        report = SourceRecord(
            title="What's in a name? Fit-for-purpose bacterial nomenclature: meeting report",
            abstract="Report from a meeting on prokaryote nomenclature and taxonomy.",
            year=2025,
            citation_count=20,
            providers=["crossref"],
        )
        clinical = SourceRecord(
            title="Taxonomy and nomenclature of bacteria with clinical and scientific importance",
            abstract="Clinical bacteriology, patients and treatment; prokaryote nomenclature.",
            year=2020,
            citation_count=100,
            providers=["crossref"],
        )
        virus = SourceRecord(
            title="Taxonomy of prokaryotic viruses: update from the ICTV Bacterial and Archaeal Viruses Subcommittee",
            abstract="Viral taxonomy of bacteriophages and prokaryotic viruses.",
            year=2018,
            citation_count=100,
            providers=["crossref"],
        )
        ranked = rank_records(
            self.query,
            [*strong, candidatus_one, candidatus_two, report, clinical, virus],
            limit=6,
            plan=self._plan(),
        )
        self.assertEqual(len(ranked), 6)
        missing = [record.title for record in strong if record not in ranked]
        self.assertTrue(all(record in ranked for record in strong), missing)
        self.assertFalse(report in ranked)
        self.assertFalse(clinical in ranked)
        self.assertFalse(virus in ranked)
        self.assertFalse(candidatus_one in ranked and candidatus_two in ranked)

    def test_meeting_report_is_flagged_and_downranked(self):
        report = SourceRecord(
            title=(
                "What's in a name? Fit-for-purpose bacterial nomenclature: "
                "meeting report"
            ),
            abstract="Report from a meeting on prokaryote nomenclature and taxonomy.",
            year=2025,
            citation_count=20,
            providers=["crossref"],
        )
        strong = SourceRecord(
            title="The species concept for prokaryotes",
            abstract="A review of the prokaryote species concept, taxonomy and classification.",
            year=2001,
            citation_count=1000,
            is_review=True,
            providers=["openalex"],
        )
        ranked = rank_records(
            "kingdom monera classification",
            [report, strong],
            plan=build_concept_plan("kingdom monera classification"),
        )
        self.assertIs(ranked[0], strong)
        self.assertTrue(is_non_primary_report(report))
        self.assertTrue(report.is_non_primary)
        self.assertLess(report.score, strong.score)

    def test_narrow_applied_source_has_lower_scope(self):
        broad = SourceRecord(
            title="Prokaryotic taxonomy and classification",
            abstract="A broad review of prokaryote taxonomy and classification.",
        )
        narrow = SourceRecord(
            title="Phytoplasma taxonomy: nomenclature, classification and identification",
            abstract="Phytoplasma cause plant disease; identification in crops is important.",
        )
        self.assertLess(
            scope_score(narrow, self.query),
            scope_score(broad, self.query),
        )
        virus = SourceRecord(
            title="Viral taxonomy and classification",
            abstract="A broad review of taxonomy and classification of viral agents.",
        )
        self.assertEqual(scope_score(virus, self.query), 0.15)
        self.assertGreater(scope_score(virus, "viral taxonomy"), 0.15)

    def test_retracted_article_is_excluded_in_strict_mode(self):
        retracted = SourceRecord(
            title="Prokaryotic taxonomy and classification",
            abstract="A review of Kingdom Monera, prokaryote taxonomy and classification.",
            year=2020,
            citation_count=500,
            is_retracted=True,
            providers=["openalex"],
        )
        plan = self._plan()
        self.assertEqual(rank_records(self.query, [retracted], plan=plan), [])
        balanced = rank_records(self.query, [retracted], plan=plan, mode="balanced")
        self.assertEqual(balanced, [retracted])
        items = {item.label: item for item in credibility_checklist(retracted)}
        self.assertEqual(items["Retraction status"].status, "warn")

    def test_preprint_filter(self):
        preprint = SourceRecord(
            title="Prokaryotic taxonomy preprint",
            abstract="A preprint about prokaryote taxonomy.",
            journal="bioRxiv",
            work_type="preprint",
        )
        self.assertTrue(is_preprint(preprint))
        self.assertEqual(
            apply_filters([preprint], SearchFilters(exclude_preprints=True)),
            [],
        )
        self.assertEqual(apply_filters([preprint], SearchFilters()), [preprint])

    def test_interpret_skips_llm_for_curated_topic(self):
        class FakeLLM:
            called = False

            def __init__(self, _settings):
                pass

            @property
            def available(self):
                return True

            async def complete(self, **_kwargs):
                FakeLLM.called = True
                return (
                    '{"topic": "quantum entanglement in photosynthesis", '
                    '"keywords": ["quantum", "entanglement"], "concepts": []}'
                )

        settings = Settings(
            interpret_topic_with_llm=True,
            llm_keyless_fallback=False,
        )
        with patch("app.modules.research.services.interpret.LLMClient", FakeLLM):
            curated = asyncio.run(interpret_topic(self.query, settings))
            self.assertFalse(FakeLLM.called)
            self.assertNotEqual(curated.mode, "llm")

            unknown = asyncio.run(
                interpret_topic("quantum entanglement in photosynthesis", settings)
            )
            self.assertTrue(FakeLLM.called)
            self.assertEqual(unknown.mode, "llm")


class AsyncLatencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_slow_provider_is_skipped_without_a_warning(self):
        record = SourceRecord(title="Kingdom Monera", abstract="prokaryotes")

        async def fast(_client, **_kwargs):
            return [record]

        async def slow(_client, **_kwargs):
            await asyncio.sleep(0.3)
            return [record]

        settings = Settings(
            search_provider_timeout_seconds=0.05,
            search_core_timeout_seconds=0.05,
            search_deep_provider_timeout_seconds=0.05,
        )
        records, warnings = await _gather(
            None,  # type: ignore[arg-type] - fake providers do not use the client
            "monera",
            SearchRequest(query="monera"),
            settings,
            5,
            providers=(("Fast", fast), ("Slow", slow)),
        )
        self.assertEqual(records, [record])
        self.assertEqual(warnings, [])

    async def test_generate_notes_works_without_ai(self):
        source = SourceOut(
            id="doi:10.1/x",
            title="Prokaryotic taxonomy and nomenclature",
            abstract="A review of prokaryote taxonomy in Kingdom Monera.",
            year=2021,
            citation_count=100,
            score=80,
        )
        notes = await generate_notes(
            "kingdom monera",
            [source],
            Settings(llm_enrich_notes=False, llm_keyless_fallback=False),
        )
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["id"], source.id)
        self.assertEqual(notes[0]["source"], "heuristic")
        self.assertTrue(notes[0]["note"])


class IdfRankingTest(unittest.TestCase):
    def test_rare_words_get_higher_weight(self):
        common = [
            SourceRecord(title="A river study", abstract="river river", providers=["openalex"]),
            SourceRecord(title="Another river paper", abstract="river", providers=["openalex"]),
            SourceRecord(title="River ecosystems", abstract="river", providers=["openalex"]),
        ]
        weights = idf_weights(common, {"river", "monera"})
        self.assertGreater(weights["monera"], weights["river"])

    def test_common_word_match_does_not_beat_the_real_topic(self):
        query = "why do we feel sleepy when its hot"
        wrong = SourceRecord(
            title="Why do we feel sick when infected",
            abstract="People often feel unwell and we feel tired.",
            year=2020,
            citation_count=800,
            providers=["openalex"],
        )
        right = SourceRecord(
            title="Sleep and thermoregulation in hot environments",
            abstract="Sleepy subjects and drowsiness in hot conditions.",
            year=2020,
            citation_count=4,
            providers=["openalex"],
        )
        ranked = rank_records(query, [wrong, right])
        self.assertIs(ranked[0], right)
        self.assertLess(relevance_score(query, wrong), relevance_score(query, right))


class FeedRankingTest(unittest.TestCase):
    """Progressive results must not disturb the protected first page."""

    def _records(self) -> list[SourceRecord]:
        # Short, non-overlapping suffixes keep these 25 synthetic papers from
        # being collapsed as one repeated story while still matching the query.
        records = []
        for index in range(25):
            suffix = " ".join(
                hashlib.sha1(f"{index}-{offset}".encode()).hexdigest()[:10]
                for offset in range(3)
            )
            records.append(
                SourceRecord(
                    title=f"Sleep heat {suffix}",
                    abstract="",
                    year=2000 + index,
                    citation_count=index,
                    providers=["openalex"],
                )
            )
        return records

    def test_feed_keeps_the_first_page_identical(self):
        query = "sleep heat"
        records = self._records()
        first_page = rank_records(query, records, limit=20, apply_gate=False)
        feed = rank_feed(
            query,
            records,
            page_size=20,
            max_results=25,
            apply_gate=False,
        )
        self.assertEqual(len(first_page), 20)
        self.assertEqual(
            [id(record) for record in feed[:20]],
            [id(record) for record in first_page],
        )
        self.assertEqual(len(feed), 25)
        self.assertEqual(len({id(record) for record in feed}), 25)

    def test_feed_without_extra_capacity_is_the_normal_page(self):
        query = "sleep heat"
        records = self._records()
        page = rank_feed(
            query,
            records,
            page_size=20,
            max_results=20,
            apply_gate=False,
        )
        self.assertEqual(len(page), 20)


class PrecisionRankingTest(unittest.TestCase):
    """The precision-first gate: generic-word matches must not leak through."""

    def _monera_atlas(self):
        return SourceRecord(
            title="ATMK: A Monera Kingdom Atlas for Presenting Cell Morphology",
            abstract="An atlas of Kingdom Monera built for biology teaching.",
            year=2021,
            citation_count=2,
            providers=["openalex"],
        )

    def _vaccination(self):
        # Shares only the generic word "characteristics" with the query.
        return SourceRecord(
            title="Parents' Sociodemographic Characteristics and Childhood Vaccination",
            abstract="We studied sociodemographic characteristics and vaccine uptake.",
            year=2019,
            citation_count=500,
            providers=["crossref"],
        )

    def test_generic_word_match_is_dropped(self):
        query = "kingdom monera characteristics"
        atlas = self._monera_atlas()
        vaccination = self._vaccination()
        ranked = rank_records(query, [vaccination, atlas])
        self.assertNotIn(vaccination, ranked)
        self.assertIs(ranked[0], atlas)
        self.assertIn("monera", atlas.matched_terms)
        self.assertNotIn("characteristics", atlas.matched_terms)

    def test_synonym_counts_as_topic_match(self):
        # The query says "monera" (obsolete); a paper about "prokaryotes" is on
        # topic and must survive the gate via the synonym map.
        query = "kingdom monera"
        prokaryote = SourceRecord(
            title="The prokaryote-eukaryote dichotomy: meanings and mythology",
            abstract="Prokaryotes are the organisms once called Kingdom Monera.",
            year=2006,
            citation_count=192,
            providers=["openalex"],
        )
        off_topic = SourceRecord(
            title="Thermodynamics of diesel engines",
            abstract="Combustion and efficiency.",
            year=2005,
            providers=["openalex"],
        )
        ranked = rank_records(query, [off_topic, prokaryote])
        self.assertNotIn(off_topic, ranked)
        self.assertIn(prokaryote, ranked)
        self.assertIn("monera", prokaryote.matched_terms)

    def test_gate_returns_fewer_instead_of_weaker(self):
        # The old behaviour padded the page with a gated-out paper. The module
        # now returns zero strong sources rather than a famous off-topic one.
        query = "kingdom monera"
        ranked = rank_records(query, [self._vaccination()], plan=build_concept_plan(query))
        self.assertEqual(ranked, [])

    def test_strict_and_balanced_modes_both_return_the_topic(self):
        query = "kingdom monera"
        atlas = self._monera_atlas()
        strict = rank_records(query, [atlas], mode="strict")
        balanced = rank_records(query, [atlas], mode="balanced")
        self.assertIn(atlas, strict)
        self.assertIn(atlas, balanced)


class DoajParsingTest(unittest.TestCase):
    def test_to_record(self):
        item = {
            "id": "abc123",
            "bibjson": {
                "title": "A review of CRISPR in plants",
                "year": "2021",
                "author": [{"name": "Jane Doe"}],
                "journal": {"title": "Plants", "volume": "10", "number": "2", "publisher": "MDPI"},
                "identifier": [{"type": "doi", "id": "10.3390/plants1002"}],
                "link": [{"type": "fulltext", "url": "https://example.org/x.pdf"}],
                "abstract": "A short abstract.",
                "keywords": ["crispr"],
                "subject": [{"term": "Botany"}],
            },
        }
        record = doaj.to_record(item)
        self.assertEqual(record.doi, "10.3390/plants1002")
        self.assertEqual(record.journal, "Plants")
        self.assertEqual(record.year, 2021)
        self.assertTrue(record.is_open_access)
        self.assertTrue(record.is_review)
        self.assertEqual(record.url, "https://example.org/x.pdf")
        self.assertIn("doaj", record.providers)


class EuropePmcParsingTest(unittest.TestCase):
    def test_to_record(self):
        result = {
            "id": "12345",
            "source": "MED",
            "pmid": "12345",
            "doi": "10.1000/xyz",
            "title": "Sleep and memory: a review",
            "authorString": "Smith J, Doe A.",
            "journalInfo": {"volume": "5", "issue": "1", "yearOfPublication": "2019"},
            "pubYear": "2019",
            "abstractText": "An abstract.",
            "citedByCount": "42",
            "isOpenAccess": "Y",
            "pubTypeList": {"pubType": ["Review"]},
            "keywordList": {"keyword": ["sleep"]},
            "pageInfo": "e12345",
        }
        record = europepmc.to_record(result)
        self.assertEqual(record.year, 2019)
        self.assertEqual(record.citation_count, 42)
        self.assertTrue(record.is_open_access)
        self.assertTrue(record.is_review)
        self.assertEqual(record.doi, "10.1000/xyz")
        self.assertEqual(record.article_number, "e12345")
        self.assertIsNone(record.pages)
        self.assertIn("europepmc", record.providers)


class LanguageFilterTest(unittest.TestCase):
    def test_english_codes_are_english(self):
        for code in ("en", "eng", "English", "en-US"):
            self.assertTrue(is_english(SourceRecord(title="A paper", language=code)))

    def test_non_english_code(self):
        self.assertFalse(is_english(SourceRecord(title="A paper", language="id")))

    def test_indonesian_title_without_code_is_caught(self):
        record = SourceRecord(
            title="PENGEMBANGAN APLIKASI SISTEM PEMBELAJARAN DAN TATA NAMA MONERA",
            abstract="Penelitian ini bertujuan untuk mengetahui bagaimana siswa.",
        )
        self.assertFalse(is_english(record))

    def test_plain_english_title_is_unknown_not_false(self):
        # No language metadata and no foreign markers -> keep (unknown).
        self.assertIsNone(is_english(SourceRecord(title="Sleep and thermoregulation")))

    def test_filter_keeps_unknown_and_drops_confident_non_english(self):
        english = SourceRecord(title="Sleep regulation in mammals", providers=["openalex"])
        indonesian = SourceRecord(title="PENGEMBANGAN DAN PENELITIAN MONERA", providers=["crossref"])
        kept = apply_filters([english, indonesian], SearchFilters(english_only=True))
        self.assertEqual(kept, [english])


class LibraryRouteTest(unittest.TestCase):
    """A saved source id is a DOI like `doi:10.1/x`, which contains a slash.

    This used to 404 (uvicorn decodes the encoded slash before routing), so
    delete and update silently failed for every DOI-based source.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path

        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import app

        # sqlite keeps the file handle briefly open on Windows; don't fail cleanup.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            database_path=Path(self._tmp.name) / "lib.sqlite3",
            llm_enrich_notes=False,
            llm_keyless_fallback=False,
        )
        library.init_db(self.settings.database_path)
        app.dependency_overrides[get_settings] = lambda: self.settings
        self.client = TestClient(app)

    def tearDown(self):
        from app.config import get_settings
        from app.main import app

        app.dependency_overrides.pop(get_settings, None)
        self._tmp.cleanup()

    def _save_slash_id(self) -> str:
        payload = {
            "source": {"id": "doi:10.1/x", "title": "A slashy DOI source"},
            "notes": "hello",
            "tags": ["key-source"],
        }
        response = self.client.post("/api/research/library", json=payload)
        self.assertEqual(response.status_code, 201)
        return response.json()["library_id"]

    def test_delete_source_with_slash_in_id(self):
        library_id = self._save_slash_id()
        self.assertIn("/", library_id)
        response = self.client.delete(f"/api/research/library/{library_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/research/library").json()["count"], 0)

    def test_update_source_with_slash_in_id(self):
        library_id = self._save_slash_id()
        response = self.client.patch(
            f"/api/research/library/{library_id}", json={"notes": "updated"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["notes"], "updated")

    def test_export_filename_is_branded_and_dated(self):
        self._save_slash_id()
        response = self.client.get("/api/research/library/export?format=bibtex")
        self.assertEqual(response.status_code, 200)
        disposition = response.headers["content-disposition"]
        self.assertIn("scholaris-rrl-", disposition)
        self.assertIn(".bib", disposition)

    def test_library_export_csv(self):
        self._save_slash_id()
        response = self.client.get("/api/research/library/export?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("A slashy DOI source", response.text)

    def test_results_export_csv(self):
        payload = {
            "format": "csv",
            "sources": [
                {
                    "id": "doi:10.1/x",
                    "title": "Prokaryotic taxonomy",
                    "authors": ["Jane Doe"],
                    "year": 2021,
                    "journal": "Journal of Testing",
                    "citation_styles": {"apa": "Doe, J. (2021). Prokaryotic taxonomy."},
                }
            ],
        }
        response = self.client.post("/api/research/export", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("Prokaryotic taxonomy", response.text)

    def test_notes_endpoint_returns_heuristic_without_ai(self):
        payload = {
            "query": "kingdom monera",
            "sources": [
                {
                    "id": "doi:10.1/x",
                    "title": "Prokaryotic taxonomy",
                    "abstract": "A review of prokaryote taxonomy and Kingdom Monera.",
                    "year": 2021,
                }
            ],
        }
        response = self.client.post("/api/research/notes", json=payload)
        self.assertEqual(response.status_code, 200)
        notes = response.json()["notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["id"], "doi:10.1/x")
        self.assertEqual(notes[0]["source"], "heuristic")


if __name__ == "__main__":
    unittest.main()
