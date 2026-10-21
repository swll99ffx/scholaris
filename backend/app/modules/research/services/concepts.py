"""
Concept expansion: work out *what a topic means*, not just which words it uses.

School activities often use obsolete or textbook-only terms ("Kingdom Monera",
"binomial nomenclature"). Searching only for those words misses the modern
papers that replaced them, while searching only for modern words misses the
historical sources that introduced them.

This module builds a small, transparent concept plan:

  * curated knowledge for common school topics (Monera, Protista, binomial
    nomenclature, ...),
  * an LLM plan when AI is available (validated, never trusted blindly),
  * a conservative noun-phrase fallback for everything else.

Each concept keeps its historical meaning, current meaning/replacement and
alternate names. The plan also produces separate search queries for the modern
concepts, the historical terms, each concept and the relationship between them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..models import SourceRecord
from .ranking import STOPWORDS, WEAK_WORDS
from .synonyms import build_aliases
from .text import clean_text, normalize_title

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-']*")
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-']*")

# Words that should not carry a concept on their own. "Kingdom" is a rank, not
# a topic; "sample" is assignment boilerplate.
_CONCEPT_IGNORED = {
    "kingdom",
    "kingdoms",
    "sample",
    "samples",
    "specimen",
    "specimens",
    "class",
    "classes",
    "activity",
    "activities",
    "assignment",
    "lesson",
    "module",
}

# Single words that are too broad to prove a source directly addresses a
# concept. They can still be search terms, but they cannot carry the CORE gate
# unless the concept itself is exactly that word.
_GENERIC_MATCH_WORDS = {
    "algae",
    "classification",
    "eukaryote",
    "eukaryotes",
    "microbe",
    "microbes",
    "microorganism",
    "microorganisms",
    "nomenclature",
    "systematics",
    "taxonomy",
}

# Split a topic at prepositions/conjunctions to recover noun phrases such as
# "social media" and "student focus" from "effect of social media on student focus".
_CHUNK_SPLIT_RE = re.compile(
    r"\b(?:of|in|on|for|with|using|use|between|among|and|or|to|from|by|as|at|"
    r"into|about|through|during|including|via)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ConceptKnowledge:
    """A high-confidence expansion for a term that commonly appears in school work."""

    key: str
    label: str
    triggers: tuple[str, ...]
    historical: str
    current: str
    alternate_names: tuple[str, ...]
    search_terms: tuple[str, ...]
    modern_terms: tuple[str, ...]
    related_terms: tuple[str, ...] = ()
    obsolete: bool = False


@dataclass(frozen=True, slots=True)
class ConceptPattern:
    """A multi-word question pattern, e.g. \"sleepy\" + \"hot\"."""

    key: str
    label: str
    trigger_groups: tuple[tuple[str, ...], ...]
    current: str
    alternate_names: tuple[str, ...]
    search_terms: tuple[str, ...]
    modern_terms: tuple[str, ...]
    historical: str | None = None
    obsolete: bool = False


