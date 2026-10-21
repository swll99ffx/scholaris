"""
Small, curated synonym map for obsolete and textbook-only terms.

School activities still say "Kingdom Monera" and "binomial nomenclature", but
real (modern) papers say "prokaryote", "bacteria" and "taxonomy". Without this
the search would return papers that merely share a generic word with the query.

The map is deliberately tiny and high-confidence: only terms where we are sure
the expansion is on-topic. It is used for two things:
  * widening the provider query (so the modern papers are actually fetched), and
  * counting an expansion as a match when scoring relevance (so a "prokaryote"
    paper is treated as matching "monera").
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-]{2,}")

# term -> on-topic modern equivalents. Keep entries conservative.
ALIASES: dict[str, tuple[str, ...]] = {
    # Obsolete / textbook taxonomy.
    "monera": (
        "prokaryote",
        "prokaryotes",
        "prokaryotic",
        "bacteria",
        "bacterial",
        "microorganism",
        "microorganisms",
        "microbe",
        "microbes",
    ),
    "prokaryote": ("bacteria", "bacterial", "monera", "prokaryotic", "microbial"),
    "prokaryotes": ("bacteria", "bacterial", "monera", "prokaryotic", "microbial"),
    "prokaryotic": ("bacteria", "bacterial", "monera", "prokaryote"),
    "bacteria": ("prokaryote", "prokaryotic", "microbial", "microorganism", "monera"),
    "bacterial": ("prokaryote", "prokaryotic", "microbial", "monera"),
    "microorganism": ("microbe", "bacteria", "prokaryote", "microbial"),
    "microorganisms": ("microbes", "bacteria", "prokaryote", "microbial"),
    "microbe": ("microorganism", "bacteria", "prokaryote"),
    "microbes": ("microorganisms", "bacteria", "prokaryote"),
    "protista": ("protist", "protozoa", "protozoan", "eukaryote", "eukaryotic"),
    "protist": ("protista", "protozoa", "eukaryote"),
    "protozoa": ("protist", "protista", "protozoan"),
    "fungi": ("fungus", "fungal", "mycology", "yeast", "mold"),
    "fungus": ("fungi", "fungal", "mycology"),
    "autotroph": ("autotrophic", "photosynthesis", "chemoautotroph"),
    "autotrophs": ("autotrophic", "photosynthesis", "chemoautotroph"),
    "heterotroph": ("heterotrophic", "carbon", "nutrition"),
    "heterotrophs": ("heterotrophic", "carbon", "nutrition"),
    # Naming / classification.
    "binomial": ("taxonomy", "taxonomic", "nomenclature", "classification", "species"),
    "nomenclature": ("taxonomy", "taxonomic", "classification", "binomial", "naming"),
    "taxonomy": ("classification", "taxonomic", "systematics", "nomenclature"),
    "taxonomic": ("taxonomy", "classification", "systematics"),
    "classification": ("taxonomy", "taxonomic", "systematics"),
    # Everyday question words. These keep the offline question fallback useful
    # without turning a word like \"hot\" into a standalone topic.
    "sleepy": ("sleepiness", "drowsiness", "sleep", "somnolence"),
    "sleepiness": ("sleepy", "drowsiness", "sleep", "somnolence"),
    "drowsiness": ("sleepiness", "sleepy", "sleep"),
    "hot": ("heat", "temperature", "thermal", "thermoregulation"),
    "heat": ("hot", "temperature", "thermal", "thermoregulation"),
    "temperature": ("heat", "thermal", "thermoregulation"),
}

_MAX_EXPANSION_TERMS = 6


def tokens(text: str) -> list[str]:
    """Lower-cased significant words, order preserved."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(text):
        word = match.group(0).lower()
        if len(word) >= 3 and word not in seen:
            seen.add(word)
            out.append(word)
    return out


def build_aliases(query: str) -> dict[str, tuple[str, ...]]:
    """token -> its expansion terms, for every query term we know an alias for."""
    found: dict[str, tuple[str, ...]] = {}
    for word in tokens(query):
        alias = ALIASES.get(word)
        if alias:
            found[word] = alias
    return found


def expansion_terms(query: str, limit: int = _MAX_EXPANSION_TERMS) -> list[str]:
    """Extra words to append to the provider query so modern papers are fetched."""
    original = set(tokens(query))
    extra: list[str] = []
    for word in tokens(query):
        for alias in ALIASES.get(word, ()):
            if alias in original or alias in extra:
                continue
            extra.append(alias)
            if len(extra) >= limit:
                return extra
    return extra
