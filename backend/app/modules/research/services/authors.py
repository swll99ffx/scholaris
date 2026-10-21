"""
Author-name parsing, validation and cross-provider checks.

The citation styles must not guess at a person's family name. Provider
adapters attach structured ``AuthorName`` values when the API gives us
family/given fields (Crossref, PubMed and, when present, Europe PMC). Flat
display names are parsed only when no structured fields exist, and a parse
that looks suspicious is reported as ``needs_checking`` instead of being
silently trusted.

The module deliberately has no network calls and no LLM fallback.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Iterable, Literal

from .text import clean_text

if TYPE_CHECKING:
    from ..models import SourceRecord

AuthorStatus = Literal["ok", "needs_checking"]

_SUFFIXES = {
    "jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "2nd", "3rd", "4th",
}
_PARTICLES = {
    "al", "bin", "da", "dal", "das", "de", "del", "della", "der", "di", "do",
    "dos", "du", "el", "la", "las", "le", "los", "ten", "ter", "van", "vanden",
    "vander", "von",
}
_CORPORATE_MARKERS = {
    "administration", "agency", "association", "authority", "board", "bureau",
    "center", "centre", "clinic", "collaboration", "collaborative", "college",
    "committee", "commission", "consortium", "cooperative", "council",
    "department", "federation", "foundation", "group", "hospital", "institute",
    "institution", "investigators", "laboratory", "lab", "ministry", "network",
    "office", "organization", "organisation", "panel", "program", "programme",
    "project", "registry", "researchers", "school", "society", "service",
    "survey", "task force", "team", "united nations", "university",
    "working group", "world bank",
}
_CREDENTIALS = {
    "bsc", "dds", "dvm", "edd", "jd", "ma", "mba", "md", "mph", "msc", "phd",
    "prof", "professor", "rn",
}
_HONORIFICS = {"dr", "dr.", "prof", "prof.", "professor"}
_CORPORATE_ACRONYMS = {
    "AAAS", "AMA", "APA", "CDC", "CIOMS", "EPA", "EU", "FDA", "IARC", "ICRC",
    "NASA", "NIH", "NSF", "OECD", "UN", "UNESCO", "UNICEF", "WHO",
}
_NON_AUTHORS = {
    "anonymous", "author", "authors", "editor", "editors", "n/a", "na",
    "unknown",
}
# Uppercase two-letter names are usually initials ("JA", "AB"). These are the
# short surnames we do not want to mislabel, including common CJK/Vietnamese
# romanisations. The list is deliberately conservative; a false warning is
# safer than silently turning initials into a family name.
_SHORT_SURNAMES = {
    "ai", "an", "ba", "do", "du", "fu", "gu", "ha", "he", "ho", "hu", "ji",
    "jo", "ka", "ko", "la", "le", "li", "lo", "lu", "ly", "ma", "mi", "mo",
    "mu", "na", "ne", "ng", "ni", "no", "nu", "oh", "ou", "pa", "po", "pu",
    "qi", "ra", "ri", "ru", "sa", "se", "si", "so", "su", "ta", "te", "ti",
    "to", "tu", "vo", "vu", "wa", "we", "wu", "xi", "xu", "ya", "ye", "yi",
    "yu", "za", "ze", "zo",
}


@dataclass(slots=True)
class AuthorName:
    """One author, preferably with provider-supplied family/given fields."""

    family: str = ""
    given: str = ""
    literal: str = ""
    suffix: str = ""
    orcid: str | None = None
    source: str = ""

    def __post_init__(self) -> None:
        self.family = clean_text(self.family)
        self.given = clean_text(self.given)
        self.literal = clean_text(self.literal)
        self.suffix = normalize_suffix(self.suffix)
        self.orcid = normalize_orcid(self.orcid)
        self.source = clean_text(self.source)

    @property
    def is_literal(self) -> bool:
        return bool(self.literal) and not self.family and not self.given

    def display(self) -> str:
        """Human-facing display only; citations use the structured fields."""
        if self.literal:
            return self.literal
        if not self.family:
            return self.given
        base = f"{self.given} {self.family}".strip() if self.given else self.family
        return f"{base} {self.suffix}".strip() if self.suffix else base


@dataclass(slots=True)
class AuthorCheck:
    """Whether the author names are safe to cite without a warning."""

    status: AuthorStatus = "ok"
    reason: str = ""
    conflicts: list[str] = field(default_factory=list)


def normalize_orcid(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"(\d{4}-\d{4}-\d{4}-[\dXx]{4})", text)
    return match.group(1).upper() if match else text


def normalize_suffix(value: str | None) -> str:
    text = clean_text(value).strip(" ,")
    if not text:
        return ""
    lowered = text.casefold().rstrip(".")
    if lowered in {"jr", "sr"}:
        return f"{lowered.title()}."
    if lowered in {"ii", "iii", "iv"}:
        return lowered.upper()
    return text


def initials(given: str) -> str:
    """'Jean-Luc Marie' -> 'J.-L. M.'; compact 'JA' -> 'J. A.'."""
    text = clean_text(given)
    if not text:
        return ""
    output: list[str] = []
    for chunk in re.split(r"\s+", text):
        chunk = chunk.strip(",;")
        if not chunk:
            continue
        if "-" in chunk:
            letters: list[str] = []
            for part in chunk.split("-"):
                part_letters = re.sub(r"[^A-Za-z]", "", part)
                if not part_letters:
                    continue
                if len(part_letters) <= 3 and part_letters.isupper() and "." not in part:
                    letters.extend(letter.upper() for letter in part_letters)
                else:
                    letters.append(part_letters[0].upper())
            if letters:
                output.append("-".join(f"{letter}." for letter in letters))
            continue

        letters = re.sub(r"[^A-Za-z]", "", chunk)
        if not letters:
            continue
        if "." in chunk and len(letters) <= 4:
            output.extend(f"{letter.upper()}." for letter in letters)
        elif letters.isupper() and 2 <= len(letters) <= 3:
            output.extend(f"{letter.upper()}." for letter in letters)
        else:
            output.append(f"{letters[0].upper()}.")
    return " ".join(output)


def _is_suffix(value: str) -> bool:
    return value.strip().casefold() in _SUFFIXES


def _is_initials_token(value: str) -> bool:
    """True for tokens like J, J., JA, J.A., or J-A."""
    text = clean_text(value)
    if not text:
        return False
    letters = re.sub(r"[^A-Za-z]", "", text)
    if not letters:
        return False
    if "." in text and len(letters) <= 3:
        return True
    if "-" in text and len(letters) <= 3:
        return True
    if len(letters) <= 3 and text.isupper():
        # A trailing "LI" is more likely a Chinese surname than initials.
        if len(letters) == 2 and letters.casefold() in _SHORT_SURNAMES:
            return False
        return True
    return False


def _looks_corporate(name: str) -> bool:
    text = clean_text(name)
    if not text:
        return False
    if text.upper() in _CORPORATE_ACRONYMS:
        return True
    lowered = f" {text.casefold()} "
    for marker in _CORPORATE_MARKERS:
        if f" {marker} " in lowered:
            return True
    return False


def _letters_only(value: str) -> str:
    return "".join(character for character in clean_text(value) if character.isalpha())


def _is_credential(value: str) -> bool:
    text = clean_text(value).strip(" ,")
    if not text:
        return False
    key = text.casefold().rstrip(".")
    if key not in _CREDENTIALS:
        return False
    # "Ma" is a common given name; only a capitalised/dotted form is a degree.
    return text.isupper() or "." in text or key not in {"ma"}


def _looks_incomplete_literal(value: str) -> bool:
    text = clean_text(value)
    lowered = text.casefold()
    if not text or lowered in _NON_AUTHORS:
        return True
    if text.upper() in _CORPORATE_ACRONYMS:
        return False
    if "et al" in lowered:
        return True
    letters = _letters_only(text)
    if letters and not any(character.isascii() for character in letters):
        return False
    if len(letters) <= 1:
        return True
    if re.fullmatch(r"(?:[A-Za-z]\.?\s*){1,4}", text):
        return True
    return False


def _looks_like_initials_surname(family: str) -> bool:
    text = clean_text(family)
    if not text:
        return True
    letters = _letters_only(text)
    if not letters:
        return True
    if not any(character.isascii() for character in letters):
        # A Chinese/Arabic/etc. family name is not a Latin initial.
        return False
    if len(letters) == 1:
        return True
    if "." in text and len(letters) <= 3:
        return True
    if " " in text and all(_is_initials_token(token) for token in text.split()):
        return True
    if text.isupper() and len(letters) <= 2:
        return letters.casefold() not in _SHORT_SURNAMES
    return False


def _split_comma_name(name: str, *, source: str) -> AuthorName:
    parts = [part.strip() for part in name.split(",") if part.strip()]
    while len(parts) > 1 and _is_credential(parts[-1]):
        parts.pop()
    if len(parts) == 1:
        return parse_flat_name(parts[0], source=source)
    if len(parts) == 2 and _is_suffix(parts[1]):
        detail = parse_flat_name(parts[0], source=source)
        detail.suffix = normalize_suffix(parts[1])
        return detail

    family = parts[0] if parts else ""
    given = parts[1] if len(parts) >= 2 else ""
    suffix = ""

    if len(parts) >= 3 and _is_suffix(parts[2]):
        suffix = parts[2]

    family_tokens = family.split()
    if len(family_tokens) >= 2 and _is_suffix(family_tokens[-1]):
        suffix = suffix or family_tokens[-1]
        family = " ".join(family_tokens[:-1])

    given_tokens = [
        token for token in given.split() if token.casefold() not in _HONORIFICS
    ]
    if given_tokens and _is_suffix(given_tokens[-1]):
        suffix = suffix or given_tokens[-1]
        given_tokens = given_tokens[:-1]
    given = " ".join(given_tokens)

    if not family and given:
        family, given = given, ""
    return AuthorName(family=family, given=given, suffix=suffix, source=source)


def parse_flat_name(name: str, *, source: str = "") -> AuthorName:
    """Parse a flat provider display name without inventing missing fields."""
    text = clean_text(name)
    if not text:
        return AuthorName(source=source)

    lowered = text.casefold()
    if "et al" in lowered or lowered in _NON_AUTHORS:
        return AuthorName(literal=text, source=source)
    if _looks_corporate(text):
        return AuthorName(literal=text, source=source)

    tokens = text.split()
    while tokens and tokens[0].casefold() in _HONORIFICS:
        tokens.pop(0)
    if not tokens:
        return AuthorName(literal=text, source=source)
    text = " ".join(tokens)

    if "," in text:
        return _split_comma_name(text, source=source)

    if len(tokens) == 1:
        return AuthorName(family=tokens[0], source=source)

    suffix = ""
    if len(tokens) >= 3 and _is_suffix(tokens[-1]):
        suffix = tokens[-1]
        tokens = tokens[:-1]

    # "Smith J. A." / "van der Waals J. D.": family first, initials last.
    split_at = len(tokens)
    while split_at > 1 and _is_initials_token(tokens[split_at - 1]):
        split_at -= 1
    if split_at < len(tokens):
        family = " ".join(tokens[:split_at]).strip()
        given = " ".join(tokens[split_at:]).strip()
        if family:
            return AuthorName(family=family, given=given, suffix=suffix, source=source)

    # "Ludwig van Beethoven" / "Maria de la Cruz": lowercase particles belong
    # to the family name, while the preceding words are given names.
    family_start = len(tokens) - 1
    while family_start > 0 and tokens[family_start - 1].casefold() in _PARTICLES:
        family_start -= 1
    family = " ".join(tokens[family_start:]).strip()
    given = " ".join(tokens[:family_start]).strip()
    return AuthorName(family=family, given=given, suffix=suffix, source=source)


def parse_flat_authors(names: Iterable[str], *, source: str = "") -> list[AuthorName]:
    details: list[AuthorName] = []
    for name in names:
        cleaned = clean_text(name)
        if not cleaned:
            continue
        # A few providers occasionally pack several names into one semicolon
        # separated string. Commas are left alone because they may be part of
        # a "Family, Given" name.
        pieces = [piece.strip() for piece in re.split(r"\s*;\s*", cleaned) if piece.strip()]
        for piece in pieces:
            details.append(parse_flat_name(piece, source=source))
    return details


def display_authors(details: Iterable[AuthorName]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for detail in details:
        label = detail.display()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            result.append(label)
    return result


def validate_author_names(
    details: Iterable[AuthorName],
    *,
    display_names: Iterable[str] | None = None,
) -> AuthorCheck:
    """Flag obvious parse failures without silently repairing a name."""
    authors = [detail for detail in details if detail]
    conflicts: list[str] = []

    for index, author in enumerate(authors, 1):
        if author.literal:
            if _looks_incomplete_literal(author.literal):
                conflicts.append(
                    f"Author {index} is incomplete or only initials: {author.literal!r}."
                )
            continue

        family = clean_text(author.family)
        given = clean_text(author.given)
        if not family and not given:
            conflicts.append(f"Author {index} has no usable name.")
            continue
        if not family:
            conflicts.append(
                f"Author {index} has a given name but no family name: {given!r}."
            )
            continue
        if _looks_like_initials_surname(family):
            conflicts.append(
                f"Author {index} looks like initials, not a surname: {family!r}."
            )

    names = [clean_text(name) for name in (display_names or []) if clean_text(name)]
    if any("et al" in name.casefold() for name in names):
        conflicts.append("The author list is abbreviated with 'et al.'.")

    unique_conflicts: list[str] = []
    for conflict in conflicts:
        if conflict not in unique_conflicts:
            unique_conflicts.append(conflict)
    if not unique_conflicts:
        return AuthorCheck()
    return AuthorCheck(
        status="needs_checking",
        reason=" ".join(unique_conflicts[:3]),
        conflicts=unique_conflicts,
    )


def combine_author_checks(*checks: AuthorCheck | None) -> AuthorCheck:
    existing = [check for check in checks if check is not None]
    conflicts: list[str] = []
    reasons: list[str] = []
    needs_checking = False
    for check in existing:
        if check.status == "needs_checking":
            needs_checking = True
        if check.reason and check.reason not in reasons:
            reasons.append(check.reason)
        for conflict in check.conflicts:
            if conflict not in conflicts:
                conflicts.append(conflict)
    if not needs_checking:
        return AuthorCheck()
    return AuthorCheck(
        status="needs_checking",
        reason=" ".join(reasons[:3]),
        conflicts=conflicts,
    )


def _comparison_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    # Some providers use a Turkish dotless i as the base for "í"/"î". Treat it
    # like an ordinary i for comparison so "Vı́ctor" and "Victor" agree.
    text = text.casefold().replace("\u0131", "i").replace("&", " and ")
    # Keep non-Latin letters. A Chinese or Arabic family name still needs to
    # compare correctly even though it has no ASCII form.
    text = "".join(
        character if character.isalnum() else " " for character in text
    )
    return re.sub(r"\s+", " ", text).strip()


def _family_variants(family: str) -> set[str]:
    normalized = _comparison_text(family)
    if not normalized:
        return {""}
    tokens = normalized.split()
    variants = {normalized}
    without_particles = [token for token in tokens if token not in _PARTICLES]
    if without_particles and len(without_particles) != len(tokens):
        variants.add(" ".join(without_particles))
    return variants


def _given_parts(given: str) -> list[str]:
    text = unicodedata.normalize("NFKD", clean_text(given))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("\u0131", "i")
    # Hyphens, apostrophes and Unicode dashes are all name separators. Splitting
    # on only ASCII "-" made "Hans\u2010Peter" disagree with "Hans-Peter".
    text = "".join(character if character.isalnum() else " " for character in text)
    parts: list[str] = []
    for chunk in text.split():
        if len(chunk) == 1:
            parts.append(chunk.casefold())
        elif chunk.isupper() and 2 <= len(chunk) <= 3:
            parts.extend(letter.casefold() for letter in chunk)
        else:
            parts.append(chunk.casefold())
    return parts


def _given_matches(first: str, second: str) -> bool:
    left = _given_parts(first)
    right = _given_parts(second)
    if not left or not right:
        return True
    for left_part, right_part in zip(left, right):
        if left_part[0] != right_part[0]:
            return False
        if len(left_part) > 1 and len(right_part) > 1 and left_part != right_part:
            return False
    return True


def names_match(first: AuthorName, second: AuthorName) -> bool:
    # Providers split compound names differently (for example "Estrada-de los
    # Santos" vs a flat "Estrada-de los Santos"). If the complete names agree
    # after punctuation/case/accent normalisation, the split is not a conflict.
    first_full = _comparison_text(first.literal or first.display())
    second_full = _comparison_text(second.literal or second.display())
    if first_full and first_full == second_full:
        return True

    if first.literal and second.literal:
        return _comparison_text(first.literal) == _comparison_text(second.literal)
    if first.literal or second.literal:
        literal = first.literal or second.literal
        person = second if first.literal else first
        return _comparison_text(literal) == _comparison_text(person.display())

    if not first.family and not second.family:
        return _given_matches(first.given, second.given)
    if not first.family or not second.family:
        return False
    if not (_family_variants(first.family) & _family_variants(second.family)):
        return False
    if first.suffix and second.suffix:
        if first.suffix.casefold() != second.suffix.casefold():
            return False
    return _given_matches(first.given, second.given)


def compare_author_lists(
    first: Iterable[AuthorName],
    second: Iterable[AuthorName],
) -> list[str]:
    """Compare overlapping author positions; truncated lists are allowed."""
    left = [author for author in first if author]
    right = [author for author in second if author]
    if not left or not right:
        return []
    conflicts: list[str] = []
    for index, (left_author, right_author) in enumerate(zip(left, right), 1):
        if names_match(left_author, right_author):
            continue
        left_label = left_author.display() or "(unknown)"
        right_label = right_author.display() or "(unknown)"
        # Canonical order lets repeated multi-provider merges deduplicate the
        # same disagreement instead of storing it once in each direction.
        if right_label.casefold() < left_label.casefold():
            left_label, right_label = right_label, left_label
        conflicts.append(f"#{index}: {left_label} vs {right_label}.")
    return conflicts


def ensure_author_details(record: "SourceRecord") -> list[AuthorName]:
    details = [detail for detail in (getattr(record, "author_details", None) or []) if detail]
    if details:
        return details
    providers = list(getattr(record, "providers", None) or [])
    source = providers[0] if providers else ""
    return parse_flat_authors(getattr(record, "authors", None) or [], source=source)


def ensure_author_check(record: "SourceRecord") -> AuthorCheck:
    details = ensure_author_details(record)
    own_check = validate_author_names(
        details,
        display_names=getattr(record, "authors", None) or [],
    )
    stored = getattr(record, "author_check", None)
    return combine_author_checks(stored, own_check)


def set_record_authors(
    record: "SourceRecord",
    details: Iterable[AuthorName],
    *,
    display_names: Iterable[str] | None = None,
) -> None:
    record.author_details = [detail for detail in details if detail]
    if display_names is None:
        record.authors = display_authors(record.author_details)
    else:
        cleaned = [clean_text(name) for name in display_names if clean_text(name)]
        record.authors = list(dict.fromkeys(cleaned))
    record.author_check = validate_author_names(
        record.author_details,
        display_names=record.authors,
    )


def attach_flat_authors(record: "SourceRecord", names: Iterable[str], *, source: str) -> None:
    cleaned = list(dict.fromkeys(clean_text(name) for name in names if clean_text(name)))
    details = parse_flat_authors(cleaned, source=source)
    set_record_authors(record, details, display_names=cleaned)


def _author_quality(details: list[AuthorName]) -> tuple[int, int]:
    full_names = sum(1 for author in details if author.family and author.given)
    return len(details), full_names


def _enrich_orcids(preferred: list[AuthorName], secondary: list[AuthorName]) -> list[AuthorName]:
    enriched: list[AuthorName] = []
    for author in preferred:
        match = next(
            (
                candidate
                for candidate in secondary
                if candidate.orcid
                and names_match(author, candidate)
            ),
            None,
        )
        enriched.append(replace(author, orcid=match.orcid) if match else author)
    return enriched


def merge_author_details(
    first: Iterable[AuthorName],
    second: Iterable[AuthorName],
    *,
    prefer_second: bool = False,
    first_check: AuthorCheck | None = None,
    second_check: AuthorCheck | None = None,
    first_source: str = "",
    second_source: str = "",
) -> tuple[list[AuthorName], AuthorCheck]:
    """Choose the more complete author list and flag provider disagreements."""
    first_details = [author for author in first if author]
    second_details = [author for author in second if author]

    if not first_details and not second_details:
        return [], combine_author_checks(first_check, second_check)
    if not first_details:
        preferred, secondary = second_details, first_details
    elif not second_details:
        preferred, secondary = first_details, second_details
    else:
        first_quality = _author_quality(first_details)
        second_quality = _author_quality(second_details)
        if second_quality > first_quality or (
            second_quality == first_quality and prefer_second
        ):
            preferred, secondary = second_details, first_details
        else:
            preferred, secondary = first_details, second_details

    preferred = [replace(author) for author in preferred]
    preferred = _enrich_orcids(preferred, secondary)

    conflicts = compare_author_lists(first_details, second_details)
    check = combine_author_checks(
        first_check,
        second_check,
        validate_author_names(preferred, display_names=display_authors(preferred)),
    )
    new_conflicts = [conflict for conflict in conflicts if conflict not in check.conflicts]
    if new_conflicts:
        sources = [source for source in (first_source, second_source) if source]
        source_text = " and ".join(dict.fromkeys(sources)) or "provider records"
        detail = "; ".join(new_conflicts[:3])
        check = combine_author_checks(
            check,
            AuthorCheck(
                status="needs_checking",
                reason=f"Author names disagree between {source_text}: {detail}",
                conflicts=new_conflicts,
            ),
        )
    return preferred, check