# Deliberately small and conservative. The fallback never invents historical
# meanings; it only lists what it can see in the topic and synonym map.
KNOWLEDGE: tuple[ConceptKnowledge, ...] = (
    ConceptKnowledge(
        key="monera",
        label="Kingdom Monera",
        triggers=("monera",),
        historical=(
            "A kingdom of prokaryotes in Whittaker's five-kingdom system (1969). "
            "It grouped bacteria and blue-green algae together."
        ),
        current=(
            "Replaced by the domains Bacteria and Archaea in Woese's three-domain "
            "system; 'prokaryote' is the modern descriptive term."
        ),
        alternate_names=(
            "prokaryote",
            "prokaryotes",
            "prokaryotic",
            "bacteria",
            "archaea",
            "microorganism",
            "microorganisms",
            "microbe",
            "microbes",
        ),
        search_terms=(
            "monera",
            "prokaryote",
            "prokaryotes",
            "prokaryotic",
            "bacteria",
            "archaea",
            "microorganism",
            "microorganisms",
        ),
        modern_terms=("prokaryote", "prokaryotic", "bacteria", "archaea", "microorganism"),
        related_terms=("Whittaker", "five-kingdom", "three-domain", "Woese"),
        obsolete=True,
    ),
    ConceptKnowledge(
        key="protista",
        label="Kingdom Protista",
        triggers=("protista", "protist", "protists", "protozoa"),
        historical=(
            "A catch-all kingdom in the five-kingdom system for eukaryotes that were "
            "not plants, animals or fungi."
        ),
        current=(
            "Protists are now treated as a polyphyletic group rather than a formal "
            "kingdom; modern classification uses eukaryote lineages."
        ),
        alternate_names=("protist", "protists", "protozoa", "protozoan", "eukaryote", "algae"),
        search_terms=("protista", "protist", "protists", "protozoa", "eukaryote"),
        modern_terms=("protist", "protists", "protozoa", "eukaryote"),
        related_terms=("Haeckel", "five-kingdom"),
        obsolete=True,
    ),
    ConceptKnowledge(
        key="binomial_nomenclature",
        label="Binomial nomenclature",
        triggers=("binomial", "nomenclature"),
        historical=(
            "Linnaeus's two-part naming system (genus + species), formalised in the "
            "18th century."
        ),
        current=(
            "The modern system of scientific naming governed by international "
            "nomenclature codes; part of taxonomy and systematics."
        ),
        alternate_names=("scientific naming", "taxonomy", "systematics", "classification"),
        search_terms=("binomial", "nomenclature", "taxonomy", "systematics", "classification"),
        modern_terms=("binomial", "nomenclature", "taxonomy", "classification"),
        related_terms=("Linnaeus", "taxonomy"),
    ),
    ConceptKnowledge(
        key="five_kingdom",
        label="Five-kingdom classification",
        triggers=("five kingdom", "five-kingdom", "five kingdoms", "whittaker"),
        historical=(
            "Whittaker's 1969 scheme: Monera, Protista, Fungi, Plantae and Animalia."
        ),
        current=(
            "Largely replaced by the three-domain system (Bacteria, Archaea, Eukarya), "
            "though the five-kingdom scheme is still taught."
        ),
        alternate_names=("Whittaker classification", "five kingdom system"),
        search_terms=("five-kingdom", "Whittaker", "classification", "Monera", "Protista"),
        modern_terms=("five-kingdom", "classification"),
        related_terms=("Whittaker", "Monera"),
        obsolete=True,
    ),
    ConceptKnowledge(
        key="three_domain",
        label="Three-domain system",
        triggers=("three domain", "three-domain", "three domains", "woese"),
        historical=(
            "Woese's rRNA-based revision split prokaryotes into the domains Bacteria "
            "and Archaea."
        ),
        current=(
            "The standard modern tree of life: Bacteria, Archaea and Eukarya."
        ),
        alternate_names=("Woese classification", "three domain system"),
        search_terms=("three-domain", "Bacteria", "Archaea", "Eukarya", "Woese"),
        modern_terms=("three-domain", "Bacteria", "Archaea", "Eukarya"),
        related_terms=("Woese", "Bacteria", "Archaea"),
    ),
    ConceptKnowledge(
        key="blue_green_algae",
        label="Blue-green algae",
        triggers=("blue green algae", "blue-green algae", "cyanobacteria"),
        historical=(
            "Photosynthetic prokaryotes once called blue-green algae and grouped with "
            "plants."
        ),
        current="Cyanobacteria, a phylum of bacteria.",
        alternate_names=("cyanobacteria", "blue-green bacteria"),
        search_terms=("cyanobacteria", "blue-green algae", "blue-green bacteria"),
        modern_terms=("cyanobacteria", "blue-green bacteria"),
        related_terms=("cyanobacteria", "Haeckel"),
        obsolete=True,
    ),
)

