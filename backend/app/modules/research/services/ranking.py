"""
Relevance scoring, filtering, credibility checks and "why we picked this".

Score = 50% topical relevance
      + 33% citation impact (log-scaled so one mega-cited paper doesn't win)
      +  7% recency
      +  5% review / textbook bonus
      +  5% foundational-paper bonus

Relevance is a *precision-first gate*, not just a weight:
  * Only the query's distinctive ("core") words decide relevance; generic
    academic words ("characteristics", "development", ...) are capped so a paper
    that merely shares one of them cannot look relevant.
  * When a concept plan is available, a result must match the primary concept in
    its title or abstract, or cover at least two distinct concepts. Subject
    metadata alone is never enough.
  * A result must match at least one core word (or a known synonym, see
    synonyms.py) to be eligible at all — this is what removes off-topic papers.
  * We return fewer results rather than relaxing the floor or padding the list
    with weak, duplicate or administrative matches.

The weights are constants so a student can tune them in one place.
"""

from __future__ import annotations

import math
import re
from datetime import date
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from ..models import SourceRecord
from ..schemas import CredibilityItem, SearchFilters
from .language import is_english
from .synonyms import build_aliases
from .text import normalize_title

if TYPE_CHECKING:
    from .concepts import ConceptPlan

WEIGHT_RELEVANCE = 0.50
WEIGHT_CITATIONS = 0.33
WEIGHT_RECENCY = 0.07
WEIGHT_REVIEW = 0.05
WEIGHT_FOUNDATIONAL = 0.05

# Generic academic words: they appear everywhere, so sharing one with a query
# says almost nothing about the topic. They are capped to a tiny weight.
WEAK_WEIGHT = 0.25
WEAK_WORDS = {
    "characteristic", "characteristics", "feature", "features", "development",
    "developments", "developing", "developed", "based", "issue", "issues",
    "analysis", "analyses", "analyse", "analyze", "study", "studies", "research",
    "researching", "effect", "effects", "effective", "types", "type", "role",
    "roles", "factor", "factors", "impact", "impacts", "method", "methods",
    "methodology", "data", "model", "models", "system", "systems", "approach",
    "approaches", "performance", "evaluation", "evaluate", "assessment",
    "assess", "various", "different", "difference", "differences", "overview",
    "introduction", "application", "applications", "new", "novel", "recent",
    "current", "case", "cases", "example", "examples", "including", "include",
    "associated", "association", "related", "relationship", "level", "levels",
    "group", "groups", "high", "low", "increase", "decrease", "change",
    "changes", "process", "processes", "structure", "structures", "aspect",
    "aspects", "important", "significant", "common", "general", "present",
    "presents", "review", "paper", "article", "towards", "toward", "comparison",
    "comparative", "exploration", "framework", "risk", "challenges", "trends",
}

# Precision-first: drop weak matches entirely. "Strict" for the default UI.
MIN_RELEVANCE_STRICT = 0.30
MIN_RELEVANCE_BALANCED = 0.12
# A concept-plan match is stronger than a single shared word, but it can still
# be incidental (a huge annual statistics report that mentions "sleepiness"
# once). Keep the plan gate, but require a minimal direct lexical overlap unless
# the source is a historical/foundational work the student needs for context.
MIN_PLAN_RELEVANCE_STRICT = 0.13

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "how", "in", "into", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "what", "when", "where",
    "which", "who", "why", "with", "using", "use", "can", "does", "do",
    # Everyday words that flag a "question" but carry little topical meaning.
    # Rare, meaningful words are what the ranking actually rewards (see idf_weights).
    "feel", "feels", "felt", "like", "really", "actually", "some", "any",
    "get", "gets", "got", "make", "makes", "thing", "things", "someone",
    "something", "much", "many", "very", "just", "also", "then", "than",
    # Pronouns: a paper about "we" is not a paper about the student's topic.
    "we", "you", "i", "me", "my", "our", "us", "he", "him", "his", "she",
    "her", "they", "them", "your", "yours", "ours", "it",
}

