"""
One-click APA helpers for Module 2.

The rules matter here: the reference is built only from details the student
actually entered, the DOI is normalised before it becomes a link, and missing
metadata produces a short, honest note instead of an invented citation.
"""

from __future__ import annotations

from app.modules.research.models import SourceRecord
from app.modules.research.services.citations import format_apa, split_name
from app.modules.research.services.text import normalize_doi

from ..schemas import SourceMeta, SummaryCitations


def _family_names(source: SourceMeta) -> list[str]:
    families: list[str] = []
    for raw in source.authors:
        family, _given = split_name(raw)
        family = (family or "").strip()
        if family:
            families.append(family)
    return families


def build_citations(source: SourceMeta) -> SummaryCitations:
    """Build the in-text forms and a draft APA 7 reference from ``source``."""
    families = _family_names(source)
    year_label = str(source.year) if source.year else "n.d."

    if not families:
        return SummaryCitations(
            year_label=year_label,
            note="Add at least one author to generate APA in-text citations and a reference.",
        )

    if len(families) == 1:
        author_label = families[0]
    elif len(families) == 2:
        author_label = f"{families[0]} & {families[1]}"
    else:
        author_label = f"{families[0]} et al."

    in_text = f"({author_label}, {year_label})"
    narrative = f"{author_label.replace(' & ', ' and ')} ({year_label})"

    title = source.title.strip()
    reference = ""
    note = ""
    if not title:
        note = "Add the paper title to generate the full APA reference."
    else:
        record = SourceRecord(
            title=title,
            authors=list(source.authors),
            year=source.year,
            journal=source.journal,
            doi=normalize_doi(source.doi) or None,
            url=source.url,
        )
        reference = format_apa(record)
        note = (
            "Draft built from the details you entered — check volume, issue and pages "
            "against the DOI record before submitting."
        )

    return SummaryCitations(
        author_label=author_label,
        year_label=year_label,
        in_text=in_text,
        narrative=narrative,
        reference=reference,
        note=note,
    )