# Question patterns that are too vague as isolated keywords. This keeps the
# offline fallback useful for the app's own example ("sleepy when it's hot")
# without pretending to know history it was not given.
PATTERNS: tuple[ConceptPattern, ...] = (
    ConceptPattern(
        key="sleep_heat",
        label="Sleep and ambient temperature",
        trigger_groups=(
            ("sleepy", "hot"),
            ("sleepy", "heat"),
            ("sleepiness", "hot"),
            ("sleepiness", "heat"),
            ("sleep", "hot"),
            ("sleep", "heat"),
            ("sleep", "temperature"),
            ("sleep", "thermoregulation"),
        ),
        current=(
            "How ambient temperature and heat affect sleepiness, sleep timing and "
            "sleep quality."
        ),
        alternate_names=(
            "sleepiness",
            "drowsiness",
            "sleep quality",
            "sleep temperature",
            "ambient temperature",
            "heat exposure",
            "thermoregulation",
        ),
        search_terms=(
            "sleep",
            "sleepiness",
            "drowsiness",
            "temperature",
            "thermoregulation",
            "heat",
        ),
        modern_terms=("sleep", "sleepiness", "ambient", "temperature", "thermoregulation"),
    ),
)


@dataclass(slots=True)
class Concept:
    label: str
    historical: str | None
    current: str
    alternate_names: list[str] = field(default_factory=list)
    obsolete: bool = False
    primary: bool = False
    source: str = "heuristic"  # curated | llm | heuristic
    search_terms: list[str] = field(default_factory=list)
    modern_terms: list[str] = field(default_factory=list)
    related_terms: list[str] = field(default_factory=list)
    match_phrases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "historical": self.historical,
            "current": self.current,
            "alternate_names": self.alternate_names,
            "obsolete": self.obsolete,
            "primary": self.primary,
            "source": self.source,
        }

    def matches(self, token_set: set[str]) -> bool:
        """True when a title/abstract token set directly covers this concept."""
        own_label = normalize_title(self.label)
        for phrase in self.match_phrases:
            terms = content_tokens(phrase)
            if not terms or not all(term in token_set for term in terms):
                continue
            if (
                len(terms) == 1
                and terms[0] in _GENERIC_MATCH_WORDS
                and normalize_title(phrase) != own_label
            ):
                continue
            return True
        return False


@dataclass(slots=True)
class SearchQuery:
    query: str
    kind: str  # modern | historical | concept | relationship
    labels: list[str] = field(default_factory=list)
    primary: bool = False

    def discovery_label(self) -> str | None:
        if self.kind == "historical":
            label = self.labels[0] if self.labels else "historical term"
            return f"Historical term: {label}"
        if self.kind == "concept":
            label = self.labels[0] if self.labels else "concept"
            return f"Concept: {label}"
        if self.kind == "relationship":
            return "Relationship search"
        return None


@dataclass(slots=True)
class ConceptPlan:
    concepts: list[Concept] = field(default_factory=list)
    queries: list[SearchQuery] = field(default_factory=list)

    @property
    def primary(self) -> Concept | None:
        for concept in self.concepts:
            if concept.primary:
                return concept
        return self.concepts[0] if self.concepts else None

    def matched_labels(self, record: SourceRecord) -> list[str]:
        tokens = content_token_set(f"{record.title} {record.abstract[:6000]}")
        return [concept.label for concept in self.concepts if concept.matches(tokens)]

    def is_core(self, record: SourceRecord) -> bool:
        """
        A source is CORE only when its title/abstract directly addresses the main
        concept, or covers at least two distinct concepts in the plan.
        """
        if not self.concepts:
            return True
        matched = self.matched_labels(record)
        if not matched:
            return False
        primary = self.primary
        if primary and primary.label in matched:
            return True
        return len(matched) >= 2

    def to_out(self) -> list[dict[str, Any]]:
        return [concept.to_dict() for concept in self.concepts]

    @property
    def cache_key(self) -> str:
        concepts = ";".join(
            f"{item.label}|{item.current}|{item.obsolete}|{item.source}"
            for item in self.concepts
        )
        queries = ";".join(f"{query.kind}:{query.query}" for query in self.queries)
        return f"{concepts}||{queries}"

    @classmethod
    def empty(cls) -> "ConceptPlan":
        return cls()


