"""
Work out *what the student is actually researching* before we hit the APIs.

Two situations are handled:
  * Short input ("why do we feel sleepy when it's hot?"): used as-is. The
    IDF-weighted ranking in ranking.py is what keeps off-topic papers out.
  * Long input (a whole pasted activity / lab brief / rubric): the real topic
    is extracted, with a `Title:` line taking priority, so we search for
    "Taxonomic Classification of Kingdom Monera..." instead of the boilerplate.

If an AI provider is available we let it read the brief and name the topic;
otherwise a transparent local heuristic does the same job.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from app.config import Settings
from app.core.llm import LLMClient

from .concepts import ConceptPlan, build_concept_plan

# Headings that show up in school activities/lab briefs. Used to avoid picking
# a heading as the "topic" and to skip instructional lines.
_SECTION_RE = re.compile(
    r"^(objectives?|background information|background|introduction|materials?|"
    r"safety precautions?|precautions?|procedure|methods?|results? and discussion|"
    r"results?|discussion|post[-\s]?lab(?:oratory)? questions?|guide questions?|"
    r"questions?|conclusion|references?|documentation|title|activity|name|date|"
    r"score|score:|rubric|instructions?|directions?|criteria|pre[-\s]?lab|"
    r"abstract|submitted (?:by|to)|subject|section)\s*[:\-–—]?\s*$",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"^\s*title\s*[:\-–—]\s*(?P<title>.+)$", re.IGNORECASE)
# Lines that merely *start* with a section word ("Activity 1 in Biology 4").
_SECTION_START_RE = re.compile(
    r"^\s*(?:objectives?|background|introduction|materials?|safety|precautions?|"
    r"procedure|methods?|results?|discussion|post[-\s]?lab|guide questions?|"
    r"questions?|conclusion|references?|documentation|activity|name|date|score|"
    r"rubric|instructions?|directions?|criteria|abstract|submitted|subject|section)\b",
    re.IGNORECASE,
)
_NUMBERED_RE = re.compile(r"^\s*\d+\s*[\.\)]\s")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-]{2,}")

# Extra noise words common in assignment prompts (beyond ranking.STOPWORDS).
_EXTRA_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "their", "these", "those",
    "provide", "based", "using", "use", "your", "own", "understand", "knowledge",
    "activity", "title", "objectives", "objective", "background", "information",
    "materials", "material", "procedure", "conclusion", "references", "reference",
    "documentation", "name", "date", "section", "score", "rubric", "instructions",
    "directions", "guide", "questions", "question", "answer", "answers", "different",
    "following", "given", "write", "written", "should", "must", "will", "also",
    "encouraged", "could", "would", "about", "other", "each", "them", "they",
    "this", "that", "which", "when", "where", "what", "why", "how", "does", "did",
    "are", "was", "were", "has", "have", "had", "can", "may", "one", "two", "more",
    "least", "part", "make", "made", "sure", "well", "properly", "orderly",
    # Pronouns / filler that show up in casual questions.
    "its", "it", "we", "you", "our", "your", "i", "feel", "feels", "like",
    "really", "actually", "thing", "things", "someone", "something",
    "get", "gets", "got", "put", "take", "takes", "give", "gives", "become",
    "becomes", "happen", "happens", "occur", "occurs", "want", "need", "know",
}

_SYSTEM_PROMPT = (
    "You are a research librarian helping a student find real papers. Turn the "
    "student's wording into a clear search topic AND a concept plan. If the input "
    "is a casual question, rewrite it into the scientific topic it is really about "
    "(for example, 'why do we feel sleepy when it's hot' becomes 'effects of "
    "ambient temperature on sleepiness and sleep regulation'). If the input is a "
    "pasted assignment brief, use its real subject. "
    "Reply with JSON only, exactly this shape: "
    '{"topic": "3 to 15 word searchable phrase", '
    '"keywords": ["term", "term", "term"], '
    '"concepts": [{"label": "concept name", "historical": "historical meaning or null", '
    '"current": "current meaning or replacement", "alternate_names": ["name", "name"], '
    '"obsolete": false}]}. '
    "Break the topic into 1 to 4 concepts, not just keywords. For every concept give "
    "its historical meaning, its current meaning or replacement, and alternate names. "
    "If a term is obsolete, explain what replaced it and set obsolete to true. "
    "If you are not confident about a historical meaning, use null; never invent dates, "
    "people or claims. Never include assignment words like Activity, Objectives, "
    "Procedure or Materials. No commentary, no markdown, no code fences."
)


@dataclass(slots=True)
class Interpreted:
    """The topic we will actually search for, plus how we found it."""

    topic: str
    keywords: list[str] = field(default_factory=list)
    mode: str = "direct"  # "direct" | "title" | "heuristic" | "llm"
    plan: ConceptPlan = field(default_factory=ConceptPlan)

    @property
    def is_long_paste(self) -> bool:
        return self.mode in {"title", "heuristic", "llm"}

    @property
    def concepts(self) -> list[dict]:
        return self.plan.to_out()

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "keywords": self.keywords,
            "input_mode": self.mode,
            "concepts": self.concepts,
        }


def is_long_input(text: str) -> bool:
    """A pasted assignment is long and/or multi-line; a topic is one short line."""
    stripped = text.strip()
    if len(stripped) > 240:
        return True
    return stripped.count("\n") >= 3


def extract_keywords(text: str, maximum: int = 8) -> list[str]:
    """Significant words from the topic, used for display and for scoring."""
    seen: set[str] = set()
    words: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        word = match.group(0).lower()
        if len(word) < 3 or word in _EXTRA_STOPWORDS or word in seen:
            continue
        seen.add(word)
        words.append(word)
        if len(words) >= maximum:
            break
    return words


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip("\"'“”").strip()
    text = re.sub(r"[.:;,\-–—\s]+$", "", text).strip()
    return text[:300]


def _from_title_line(raw: str) -> str | None:
    for line in raw.splitlines():
        match = _TITLE_RE.match(line)
        if match:
            title = _clean(match.group("title"))
            if len(title.split()) >= 2:
                return title
    return None


def _first_content_line(raw: str) -> str | None:
    for line in raw.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if _SECTION_RE.match(candidate) or _SECTION_START_RE.match(candidate):
            continue
        if _NUMBERED_RE.match(candidate):
            continue
        if candidate.startswith("(") or candidate.endswith(")"):
            continue
        if "provide your" in candidate.lower():
            continue
        if len(candidate.split()) < 3 or len(candidate) > 220:
            continue
        return _clean(candidate)
    return None


def _heuristic(raw: str) -> tuple[str, str]:
    """Return (topic, mode)."""
    title = _from_title_line(raw)
    if title:
        return title, "title"
    line = _first_content_line(raw)
    if line:
        return line, "heuristic"

    # Last resort: squeeze the most meaningful words out of the whole blob.
    keywords = extract_keywords(raw, maximum=10)
    if keywords:
        return " ".join(keywords[:6]), "heuristic"
    return _clean(raw), "heuristic"


def _parse_llm_json(answer: str) -> dict | None:
    text = answer.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _should_use_llm(stripped: str, plan: ConceptPlan) -> bool:
    """Skip AI when our curated plan already covers a short school topic.

    Monera/binomial nomenclature, five kingdoms and the sleep/heat example are
    all covered by curated knowledge. Sending them to a free model adds latency
    without adding historical or modern concepts.
    """
    if is_long_input(stripped):
        return True
    return not any(concept.source == "curated" for concept in plan.concepts)


async def interpret_topic(raw: str, settings: Settings) -> Interpreted:
    stripped = raw.strip()

    # A fast local guess first, so we always have something to search with.
    if is_long_input(stripped):
        topic, mode = _heuristic(stripped)
        keywords = extract_keywords(f"{topic} {stripped}")
    else:
        keywords = extract_keywords(stripped)
        keyword_query = " ".join(keywords[:8])
        # Turning "why do we feel sleepy when its hot" into "sleepy hot" already
        # finds far better papers even with no AI available.
        if len(keywords) >= 2 and keyword_query != stripped.lower():
            topic, mode = keyword_query, "keywords"
        else:
            topic, mode = stripped, "direct"

    # Build the deterministic plan first. For common school topics it is already
    # excellent, so we can skip the model entirely and save its latency/quota.
    initial_plan = build_concept_plan(
        topic,
        keywords,
        max_queries=settings.concept_search_max_queries,
    )

    # If AI is available, let it sharpen the topic and expand the concepts. This
    # is what turns an unknown casual question into a research phrase.
    llm_concepts: list[dict] | None = None
    client = LLMClient(settings)
    if (
        settings.interpret_topic_with_llm
        and client.available
        and _should_use_llm(stripped, initial_plan)
    ):
        try:
            answer = await asyncio.wait_for(
                client.complete(
                    system=_SYSTEM_PROMPT,
                    user=stripped[:6000] + "\n\nReturn the JSON now.",
                    max_tokens=800,
                    temperature=0.0,
                ),
                timeout=settings.llm_interpret_timeout_seconds,
            )
            data = _parse_llm_json(answer)
            if data and isinstance(data.get("topic"), str):
                llm_topic = _clean(data["topic"])
                if 2 <= len(llm_topic.split()) <= 16:
                    topic = llm_topic
                    mode = "llm"
                    raw_keywords = data.get("keywords")
                    if isinstance(raw_keywords, list):
                        cleaned = [
                            str(item).strip().lower()
                            for item in raw_keywords
                            if str(item).strip()
                        ]
                        if cleaned:
                            keywords = cleaned[:8]
                    if not keywords:
                        keywords = extract_keywords(topic)
                    raw_concepts = data.get("concepts")
                    if isinstance(raw_concepts, list):
                        llm_concepts = [item for item in raw_concepts if isinstance(item, dict)]
        except Exception:  # noqa: BLE001 - interpretation must never break search
            pass

    plan = build_concept_plan(
        topic,
        keywords,
        llm_concepts=llm_concepts,
        max_queries=settings.concept_search_max_queries,
    )
    return Interpreted(topic=topic, keywords=keywords, mode=mode, plan=plan)