SUBJECT_KEYWORDS = {
    "math": {
        "math", "mathematics", "mathematical", "algebra", "calculus", "geometry",
        "topology", "trigonometry", "statistics", "probability", "theorem",
        "equation", "function", "functions", "derivative", "integral", "limits",
        "combinatorics", "differential", "linear algebra", "number theory",
        "graph theory", "optimization", "analysis",
    },
    "biology": {
        "biology", "biological", "cell", "cells", "cellular", "gene", "genes",
        "genetic", "genetics", "genome", "protein", "proteins", "dna", "rna",
        "enzyme", "enzymes", "metabolism", "ecology", "evolution", "evolutionary",
        "organism", "organisms", "microbiology", "neuroscience", "immunology",
        "biochemistry", "botany", "zoology", "physiology", "crispr", "bacteria",
    },
    "science": {
        "physics", "chemistry", "chemical", "biology", "biological", "medicine",
        "medical", "engineering", "earth", "climate", "environment",
        "environmental", "materials", "energy", "astronomy", "astrophysics",
        "geology", "neuroscience", "quantum", "thermodynamics", "mechanics",
        "electromagnetism", "optics", "acoustics", "oceanography",
    },
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_REVIEW_TITLE_RE = re.compile(
    r"\b(systematic review|literature review|meta-analysis|scoping review|narrative review)\b",
    re.IGNORECASE,
)

# Administrative/editorial material is not a research finding. It is downranked
# unless the student's topic is the administrative process itself.
_ADMIN_WORK_TYPES = {
    "ballot",
    "book-review",
    "comment",
    "correction",
    "editorial",
    "erratum",
    "letter",
    "peer-review",
    "retraction",
    "review-of",
}
_ADMIN_TITLE_RE = re.compile(
    r"\b("
    r"ballot(?:ing)?|ballot results?|vote|voting results?|"
    r"committee(?: announcement| notice| report)?|call for (?:nominations|papers|abstracts)|"
    r"recommended names|approved list|election|nominations?|notice of|erratum|corrigendum|correction to|"
    r"retraction(?: note)?|expression of concern|"
    r"editorial(?: board)?|letter to the editor|book review|obituary|in memoriam|"
    r"preface|front matter|table of contents|minutes|annual report|"
    r"bylaw|rule (?:amendment|emendation|change)|amendment to|"
    r"international code of nomenclature|recommendation\s+\d+|rule\s+\d+|"
    r"proposal (?:no\.?|number|#)?\s*[A-Za-z0-9]|resolution (?:no\.?|number|#)?\s*[A-Za-z0-9]|"
    r"instructions to authors|author guidelines|peer review (?:acknowledg|statement)|"
    r"award announcement|conference announcement|call for"
    r")\b",
    re.IGNORECASE,
)
_ADMIN_TOPIC_RE = re.compile(
    r"\b("
    r"ballot|committee|editorial|erratum|corrigendum|retraction|"
    r"rule[-\s]?making|amendment|emendation|bylaw|governance|election|"
    r"proposal|resolution|nomination|peer review|publication ethics|journal policy|"
    r"editorial policy|vote"
    r")\b",
    re.IGNORECASE,
)
_REFERENCE_WORK_TYPES = {
    "book",
    "book-chapter",
    "handbook",
    "monograph",
    "reference-book",
    "textbook",
}
_REFERENCE_TITLE_RE = re.compile(
    r"\b(textbook|handbook|monograph|encyclopedia|reference work)\b",
    re.IGNORECASE,
)

# Meeting/conference summaries are useful context but are not primary research.
# They should never receive the review bonus or outrank a real article.
_NON_PRIMARY_TITLE_RE = re.compile(
    r"\b("
    r"(?:meeting|conference|workshop|symposium|congress|roundtable)\s+"
    r"(?:report|summary|highlights|proceedings)|"
    r"(?:report|summary|highlights)\s+(?:of|from)\s+(?:the\s+)?"
    r"(?:meeting|conference|workshop|symposium|congress|roundtable)|"
    r"consensus\s+(?:conference|meeting|report)"
    r")\b",
    re.IGNORECASE,
)

# A broad taxonomy/nomenclature query should prefer sources that explain the
# field rather than a narrow applied, clinical, plant or database paper.
_BROAD_TAXONOMY_QUERY_RE = re.compile(
    r"\b("
    r"taxonomy|taxonomic|nomenclature|classification|systematics|"
    r"kingdom|monera|species concept|evolution|phylogeny|"
    r"tree of life|prokaryote|prokaryotic|microbiology"
    r")\b",
    re.IGNORECASE,
)
_BROAD_SCOPE_WORDS = {
    "taxonomy", "taxonomic", "nomenclature", "classification", "systematics",
    "species", "evolution", "evolutionary", "phylogeny", "phylogenetic",
    "kingdom", "kingdoms", "domain", "domains", "prokaryote", "prokaryotes",
    "prokaryotic", "bacteria", "bacterial", "archaea", "archaeal", "microbe",
    "microbes", "microbial", "microbiology", "concept", "concepts",
    "principles", "history", "historical", "diversity", "tree", "life",
}
_NARROW_SCOPE_WORDS = {
    "clinical", "patient", "patients", "diagnosis", "diagnostic", "treatment",
    "therapy", "outbreak", "strain", "strains", "isolate", "isolates",
    "pathogen", "pathogens", "phytoplasma", "plant", "plants", "crop",
    "crops", "disease", "diseases", "prevalence", "case", "cases", "gtdb",
    "candidatus", "metagenome", "metagenomic", "uncultivated", "database",
    "databases", "identification", "detection", "epidemiology", "infection",
    "infections", "antibiotic", "antimicrobial", "agriculture", "soil",
    "marine", "gut", "host", "virus", "viruses", "viral", "bacteriophage",
    "bacteriophages", "phage", "phages", "pharmacist", "pharmacy", "therapy",
    "therapeutic", "physician", "drug", "medical",
}

# Words stripped before comparing two titles for the same narrow sub-story.
_STORY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "this", "to", "was", "were", "what", "when", "where", "which",
    "who", "why", "with", "using", "use",
    "ballot", "balloting", "committee", "election", "proposal", "resolution",
    "vote", "voting", "results", "result", "notice", "announcement", "amendment",
    "emendation", "bylaw", "rule", "editorial", "erratum", "corrigendum",
    "correction", "retraction", "comment", "reply",
}