def content_tokens(text: str) -> list[str]:
    """Significant words for concept matching (generic/weak words removed)."""
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0)
        if (
            len(token) < 2
            or token in seen
            or token in STOPWORDS
            or token in WEAK_WORDS
            or token in _CONCEPT_IGNORED
        ):
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def content_token_set(text: str) -> set[str]:
    return set(content_tokens(text))


def _clean_label(value: str) -> str:
    text = clean_text(value)
    text = text.strip(" .,;:!?()[]{}\"'“”‘’")
    return text[:90].strip()


def _knowledge_matches(item: ConceptKnowledge, normalized_topic: str) -> bool:
    topic_tokens = set(normalized_topic.split())
    for trigger in item.triggers:
        normalized = normalize_title(trigger)
        if not normalized:
            continue
        if " " in normalized or "-" in normalized:
            if normalized in normalized_topic:
                return True
        elif normalized in topic_tokens:
            return True
    return False


def _pattern_matches(item: ConceptPattern, normalized_topic: str) -> bool:
    topic_tokens = set(normalized_topic.split())
    for group in item.trigger_groups:
        matched = True
        for term in group:
            normalized = normalize_title(term)
            if " " in normalized:
                if normalized not in normalized_topic:
                    matched = False
                    break
            elif normalized not in topic_tokens:
                matched = False
                break
        if matched:
            return True
    return False


def _concept_from_pattern(item: ConceptPattern) -> Concept:
    alternates = list(dict.fromkeys(item.alternate_names))
    return Concept(
        label=item.label,
        historical=item.historical,
        current=item.current,
        alternate_names=alternates,
        obsolete=item.obsolete,
        source="curated",
        search_terms=list(item.search_terms),
        modern_terms=list(item.modern_terms),
        related_terms=[],
        # Deliberately do not use every search term as a gate phrase: \"sleep\"
        # and \"temperature\" alone are too broad. The multi-word alternates and
        # the distinctive sleepiness/thermoregulation terms do the gating.
        match_phrases=_match_phrases(item.label, item.current, alternates, []),
    )


def _concept_token_set(concept: Concept) -> set[str]:
    parts: Iterable[str] = (
        concept.label,
        *concept.search_terms,
        *concept.alternate_names,
    )
    tokens: set[str] = set()
    for part in parts:
        tokens.update(content_tokens(part))
    return tokens


def _overlaps(first: Concept, second: Concept) -> bool:
    left = _concept_token_set(first)
    right = _concept_token_set(second)
    if not left or not right:
        return normalize_title(first.label) == normalize_title(second.label)
    shared = left & right
    return bool(shared) and len(shared) / min(len(left), len(right)) >= 0.6


def _synonym_alternates(text: str, limit: int = 6) -> list[str]:
    original = set(content_tokens(text))
    found: list[str] = []
    seen: set[str] = set()
    for aliases in build_aliases(text).values():
        for alias in aliases:
            key = normalize_title(alias)
            if not key or key in seen or key in original:
                continue
            # Avoid duplicate single tokens already represented by a phrase.
            seen.add(key)
            found.append(alias)
            if len(found) >= limit:
                return found
    return found


