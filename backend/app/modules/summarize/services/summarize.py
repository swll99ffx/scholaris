"""
Structured summaries for Module 2.

Two tiers, matching Module 1's philosophy:
  1. A deterministic, extractive summary that always works offline.
  2. An AI summary (strict JSON) when a provider is available.

The AI is never allowed to invent quotes: it returns sentence numbers and we
look those sentences up in the original text, so every quote is verbatim and
keeps its PDF page number.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.llm import LLMClient

from .extract import Document, Sentence, remove_citations

_METHOD_CUES = re.compile(
    r"\b(?:we|authors?|researchers?|investigators?)\s+"
    r"(?:used|use|conducted|collected|measured|recruited|surveyed|interviewed|"
    r"analy[sz]ed|tested|randomi[sz]ed|administered|applied|compared|modelled|modeled)\b"
    r"|\b(?:method|methods|methodology|procedure|participants?|sample|dataset|data set|"
    r"experiment|experiments|survey|questionnaire|interviews?|trial|regression|"
    r"systematic review|meta-analysis|sample size)\b",
    re.IGNORECASE,
)
_FINDING_CUES = re.compile(
    r"\b(?:results?|findings?|showed|show that|shows that|found|revealed|indicated|"
    r"demonstrated|suggests?|concluded?|conclusions?|associated with|correlat\w*|"
    r"significantly|increased|decreased|improved|reduced|higher|lower|"
    r"effective|effect|impact|outcome)\b",
    re.IGNORECASE,
)
_LIMITATION_CUES = re.compile(
    r"\b(?:limitations?|limited|caveat|weakness|small sample|future (?:research|studies)|"
    r"further (?:research|studies)|generaliz\w*|cannot|can't|may not|did not|"
    r"only \d+|however|caution)\b",
    re.IGNORECASE,
)
_CITATION_YEAR_RE = re.compile(r"\s*\((?:[A-Z][^()]{0,80}?,\s*)?(?:19|20)\d{2}[a-z]?\)")
_INLINE_NUMBER = re.compile(r"\d+(?:\.\d+)?")

_SYSTEM_PROMPTS = {
    "academic": (
        "You are a careful academic study assistant. Summarize the source for a student "
        "using ONLY the numbered sentences supplied. Never add facts, numbers or claims "
        "that are not in the text. Write plain English. Return one JSON object and nothing "
        "else."
    ),
    "plain": (
        "You are a patient tutor explaining a research paper to a curious secondary-school "
        "student. Use plain, everyday English and short sentences. When a technical term is "
        "unavoidable, explain it briefly in parentheses. Summarize using ONLY the numbered "
        "sentences supplied. Never add facts, numbers or claims that are not in the text. "
        "Return one JSON object and nothing else."
    ),
}


@dataclass(frozen=True, slots=True)
class _DetailProfile:
    """How much the AI (and the offline fallback) should write."""

    max_tokens: int
    tldr_words: int
    key_min: int
    key_max: int
    methods_max: int
    findings_max: int
    limitations_max: int


_DETAIL_PROFILES = {
    "quick": _DetailProfile(550, 35, 2, 3, 2, 2, 2),
    "standard": _DetailProfile(900, 45, 3, 5, 3, 3, 3),
    "deep": _DetailProfile(1500, 70, 4, 6, 4, 4, 4),
}

# Offline limits: (key points, methods, findings, limitations). "standard"
# matches the original v1.0 output exactly.
_HEURISTIC_LIMITS = {
    "quick": (3, 2, 2, 2),
    "standard": (4, 3, 3, 2),
    "deep": (5, 3, 4, 3),
}

# The offline TL;DR keeps the v1.0 allowance for "standard".
_HEURISTIC_TLDR_WORDS = {"quick": 35, "standard": 55, "deep": 70}


def _profile(detail: str) -> _DetailProfile:
    return _DETAIL_PROFILES.get(detail, _DETAIL_PROFILES["standard"])


def _heuristic_limits(detail: str) -> tuple[int, int, int, int]:
    return _HEURISTIC_LIMITS.get(detail, _HEURISTIC_LIMITS["standard"])


@dataclass(slots=True)
class Draft:
    tldr: str
    key_points: list[str]
    methods: list[str]
    findings: list[str]
    limitations: list[str]
    quote_indices: list[int]
    ai_source: str = "heuristic"
    warnings: list[str] = field(default_factory=list)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _tokens(text: str) -> set[str]:
    return {word for word in _words(text) if len(word) > 3}


def _similar(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.7


def _display(text: str, limit: int = 320) -> str:
    """Clean a sentence for a summary bullet, keeping it verbatim in meaning."""
    text = remove_citations(text)
    text = _CITATION_YEAR_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        if "." in cut[60:]:
            cut = cut[: cut.rfind(".") + 1]
        text = cut.rstrip() + " …"
    return text


def _score(sentence: Sentence, cue: re.Pattern[str] | None, position: int) -> float:
    words = len(sentence.text.split())
    if words < 5:
        return 0.0
    score = 0.0
    if 7 <= words <= 42:
        score += 1.4
    elif 43 <= words <= 60:
        score += 0.6
    elif words > 70:
        score -= 0.8
    if cue is not None:
        score += min(2.0 * len(cue.findall(sentence.text)), 4.0)
    if _INLINE_NUMBER.search(sentence.text):
        score += 0.7
    if position < 3:
        score += 0.5
    if sentence.page is not None:
        score += 0.1
    return score


def _quote_score(sentence: Sentence, position: int) -> float:
    score = _score(sentence, _FINDING_CUES, position)
    if _FINDING_CUES.search(sentence.text):
        score += 0.9
    words = len(sentence.text.split())
    if 8 <= words <= 32:
        score += 0.8
    # Quotes should stand alone, not start with a bare connective.
    if re.match(r"^(however|therefore|thus|moreover|also|and|but)\b", sentence.text, re.I):
        score -= 0.5
    if "%" in sentence.text:
        score += 0.5
    return score


def _pick(
    candidates: list[tuple[float, Sentence]],
    used: set[int],
    limit: int,
) -> list[Sentence]:
    chosen: list[Sentence] = []
    for _, sentence in sorted(candidates, key=lambda item: item[0], reverse=True):
        if sentence.index in used:
            continue
        if any(_similar(sentence.text, other.text) for other in chosen):
            continue
        chosen.append(sentence)
        used.add(sentence.index)
        if len(chosen) >= limit:
            break
    return sorted(chosen, key=lambda sentence: sentence.index)


def heuristic_draft(document: Document, quote_count: int = 3, detail: str = "standard") -> Draft:
    sentences = document.sentences
    if not sentences:
        raise ValueError("There are no sentences to summarize.")

    key_limit, method_limit, finding_limit, limitation_limit = _heuristic_limits(detail)

    method_candidates: list[tuple[float, Sentence]] = []
    finding_candidates: list[tuple[float, Sentence]] = []
    limitation_candidates: list[tuple[float, Sentence]] = []
    other_candidates: list[tuple[float, Sentence]] = []

    for position, sentence in enumerate(sentences):
        method = _score(sentence, _METHOD_CUES, position) if _METHOD_CUES.search(sentence.text) else 0.0
        finding = _score(sentence, _FINDING_CUES, position) if _FINDING_CUES.search(sentence.text) else 0.0
        limitation = (
            _score(sentence, _LIMITATION_CUES, position)
            if _LIMITATION_CUES.search(sentence.text)
            else 0.0
        )
        best = max(method, finding, limitation)
        if best >= 2.0:
            if best == limitation:
                limitation_candidates.append((limitation + 0.3, sentence))
            elif best == finding:
                finding_candidates.append((finding, sentence))
            else:
                method_candidates.append((method, sentence))
        else:
            other_candidates.append((_score(sentence, None, position), sentence))

    used: set[int] = set()
    methods = _pick(method_candidates, used, method_limit)
    limitations = _pick(limitation_candidates, used, limitation_limit)
    findings = _pick(finding_candidates, used, finding_limit)

    # Key points: context/aim sentences first. If the abstract is very short,
    # fall back to the strongest findings so the section is never empty.
    key_pool = other_candidates or finding_candidates or [
        (_score(sentence, None, position), sentence) for position, sentence in enumerate(sentences)
    ]
    key_points = _pick(key_pool, used, key_limit)

    if not findings:
        # No explicit results cue: use the best remaining informative sentences.
        fallback = [
            (_score(sentence, None, position), sentence)
            for position, sentence in enumerate(sentences)
            if sentence.index not in used
        ]
        findings = _pick(fallback, used, min(2, finding_limit))

    if not key_points:
        key_points = _pick(
            [
                (_score(sentence, None, position), sentence)
                for position, sentence in enumerate(sentences)
            ],
            set(),
            2,
        )

    tldr_source = (findings or key_points or sentences)[:2]
    tldr = _tldr(
        " ".join(sentence.text for sentence in tldr_source),
        _HEURISTIC_TLDR_WORDS.get(detail, 55),
    )

    quote_pool = [
        (_quote_score(sentence, position), sentence)
        for position, sentence in enumerate(sentences)
    ]
    quote_sentences: list[Sentence] = []
    for _, sentence in sorted(quote_pool, key=lambda item: item[0], reverse=True):
        if len(quote_sentences) >= quote_count:
            break
        if _score(sentence, None, sentence.index) <= 0:
            continue
        if any(_similar(sentence.text, other.text) for other in quote_sentences):
            continue
        quote_sentences.append(sentence)
    quote_sentences.sort(key=lambda sentence: sentence.index)

    return Draft(
        tldr=tldr,
        key_points=[_display(sentence.text) for sentence in key_points],
        methods=[_display(sentence.text) for sentence in methods],
        findings=[_display(sentence.text) for sentence in findings],
        limitations=[_display(sentence.text) for sentence in limitations],
        quote_indices=[sentence.index for sentence in quote_sentences],
        warnings=list(document.warnings),
    )


def _tldr(text: str, limit: int = 55) -> str:
    text = _display(text, 520)
    words = text.split()
    if len(words) > limit:
        text = " ".join(words[:limit]).rstrip(",;:") + " …"
    return text


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _string_list(value: Any, limit: int, max_chars: int = 320) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        cleaned = re.sub(r"\s{2,}", " ", entry).strip().lstrip("-• ").strip()
        cleaned = re.sub(r"^\(?\d+[.)]\s*", "", cleaned)
        cleaned = cleaned.replace("**", "").strip()
        if not cleaned:
            continue
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rstrip() + " …"
        items.append(cleaned)
        if len(items) >= limit:
            break
    return items


def _draft_from_llm(
    answer: str,
    document: Document,
    quote_count: int,
    detail: str = "standard",
) -> Draft | None:
    data = _extract_json(answer)
    if data is None:
        return None

    tldr = data.get("tldr")
    if not isinstance(tldr, str) or not tldr.strip():
        return None
    tldr = re.sub(r"\s+", " ", tldr).strip()
    if len(tldr) > 600:
        tldr = tldr[:600].rstrip() + " …"

    profile = _profile(detail)
    key_points = _string_list(data.get("key_points"), profile.key_max)
    methods = _string_list(data.get("methods"), profile.methods_max)
    findings = _string_list(data.get("findings"), profile.findings_max)
    limitations = _string_list(data.get("limitations"), profile.limitations_max)
    if not any((key_points, methods, findings, limitations)):
        return None

    indices: list[int] = []
    raw_quotes = data.get("quotes")
    if isinstance(raw_quotes, list):
        for entry in raw_quotes:
            if isinstance(entry, bool):
                continue
            if isinstance(entry, int):
                position = entry
            elif isinstance(entry, str) and entry.strip().isdigit():
                position = int(entry.strip())
            else:
                continue
            # Prompt numbers start at 1; only sentences we actually sent are valid.
            if 1 <= position <= len(document.sentences):
                index = document.sentences[position - 1].index
                if index not in indices:
                    indices.append(index)
    if len(indices) > quote_count:
        indices = indices[:quote_count]

    return Draft(
        tldr=tldr,
        key_points=key_points,
        methods=methods,
        findings=findings,
        limitations=limitations,
        quote_indices=indices,
        ai_source="llm",
        warnings=list(document.warnings),
    )


def _prompt(document: Document, settings: Settings) -> tuple[str, int]:
    lines: list[str] = []
    used_chars = 0
    budget = max(2000, settings.summarize_llm_max_chars)
    sent = 0
    for position, sentence in enumerate(document.sentences[: settings.summarize_llm_max_sentences], start=1):
        line = f"[{position}] {sentence.text}"
        if used_chars + len(line) > budget:
            break
        lines.append(line)
        used_chars += len(line)
        sent = position
    return "\n".join(lines), sent


def _json_spec(detail: str, quote_count: int) -> str:
    profile = _profile(detail)
    quote_spec = (
        f'"quotes": [sentence numbers, 2-{quote_count} of them]'
        if quote_count
        else '"quotes": []'
    )
    return (
        "Return JSON with exactly these keys:\n"
        f'{{"tldr": "one plain-English summary, max {profile.tldr_words} words", '
        f'"key_points": ["{profile.key_min}-{profile.key_max} short main ideas"], '
        f'"methods": ["how the study was done, 0-{profile.methods_max} items"], '
        f'"findings": ["what it found, 0-{profile.findings_max} items"], '
        f'"limitations": ["only limitations actually stated, 0-{profile.limitations_max} items"], '
        f"{quote_spec}}}\n\n"
        "Rules: use only the sentences above; do not invent numbers or claims; "
        "write short phrases, not paragraphs; quote numbers must be the [number] labels. "
        "If a section is not stated in the text, use an empty list."
    )


async def _llm_draft(
    document: Document,
    source_title: str,
    settings: Settings,
    quote_count: int,
    detail: str = "standard",
    mode: str = "academic",
) -> tuple[Draft | None, str]:
    """
    Ask the AI for a draft.

    Returns ``(draft, failure)`` where failure is ``""`` on success,
    ``"unavailable"`` when no provider answered, and ``"malformed"`` when the
    provider answered but neither attempt was valid JSON.
    """
    client = LLMClient(settings)
    if not client.available:
        return None, "unavailable"

    numbered, sent = _prompt(document, settings)
    if sent == 0:
        return None, "unavailable"

    profile = _profile(detail)
    system = _SYSTEM_PROMPTS.get(mode, _SYSTEM_PROMPTS["academic"])
    user = (
        f"Paper title: {source_title or 'unknown'}\n\n"
        f"Numbered sentences from the source:\n{numbered}\n\n"
        f"{_json_spec(detail, quote_count)}"
    )
    try:
        answer = await asyncio.wait_for(
            client.complete(
                system=system,
                user=user,
                max_tokens=profile.max_tokens,
                temperature=0.1,
            ),
            timeout=settings.summarize_llm_timeout_seconds,
        )
    except Exception:  # noqa: BLE001 - AI is a bonus; offline summary still works
        return None, "unavailable"

    draft = _draft_from_llm(answer, document, quote_count, detail)
    if draft is not None:
        return draft, ""

    # One repair attempt: free providers sometimes wrap JSON in prose or cut it
    # off. Re-ask with a low temperature and an explicit reminder.
    repair_user = (
        f"{user}\n\n"
        "Your previous answer was not valid JSON. Return ONLY the JSON object now — "
        "no code fences, no explanation, no trailing text."
    )
    try:
        answer = await asyncio.wait_for(
            client.complete(
                system=system,
                user=repair_user,
                max_tokens=profile.max_tokens,
                temperature=0.0,
            ),
            timeout=settings.summarize_llm_timeout_seconds,
        )
    except Exception:  # noqa: BLE001 - fall back to the offline summary
        return None, "malformed"

    draft = _draft_from_llm(answer, document, quote_count, detail)
    if draft is not None:
        draft.warnings.append(
            "The AI's first reply was not valid JSON, so it was asked once more."
        )
        return draft, ""
    return None, "malformed"


async def summarize_document(
    document: Document,
    *,
    source_title: str,
    settings: Settings,
    quote_count: int = 3,
    detail: str = "standard",
    mode: str = "academic",
) -> tuple[Draft, str]:
    """Return the best available draft and whether AI was used."""
    heuristic = heuristic_draft(document, quote_count=quote_count, detail=detail)
    if not settings.summarize_with_llm:
        return heuristic, "heuristic"

    draft, failure = await _llm_draft(
        document,
        source_title,
        settings,
        quote_count,
        detail=detail,
        mode=mode,
    )
    if draft is None:
        if failure == "malformed":
            heuristic.warnings.append(
                "The AI's reply could not be read, so this summary was built offline from your text."
            )
        elif settings.llm_available:
            heuristic.warnings.append(
                "The AI was unavailable, so this summary was built offline from your text."
            )
        return heuristic, "heuristic"

    # The AI sometimes returns no quotes (or fewer than requested). Top up with
    # the heuristic's verbatim picks so the quote finder is always useful.
    if quote_count > 0 and len(draft.quote_indices) < quote_count:
        chosen = list(draft.quote_indices)
        for index in heuristic.quote_indices:
            if len(chosen) >= quote_count:
                break
            if index not in chosen:
                chosen.append(index)
        draft.quote_indices = chosen[:quote_count]
    return draft, "llm"


# ------------------------------------------------------------------ formatting


def quote_text(document: Document, index: int) -> Sentence | None:
    for sentence in document.sentences:
        if sentence.index == index:
            return sentence
    return None


def format_notes(summary: dict[str, Any]) -> str:
    """Render a summary as the notes block saved into the library."""
    from datetime import date

    source = summary.get("source") or {}
    lines = [f"SUMMARY — {date.today().isoformat()} ({summary.get('ai_source', 'heuristic')})"]
    if source.get("title"):
        lines.append(f"Source: {source['title']}")
    lines += ["", f"TL;DR: {summary.get('tldr', '')}"]

    sections = (
        ("Key points", summary.get("key_points") or []),
        ("Methods", summary.get("methods") or []),
        ("Findings", summary.get("findings") or []),
        ("Limitations", summary.get("limitations") or []),
    )
    for label, items in sections:
        if not items:
            continue
        lines += ["", f"{label}:"]
        lines.extend(f"- {item}" for item in items)

    quotes = summary.get("quotes") or []
    if quotes:
        lines += ["", "Quotes:"]
        for quote in quotes:
            page = quote.get("page")
            where = f" (p. {page})" if page else ""
            lines.append(f'- "{quote.get("text", "")}"{where}')

    return "\n".join(lines).strip()