# Shared, highly specific markers identify the same narrow sub-story even when
# the titles are worded differently (e.g. two papers about naming Candidatus
# taxa from GTDB). Broad subject words are deliberately excluded.
_NARROW_STORY_MARKERS = {
    "gtdb",
    "genome taxonomy database",
    "metagenome assembled",
    "metagenome-assembled",
    "mags",
    "naming the unnamed",
    "uncultivated microbes",
}
_BROAD_STORY_WORDS = _STORY_STOPWORDS | {
    "taxonomy", "taxonomic", "nomenclature", "classification", "systematics",
    "species", "evolution", "evolutionary", "phylogeny", "phylogenetic",
    "prokaryote", "prokaryotes", "prokaryotic", "bacteria", "bacterial",
    "archaea", "archaeal", "microbe", "microbes", "microbial", "microbiology",
    "microorganism", "microorganisms", "organism", "organisms", "genome",
    "genomes", "genomic", "genomics", "sequence", "sequences", "sequencing",
    "diversity", "biology", "biological", "research", "study", "studies",
    "paper", "article", "review", "concept", "concepts", "kingdom", "kingdoms",
    "domain", "domains", "tree", "life", "natural", "system", "systems",
    "new", "novel", "based", "using", "approach", "analysis", "data",
    "database", "databases", "culture", "cultured", "uncultured",
    "representative", "representatives", "international", "journal",
    "bacteriology", "microbiology", "proposal", "proposed", "towards",
    "toward", "need", "needs", "own", "over", "into", "within", "between",
}


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) >= 2 and token not in STOPWORDS
    ]


def idf_weights(records: list[SourceRecord], query_tokens: set[str]) -> dict[str, float]:
    """
    Give each query word a weight based on how rare it is across the results.

    Common words ("feel", "river") end up with a low weight, while distinctive
    words ("sleepy", "monera", "binomial") dominate. This is what stops a paper
    that merely shares one common word from out-ranking the right papers.
    """
    if not query_tokens:
        return {}

    document_frequency = {token: 0 for token in query_tokens}
    for record in records:
        present = set(_tokens(record.title)) | set(_tokens(record.abstract[:4000]))
        for token in query_tokens:
            if token in present:
                document_frequency[token] += 1

    total = max(1, len(records))
    weights: dict[str, float] = {}
    for token in query_tokens:
        # Generic academic words are capped regardless of how "rare" they look
        # inside this particular result set.
        if token in WEAK_WORDS:
            weights[token] = WEAK_WEIGHT
        else:
            # 1.0 for a word in every record; grows as the word gets rarer.
            weights[token] = math.log((total + 1) / (document_frequency[token] + 1)) + 1.0
    return weights


def query_tokens(query: str) -> list[str]:
    """Ordered, de-duplicated significant words of the query."""
    seen: set[str] = set()
    out: list[str] = []
    for token in _tokens(query):
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def core_terms(query: str) -> list[str]:
    """The distinctive words a result must relate to (weak/generic words removed)."""
    return [token for token in query_tokens(query) if token not in WEAK_WORDS]


def _forms(token: str, aliases: dict[str, tuple[str, ...]] | None) -> tuple[str, ...]:
    """The token plus any known synonyms, so a "prokaryote" paper matches "monera"."""
    if aliases and token in aliases:
        return (token, *aliases[token])
    return (token,)


def _record_token_sets(record: SourceRecord) -> tuple[set[str], set[str], set[str]]:
    return (
        set(_tokens(record.title)),
        set(_tokens(record.abstract[:4000])),
        set(_tokens(" ".join(record.subjects))),
    )