def _match_phrases(
    label: str,
    current: str,
    alternates: list[str],
    search_terms: list[str],
) -> list[str]:
    phrases: list[str] = [label, *alternates, *search_terms]
    # A short current meaning is usually a phrase; long descriptions are not.
    if current and len(current) <= 100:
        phrases.append(current)
    seen: set[str] = set()
    output: list[str] = []
    for phrase in phrases:
        cleaned = _clean_label(phrase)
        key = normalize_title(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _concept_from_knowledge(item: ConceptKnowledge) -> Concept:
    alternates = list(dict.fromkeys(item.alternate_names))
    return Concept(
        label=item.label,
        historical=item.historical,
        current=item.current,
        alternate_names=alternates,
        obsolete=item.obsolete,
        source="curated",
        search_terms=list(item.search_terms),
        modern_terms=list(item.modern_terms),
        related_terms=list(item.related_terms),
        match_phrases=_match_phrases(
            item.label,
            item.current,
            alternates,
            [*item.search_terms, *item.related_terms],
        ),
    )


def _concept_from_llm(raw: dict[str, Any]) -> Concept | None:
    label = _clean_label(str(raw.get("label") or ""))
    current = clean_text(str(raw.get("current") or label), limit=260)
    if len(label) < 2 or len(current) < 2:
        return None

    historical_raw = raw.get("historical")
    historical = clean_text(str(historical_raw), limit=300) if historical_raw else ""
    if historical.strip().lower() in {"", "none", "null", "n/a", "unknown"}:
        historical = None

    alternate_names: list[str] = []
    raw_alternates = raw.get("alternate_names")
    if isinstance(raw_alternates, list):
        for item in raw_alternates[:8]:
            cleaned = _clean_label(str(item))
            if cleaned and normalize_title(cleaned) not in {
                normalize_title(name) for name in alternate_names
            }:
                alternate_names.append(cleaned)

    search_terms = list(dict.fromkeys([label, *alternate_names]))
    modern_terms = [current] if len(current.split()) <= 4 else [label, *alternate_names[:3]]
    raw_obsolete = raw.get("obsolete")
    if isinstance(raw_obsolete, str):
        obsolete = raw_obsolete.strip().lower() in {"1", "true", "yes", "obsolete"}
    else:
        obsolete = bool(raw_obsolete)
    return Concept(
        label=label,
        historical=historical,
        current=current,
        alternate_names=alternate_names,
        obsolete=obsolete,
        source="llm",
        search_terms=search_terms,
        modern_terms=modern_terms,
        related_terms=[],
        match_phrases=_match_phrases(label, current, alternate_names, search_terms),
    )


def _topic_chunks(topic: str) -> list[str]:
    chunks: list[str] = []
    for part in _CHUNK_SPLIT_RE.split(topic):
        cleaned = _clean_label(part)
        if not cleaned:
            continue
        if not content_tokens(cleaned):
            continue
        chunks.append(cleaned)
    return chunks


def _concept_from_chunk(chunk: str) -> Concept:
    alternates = _synonym_alternates(chunk)
    label = _clean_label(chunk)
    return Concept(
        label=label,
        historical=None,
        current=label,
        alternate_names=alternates,
        obsolete=False,
        source="heuristic",
        search_terms=list(dict.fromkeys([label, *alternates])),
        modern_terms=list(dict.fromkeys([label, *alternates[:2]])),
        related_terms=[],
        match_phrases=_match_phrases(label, label, alternates, [label, *alternates]),
    )


def _fallback_concept(topic: str, keywords: list[str] | None) -> Concept:
    label = _clean_label(topic)
    if not label:
        label = " ".join((keywords or [])[:4]) or "research topic"
    return Concept(
        label=label,
        historical=None,
        current=label,
        alternate_names=[],
        obsolete=False,
        source="heuristic",
        search_terms=[label],
        modern_terms=[label],
        related_terms=[],
        match_phrases=[label],
    )


def _compact_query(text: str, max_words: int = 18, keep: set[str] | None = None) -> str:
    keep = keep or set()
    words: list[str] = []
    seen: set[str] = set()
    for match in _QUERY_TOKEN_RE.finditer(text):
        word = match.group(0).strip("-'")
        key = word.lower()
        if (
            not word
            or key in seen
            or key in _CONCEPT_IGNORED
            or (key in STOPWORDS and key not in keep)
            or (key in WEAK_WORDS and key not in keep)
        ):
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= max_words:
            break
    return " ".join(words)


def _build_queries(
    topic: str,
    concepts: list[Concept],
    max_queries: int,
) -> list[SearchQuery]:
    queries: list[SearchQuery] = []
    seen: set[str] = set()

    def add(query: str, kind: str, labels: list[str], primary: bool = False) -> None:
        compact = _compact_query(query, keep={"relationship"} if kind == "relationship" else None)
        key = normalize_title(compact)
        if not compact or key in seen:
            return
        seen.add(key)
        queries.append(SearchQuery(query=compact, kind=kind, labels=labels, primary=primary))

    # 1. Modern wording. Obsolete terms use the names that replaced them.
    modern_parts: list[str] = []
    for concept in concepts:
        modern_parts.extend(concept.modern_terms[:4])
    add(" ".join(modern_parts) or topic, "modern", [c.label for c in concepts], True)

    # 2. Historical wording for each obsolete concept.
    for concept in concepts:
        if concept.obsolete:
            add(
                " ".join([concept.label, *concept.related_terms[:4]]),
                "historical",
                [concept.label],
                concept.primary,
            )

    # 3. The relationship between the main concepts.
    if len(concepts) >= 2:
        first, second = concepts[0], concepts[1]
        first_term = first.modern_terms[0] if first.modern_terms else first.label
        add(
            f"{first_term} {second.label} relationship",
            "relationship",
            [first.label, second.label],
        )

    # 4. One query per concept. Secondary concepts first so the budget is spent
    #    on breadth instead of repeating the primary concept.
    ordered = [c for c in concepts if not c.primary] + [c for c in concepts if c.primary]
    for concept in ordered:
        add(
            " ".join([concept.label, *concept.search_terms[:5]]),
            "concept",
            [concept.label],
            concept.primary,
        )

    return queries[: max(1, max_queries)]


def build_concept_plan(
    topic: str,
    keywords: list[str] | None = None,
    llm_concepts: list[dict[str, Any]] | None = None,
    max_concepts: int = 4,
    max_queries: int = 5,
) -> ConceptPlan:
    """Build the concept plan and its separate search queries."""
    topic = clean_text(topic) or " ".join((keywords or [])[:6]).strip()
    normalized_topic = normalize_title(topic)

    concepts: list[Concept] = []
    covered_tokens: set[str] = set()

    for pattern in PATTERNS:
        if not _pattern_matches(pattern, normalized_topic):
            continue
        concept = _concept_from_pattern(pattern)
        if any(_overlaps(concept, existing) for existing in concepts):
            continue
        concepts.append(concept)
        covered_tokens.update(_concept_token_set(concept))

    for item in KNOWLEDGE:
        if not _knowledge_matches(item, normalized_topic):
            continue
        concept = _concept_from_knowledge(item)
        if any(_overlaps(concept, existing) for existing in concepts):
            continue
        concepts.append(concept)
        covered_tokens.update(_concept_token_set(concept))

    for raw in llm_concepts or []:
        if len(concepts) >= max_concepts:
            break
        if not isinstance(raw, dict):
            continue
        concept = _concept_from_llm(raw)
        if concept is None or any(_overlaps(concept, existing) for existing in concepts):
            continue
        concepts.append(concept)
        covered_tokens.update(_concept_token_set(concept))

    # Fill gaps with conservative noun phrases from the topic itself.
    for chunk in _topic_chunks(topic):
        if len(concepts) >= max_concepts:
            break
        chunk_tokens = content_token_set(chunk)
        if not chunk_tokens:
            continue
        # Skip chunks already represented by a curated/LLM concept.
        if chunk_tokens <= covered_tokens or chunk_tokens & covered_tokens:
            continue
        concept = _concept_from_chunk(chunk)
        if any(_overlaps(concept, existing) for existing in concepts):
            continue
        concepts.append(concept)
        covered_tokens.update(_concept_token_set(concept))

    if not concepts:
        concepts.append(_fallback_concept(topic, keywords))

    concepts = concepts[:max_concepts]

    primary = next(
        (c for c in concepts if c.obsolete and c.source == "curated"),
        next((c for c in concepts if c.source == "curated"), None),
    ) or concepts[0]
    for concept in concepts:
        concept.primary = concept is primary

    queries = _build_queries(topic, concepts, max(1, max_queries))
    return ConceptPlan(concepts=concepts, queries=queries)