def matched_terms(
    query: str,
    record: SourceRecord,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    """Query words (order preserved) this record covers, synonyms included.

    Subject metadata is deliberately excluded: a paper can be tagged "Monera"
    while its title and abstract are about something else.
    """
    title_tokens, abstract_tokens, _ = _record_token_sets(record)
    present = title_tokens | abstract_tokens
    matched = [
        token
        for token in query_tokens(query)
        if any(form in present for form in _forms(token, aliases))
    ]
    # Show the distinctive words ("monera"), not generic filler ("effect").
    distinctive = [token for token in matched if token not in WEAK_WORDS]
    return distinctive or matched


def relevance_score(
    query: str,
    record: SourceRecord,
    weights: dict[str, float] | None = None,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> float:
    """0..1 overlap score with a bonus for an exact phrase match."""
    tokens = query_tokens(query)
    if not tokens:
        return 0.0

    title_tokens, abstract_tokens, subject_tokens = _record_token_sets(record)

    def weight_of(token: str) -> float:
        base = weights.get(token, 1.0) if weights else 1.0
        return min(base, WEAK_WEIGHT) if token in WEAK_WORDS else base

    total_weight = sum(weight_of(token) for token in tokens) or 1.0

    def overlap(candidate: set[str]) -> float:
        hit = 0.0
        for token in tokens:
            if any(form in candidate for form in _forms(token, aliases)):
                hit += weight_of(token)
        return hit / total_weight

    title_overlap = overlap(title_tokens)
    abstract_overlap = overlap(abstract_tokens)
    subject_overlap = overlap(subject_tokens)

    phrase = 1.0 if query.lower().strip() in (record.title + " " + record.abstract).lower() else 0.0

    score = (
        0.62 * title_overlap
        + 0.24 * abstract_overlap
        + 0.09 * subject_overlap
        + 0.05 * phrase
    )
    return max(0.0, min(1.0, score))


def _citation_score(count: int) -> float:
    # log1p keeps the difference between 10 and 100 citations meaningful while
    # stopping a 10,000-citation paper from dominating the ranking.
    return min(1.0, math.log1p(max(0, count)) / math.log1p(2000))


def _recency_score(year: int | None) -> float:
    if not year:
        return 0.0
    age = max(0, date.today().year - year)
    return max(0.0, 1.0 - age / 25)


def is_administrative(record: SourceRecord) -> bool:
    """True for ballots, editorials, errata, retraction notices, etc."""
    work_type = (record.work_type or "").strip().lower()
    if work_type in _ADMIN_WORK_TYPES:
        return True
    return bool(_ADMIN_TITLE_RE.search(record.title or ""))


def is_admin_topic(query: str) -> bool:
    """The student is researching the administrative process itself."""
    return bool(_ADMIN_TOPIC_RE.search(query or ""))


def is_reference_work(record: SourceRecord) -> bool:
    work_type = (record.work_type or "").strip().lower()
    if work_type in _REFERENCE_WORK_TYPES:
        return True
    return bool(_REFERENCE_TITLE_RE.search(record.title or ""))


def is_foundational(record: SourceRecord) -> bool:
    """An older, highly cited work that a field still builds on."""
    if not record.year or record.citation_count < 100:
        return False
    return date.today().year - record.year >= 10


def is_preprint(record: SourceRecord) -> bool:
    """Best-effort detection of a non-peer-reviewed manuscript."""
    work_type = (record.work_type or "").strip().lower()
    journal = record.journal or ""
    return bool(
        re.search(
            r"arxiv|biorxiv|medrxiv|preprint|ssrn|research square|researchsquare",
            journal,
            re.I,
        )
    ) or work_type in {"preprint", "posted-content"}


def is_non_primary_report(record: SourceRecord) -> bool:
    """True for meeting/conference/workshop reports and summaries."""
    return bool(_NON_PRIMARY_TITLE_RE.search(record.title or ""))


def scope_score(record: SourceRecord, query: str) -> float:
    """How central/broad a source is for a taxonomy-style query.

    A broad query wants papers that explain a field. A narrow applied paper about
    one host, crop, clinical sample or sequence database is still relevant, but it
    should not take a top-six slot ahead of the field's core literature. For
    non-taxonomy queries this is neutral (0.5) so plant/clinical searches keep
    their natural results.
    """
    if not _BROAD_TAXONOMY_QUERY_RE.search(query or ""):
        return 0.5

    # A focused query ("Phytoplasma taxonomy", "Candidatus taxonomy", "viral
    # taxonomy") is already about the narrow subject; the broad-vs-applied
    # correction must not push those results down.
    query_words = set(_TOKEN_RE.findall((query or "").lower()))
    if query_words & _NARROW_SCOPE_WORDS:
        return 0.5

    text = f"{record.title} {record.abstract[:2500]}".lower()
    words = set(_TOKEN_RE.findall(text))
    title_words = set(_TOKEN_RE.findall((record.title or "").lower()))
    broad = len(words & _BROAD_SCOPE_WORDS)
    narrow = len(words & _NARROW_SCOPE_WORDS)
    if broad == 0 and narrow == 0:
        return 0.5

    # Viral taxonomy and social-science angles are not the core literature for
    # a Kingdom Monera / prokaryote classification query. Penalise them hard
    # unless the student explicitly asked about viruses or the social angle.
    # Check the title so a broad paper that mentions phages in passing survives.
    virus_words = {
        "virus", "viruses", "viral", "bacteriophage", "bacteriophages", "phage", "phages",
    }
    if title_words & virus_words and not (query_words & virus_words):
        return 0.15
    social_words = {"gender", "women", "equity", "inclusion", "honouring", "honoring"}
    if title_words & social_words and not (query_words & social_words):
        return 0.15

    return max(0.0, min(1.0, 0.5 + 0.12 * broad - 0.20 * narrow))


def _story_signature(record: SourceRecord) -> tuple[str, ...]:
    tokens = [
        token
        for token in normalize_title(record.title).split()
        if token not in _STORY_STOPWORDS and not token.isdigit()
    ]
    return tuple(tokens)


def _story_ids(record: SourceRecord) -> set[str]:
    """Shared proposal/ballot identifiers, e.g. "proposal 2024-a"."""
    normalized = normalize_title(record.title)
    found: set[str] = set()
    ignored = {
        "result", "results", "vote", "voting", "on", "for", "the", "of",
        "proposal", "ballot", "resolution", "amendment", "rule", "motion",
        "measure", "number", "no",
    }
    for match in re.finditer(
        r"\b(?:proposal|ballot|resolution|amendment|rule|motion|measure)"
        r"\s*(?:no\.?|number|#)?\s*([a-z0-9]+)\b(?:\s+([a-z])\b)?",
        normalized,
    ):
        first = (match.group(1) or "").strip(".-")
        suffix = (match.group(2) or "").strip()
        value = f"{first} {suffix}".strip()
        if not value or value in ignored or first in ignored:
            continue
        # A bare year is too broad to identify one proposal, but "2024 a" is not.
        if value.isdigit():
            continue
        found.add(value)
    return found


def same_story(
    first: SourceRecord,
    second: SourceRecord,
    topic_tokens: set[str] | None = None,
) -> bool:
    """Conservative check that two results describe the same narrow sub-story.

    A proposal and its ballot count as one story. The threshold is intentionally
    high so genuinely different papers about the same broad topic survive.
    ``topic_tokens`` are excluded from title overlap: two studies of
    "antibiotic resistance" are not duplicates just because those words appear
    in both titles.
    """
    if _story_ids(first) & _story_ids(second):
        return True

    left = _story_signature(first)
    right = _story_signature(second)
    if not left or not right:
        return bool(is_administrative(first) and is_administrative(second))

    left_set, right_set = set(left), set(right)
    shared = left_set & right_set
    if topic_tokens:
        shared -= topic_tokens
    if (
        len(shared) >= 2
        and len(shared) / min(len(left_set), len(right_set)) >= 0.65
    ):
        return True

    # A Candidatus/GTDB naming paper and an "uncultivated microbes need names"
    # paper are two sides of one sub-story, even though their titles barely
    # overlap. Shared markers from title+abstract catch that case without
    # lowering the general title-similarity threshold.
    left_markers, _ = _story_aspects(first)
    right_markers, _ = _story_aspects(second)
    if left_markers & right_markers:
        return True

    left_text = f"{first.title} {first.abstract}".lower()
    right_text = f"{second.title} {second.abstract}".lower()
    if "candidatus" in left_text and "candidatus" in right_text:
        combined = f"{left_text} {right_text}"
        if re.search(
            r"gtdb|genome taxonomy database|unnamed|uncultivated|naming the unnamed",
            combined,
        ):
            return True

    if len(left) < 3 or len(right) < 3:
        return False
    ratio = SequenceMatcher(None, " ".join(left), " ".join(right)).ratio()
    return ratio >= 0.86


def _story_aspects(record: SourceRecord) -> tuple[set[str], set[str]]:
    """Specific sub-story markers plus distinctive non-broad terms."""
    text = f"{record.title} {record.abstract[:2000]}"
    lowered = text.lower()
    markers = {
        marker
        for marker in _NARROW_STORY_MARKERS
        if marker in lowered
    }
    tokens = {
        token
        for token in _TOKEN_RE.findall(lowered)
        if len(token) >= 7 and token not in _BROAD_STORY_WORDS and not token.isdigit()
    }
    return markers, tokens


def _is_historical_discovery(record: SourceRecord) -> bool:
    return "historical term" in (record.discovery or "").lower()


def _is_foundational_classic(record: SourceRecord) -> bool:
    """A historical discovery or an older, heavily cited field-defining work."""
    if _is_historical_discovery(record):
        return True
    return bool(
        is_foundational(record)
        and record.year is not None
        and record.year <= 2005
    )


def _select_diverse(
    scored: list[tuple[SourceRecord, float, bool]],
    limit: int | None,
    *,
    admin_topic: bool,
    ensure_historical: bool = False,
    topic_tokens: set[str] | None = None,
) -> list[SourceRecord]:
    """Pick the best results while keeping one source per narrow sub-story."""
    ordered = sorted(scored, key=lambda item: item[0].score, reverse=True)
    selected: list[SourceRecord] = []
    admin_count = 0

    for record, _, gated_out in ordered:
        if gated_out:
            continue
        if limit is not None and len(selected) >= limit:
            break
        if record.is_administrative and not admin_topic:
            if admin_count >= 1:
                continue
        if any(
            same_story(record, existing, topic_tokens=topic_tokens)
            for existing in selected
        ):
            continue
        selected.append(record)
        if record.is_administrative and not admin_topic:
            admin_count += 1

    # An obsolete term needs both sides of the story. Reserve one slot for a
    # tagged historical source and one for a field-defining classic when they
    # were found but ranked just below the cut. With a normal six-result page
    # this keeps Whittaker and Woese visible without dropping the modern papers.
    if ensure_historical and (limit is None or limit >= 2):
        reserved: list[SourceRecord] = []

        def reserve(predicate) -> None:
            if any(predicate(record) for record in selected):
                return
            candidate = next(
                (
                    record
                    for record, _, gated_out in ordered
                    if not gated_out
                    and predicate(record)
                    and record not in selected
                    and not (record.is_administrative and not admin_topic)
                ),
                None,
            )
            if candidate is None:
                return
            if limit is not None and len(selected) >= limit:
                # Replace the lowest-ranked slot, but never a slot that was
                # already reserved for the other half of the historical story.
                for index in range(len(selected) - 1, -1, -1):
                    if selected[index] not in reserved:
                        selected[index] = candidate
                        break
                else:
                    return
            else:
                selected.append(candidate)
            reserved.append(candidate)

        reserve(_is_historical_discovery)
        reserve(
            lambda record: bool(
                _is_foundational_classic(record)
                and not _is_historical_discovery(record)
            )
        )

    # Reservations replace the lowest slots; restore score order so a strong
    # historical source rises to where its score belongs instead of staying at
    # the bottom of the page.
    selected.sort(key=lambda record: record.score, reverse=True)
    return selected


def _subject_matches(record: SourceRecord, subject: str) -> bool:
    if subject in {"any", "general"}:
        return True
    keywords = SUBJECT_KEYWORDS.get(subject, set())
    if not keywords:
        return True

    haystack = " ".join([record.title, record.abstract[:1500], *record.subjects]).lower()
    tokens = set(_tokens(haystack))
    for keyword in keywords:
        if " " in keyword:
            if keyword in haystack:
                return True
        elif keyword in tokens:
            return True
    return False


def apply_filters(records: list[SourceRecord], filters: SearchFilters) -> list[SourceRecord]:
    output: list[SourceRecord] = []
    for record in records:
        if filters.year_from and (record.year is None or record.year < filters.year_from):
            continue
        if filters.year_to and (record.year is None or record.year > filters.year_to):
            continue
        if filters.reviews_only and record.is_review is not True:
            continue
        if filters.open_access_only and record.is_open_access is not True:
            continue
        if filters.exclude_preprints and is_preprint(record):
            continue
        if filters.english_only and is_english(record) is False:
            continue
        if not _subject_matches(record, filters.subject):
            continue
        output.append(record)
    return output


def _reason(
    record: SourceRecord,
    relevance: float,
    admin_penalized: bool = False,
    scope: float | None = None,
) -> str:
    if relevance >= 0.70:
        opening = "Strong topical match"
    elif relevance >= 0.45:
        opening = "Relevant match"
    else:
        opening = "Background/supporting match"

    facts: list[str] = []
    if record.is_review:
        facts.append("review article")
    elif is_reference_work(record):
        facts.append("textbook/reference work")
    if is_foundational(record):
        facts.append("foundational paper")
    if record.citation_count >= 100:
        facts.append(f"highly cited ({record.citation_count:,})")
    elif record.citation_count >= 20:
        facts.append(f"well cited ({record.citation_count:,})")
    if record.year and record.year >= date.today().year - 5:
        facts.append(f"recent ({record.year})")
    if record.is_open_access:
        facts.append("open access")
    if record.is_retracted:
        facts.append("retracted paper — use with caution")
    if record.is_non_primary:
        facts.append("meeting/conference report — downranked")
    if scope is not None and scope < 0.35:
        facts.append("narrow/applied focus — downranked for a broad topic")
    if record.discovery:
        facts.append(record.discovery)
    if admin_penalized:
        facts.append("administrative/editorial notice — downranked")
    elif record.is_administrative:
        facts.append("administrative document (matched your topic)")

    return f"{opening} — " + " · ".join(facts) if facts else opening


def rank_records(
    query: str,
    records: list[SourceRecord],
    limit: int | None = None,
    mode: str = "strict",
    aliases: dict[str, tuple[str, ...]] | None = None,
    plan: "ConceptPlan | None" = None,
    apply_gate: bool = True,
) -> list[SourceRecord]:
    """Rank and select the strongest distinct sources.

    When ``limit`` is provided, historical reservation slots can replace the
    lowest-ranked slots. That means the first page of a larger feed must be
    selected with the original page size, not just sliced from a larger list.
    ``rank_feed`` below does exactly that.
    """
    aliases = aliases if aliases is not None else build_aliases(query)
    tokens = set(query_tokens(query))
    weights = idf_weights(records, tokens)
    core = set(core_terms(query))
    admin_topic = is_admin_topic(query)
    has_plan = bool(plan is not None and plan.concepts)

    scored: list[tuple[SourceRecord, float, bool]] = []
    for record in records:
        matched = matched_terms(query, record, aliases)
        relevance = relevance_score(query, record, weights, aliases)
        record.is_administrative = is_administrative(record)
        record.is_non_primary = is_non_primary_report(record)
        scope = scope_score(record, query)

        # Precision gate: title/abstract must directly cover the main concept, or
        # at least two concepts from the plan. Subject-only matches never count.
        if not apply_gate:
            # Related-source lists are recommendations around a known paper;
            # their titles need not repeat the parent title's words.
            gated_out = False
        elif has_plan:
            if mode == "balanced":
                # Explicit user choice for broad/exploratory topics: any concept
                # in the plan is enough. The default remains the stricter CORE
                # rule (primary concept, or at least two concepts).
                gated_out = not plan.matched_labels(record)
            else:
                gated_out = not plan.is_core(record)
        else:
            gated_out = bool(core) and not (core & set(matched))

        # A retracted article is not a valid source in the default strict mode.
        # In balanced mode it is shown with a clear warning so it can be studied
        # as part of a retraction/correction story.
        if record.is_retracted and mode == "strict" and not admin_topic:
            gated_out = True

        # A concept-plan match can still be incidental. Keep a low direct-overlap
        # floor for recent sources, but never drop a historical/foundational work
        # that a broad taxonomy query needs for context.
        if (
            has_plan
            and not gated_out
            and mode == "strict"
            and relevance < MIN_PLAN_RELEVANCE_STRICT
            and not is_foundational(record)
            and not _is_historical_discovery(record)
            and not (record.is_administrative and admin_topic)
        ):
            gated_out = True

        citations = _citation_score(record.citation_count)
        recency = _recency_score(record.year)
        review = (
            1.0
            if (record.is_review or is_reference_work(record))
            and not record.is_non_primary
            else 0.0
        )
        foundational = 1.0 if is_foundational(record) else 0.0

        # Quality signals (citations/recency/review) are damped when a paper is
        # only loosely on-topic, so a famous but unrelated paper cannot outrank
        # a paper the student actually needs.
        quality = (
            WEIGHT_CITATIONS * citations
            + WEIGHT_RECENCY * recency
            + WEIGHT_REVIEW * review
            + WEIGHT_FOUNDATIONAL * foundational
        )
        overall = WEIGHT_RELEVANCE * relevance + quality * (0.35 + 0.65 * relevance)

        # A narrow/applied paper can be relevant and still be the wrong level for
        # a broad "taxonomy/nomenclature" query. Scope is a multiplier so it
        # does not distort the transparent relevance/citation breakdown.
        overall *= 0.50 + 0.50 * scope

        admin_penalized = record.is_administrative and not admin_topic
        if admin_penalized:
            overall *= 0.35
        if record.is_non_primary and not admin_topic:
            overall *= 0.55

        record.score = round(overall * 100, 1)
        record.score_breakdown = {
            "relevance": round(relevance * 100, 1),
            "citations": round(citations * 100, 1),
            "recency": round(recency * 100, 1),
            "review": round(review * 100, 1),
            "foundational": round(foundational * 100, 1),
            "scope": round(scope * 100, 1),
        }
        record.matched_terms = matched
        record.reason = _reason(record, relevance, admin_penalized, scope)
        scored.append((record, relevance, gated_out))

    floor = MIN_RELEVANCE_STRICT if mode == "strict" else MIN_RELEVANCE_BALANCED
    # When a concept plan exists, its title/abstract CORE gate is already the
    # precision filter. Do not let the older lexical floor throw away a
    # foundational source that addresses the concept with different wording.
    kept = [
        item
        for item in scored
        if not item[2] and (not apply_gate or has_plan or item[1] >= floor)
    ]

    # No fallback and no floor relaxation for searches: return fewer strong,
    # distinct sources rather than padding the list with weak or duplicate ones.
    ensure_historical = bool(
        apply_gate
        and plan is not None
        and plan.primary is not None
        and plan.primary.obsolete
    )
    return _select_diverse(
        kept,
        limit,
        admin_topic=admin_topic,
        ensure_historical=ensure_historical,
        topic_tokens=tokens,
    )


def rank_feed(
    query: str,
    records: list[SourceRecord],
    page_size: int = 20,
    max_results: int = 100,
    mode: str = "strict",
    aliases: dict[str, tuple[str, ...]] | None = None,
    plan: "ConceptPlan | None" = None,
    apply_gate: bool = True,
) -> list[SourceRecord]:
    """Rank a larger feed without changing the protected first page.

    ``_select_diverse`` may use historical/foundational reservation slots when
    the limit is small. Re-ranking the same records with a larger limit can
    therefore produce a different first page. The first ``page_size`` results
    are selected exactly as they would be for a normal search, then the broader
    selection is appended for progressive scrolling.

    No extra provider calls are made; this is only local ranking. Results are
    returned in feed order, with the first page untouched.
    """
    page_size = max(1, page_size)
    max_results = max(page_size, max_results)

    first_page = rank_records(
        query,
        records,
        page_size,
        mode=mode,
        aliases=aliases,
        plan=plan,
        apply_gate=apply_gate,
    )
    if max_results <= page_size:
        return first_page

    broad = rank_records(
        query,
        records,
        max_results,
        mode=mode,
        aliases=aliases,
        plan=plan,
        apply_gate=apply_gate,
    )
    seen = {id(record) for record in first_page}
    return first_page + [record for record in broad if id(record) not in seen]


def credibility_checklist(record: SourceRecord) -> list[CredibilityItem]:
    """Four plain-English checks a student can actually understand."""
    items: list[CredibilityItem] = []

    work_type = (record.work_type or "").lower()
    journal = record.journal or ""
    looks_preprint = is_preprint(record)
    peer_reviewed = bool(journal) and not looks_preprint and work_type not in {"dataset"}

    if peer_reviewed:
        items.append(
            CredibilityItem(
                label="Peer reviewed",
                status="good",
                detail=f"Published in {journal}.",
            )
        )
    elif looks_preprint:
        items.append(
            CredibilityItem(
                label="Peer reviewed",
                status="warn",
                detail="This looks like a preprint, so it may not have been peer reviewed yet.",
            )
        )
    else:
        items.append(
            CredibilityItem(
                label="Peer reviewed",
                status="unknown",
                detail="No journal information was available to confirm peer review.",
            )
        )

    if record.citation_count >= 50:
        items.append(
            CredibilityItem(
                label="Citation impact",
                status="good",
                detail=f"{record.citation_count:,} citations — well established.",
            )
        )
    elif record.citation_count > 0:
        items.append(
            CredibilityItem(
                label="Citation impact",
                status="warn",
                detail=f"{record.citation_count:,} citations — useful, but not yet widely cited.",
            )
        )
    else:
        items.append(
            CredibilityItem(
                label="Citation impact",
                status="unknown",
                detail="No citation count available (it may be new, or the provider does not report citations).",
            )
        )

    if record.year is None:
        items.append(
            CredibilityItem(
                label="Recency",
                status="unknown",
                detail="Publication year is missing.",
            )
        )
    else:
        age = date.today().year - record.year
        if age <= 5:
            items.append(
                CredibilityItem(
                    label="Recency",
                    status="good",
                    detail=f"Published in {record.year}, within the last five years.",
                )
            )
        elif age <= 15:
            items.append(
                CredibilityItem(
                    label="Recency",
                    status="warn",
                    detail=f"Published in {record.year}; still relevant, but check for newer work.",
                )
            )
        else:
            items.append(
                CredibilityItem(
                    label="Recency",
                    status="warn",
                    detail=f"Published in {record.year}; treat as foundational or historical.",
                )
            )

    indexed_providers = {"pubmed", "crossref", "openalex", "europepmc", "doaj", "core"}
    matched = sorted(indexed_providers & set(record.providers))
    if journal and matched:
        items.append(
            CredibilityItem(
                label="Reputable journal",
                status="good",
                detail=f"Journal metadata confirmed by {' and '.join(matched)}.",
            )
        )
    elif journal:
        items.append(
            CredibilityItem(
                label="Reputable journal",
                status="warn",
                detail="Journal name is present, but it was not confirmed by an indexed provider.",
            )
        )
    else:
        items.append(
            CredibilityItem(
                label="Reputable journal",
                status="unknown",
                detail="No journal name is available.",
            )
        )

    if record.is_retracted:
        items.append(
            CredibilityItem(
                label="Retraction status",
                status="warn",
                detail="This paper has been retracted. Do not rely on its findings; cite the retraction notice instead.",
            )
        )

    if record.is_non_primary:
        items.append(
            CredibilityItem(
                label="Publication type",
                status="warn",
                detail="Meeting/conference report, not a primary research article.",
            )
        )

    if record.is_administrative:
        items.append(
            CredibilityItem(
                label="Publication type",
                status="warn",
                detail="Administrative/editorial notice, not a research article.",
            )
        )

    return items
