"""
Search orchestrator: interpret the topic, query the free APIs in parallel,
merge, rank and annotate.

Design notes:
  * Providers are independent; one failing never hides the others' results.
  * A long pasted assignment is reduced to its real topic before searching.
  * The whole pipeline is cached per topic+filters for 15 minutes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Awaitable, Callable

import httpx

from app.config import Settings, get_settings
from app.core.cache import TTLCache
from app.core.errors import ProviderError

from ..models import SourceRecord
from ..schemas import SearchRequest
from . import (
    core,
    crossref,
    doaj,
    europepmc,
    openalex,
    pubmed,
    semantic_scholar,
)
from . import interpret as interpret_service
from . import synonyms
from .merge import merge_records
from .notes import apply_notes
from .presenter import to_out
from .ranking import apply_filters, rank_feed

logger = logging.getLogger(__name__)

# The first page is kept identical to the pre-feed ranking so scroll loading
# never changes the protected top results. The hidden feed cap comes from the
# request's limit (100 by default in the UI).
SEARCH_PAGE_SIZE = 20

_settings = get_settings()
CACHE = TTLCache(
    max_entries=_settings.cache_max_entries,
    default_ttl=_settings.cache_ttl_seconds,
)

ProviderFn = Callable[..., Awaitable[list[SourceRecord]]]

# Order matters for merging: earlier providers define the "base" record.
# All of these are free and researcher-trusted:
#   OpenAlex (open catalogue), Semantic Scholar, Crossref, PubMed + Europe PMC
#   (PMC), DOAJ (vetted open-access journals) and CORE (OA repositories).
PROVIDERS: tuple[tuple[str, ProviderFn], ...] = (
    ("OpenAlex", openalex.search),
    ("Europe PMC", europepmc.search),
    ("Semantic Scholar", semantic_scholar.search),
    ("Crossref", crossref.search),
    ("PubMed", pubmed.search),
    ("DOAJ", doaj.search),
    ("CORE", core.search),
)

# Extra concept searches use a smaller provider subset. Europe PMC covers
# PubMed, and this avoids hammering the strict rate limits on Semantic Scholar,
# PubMed and CORE.
EXTRA_PROVIDERS: tuple[tuple[str, ProviderFn], ...] = tuple(
    item for item in PROVIDERS if item[0] in {"OpenAlex", "Europe PMC", "Crossref", "DOAJ"}
)

# Semantic Scholar's anonymous tier is far stricter than the others and is fully
# covered by them, so a rate-limit there is logged but never shown to the user.
QUIET_PROVIDERS = {"Semantic Scholar"}


def build_client(settings: Settings) -> httpx.AsyncClient:
    """One HTTP client per search, with a polite User-Agent."""
    return httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={
            "User-Agent": f"Scholaris/0.1 (mailto:{settings.contact_email})",
            "Accept": "application/json, application/xml;q=0.9, */*;q=0.8",
        },
    )


def _durable_warning(message: str) -> bool:
    """Provider rate-limit/unavailable notices are transient; advisories are not."""
    return "Results from other sources are still shown" not in message


def cache_key(payload: dict[str, Any]) -> str:
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"research:search:{digest}"


def _provider_timeout(name: str, settings: Settings, deep_search: bool) -> float:
    """Keep normal searches fast; let the user explicitly opt into slow CORE."""
    if deep_search:
        return settings.search_deep_provider_timeout_seconds
    if name == "CORE":
        return settings.search_core_timeout_seconds
    return settings.search_provider_timeout_seconds


async def _gather(
    client: httpx.AsyncClient,
    query: str,
    request: SearchRequest,
    settings: Settings,
    per_provider: int,
    providers: tuple[tuple[str, ProviderFn], ...] = PROVIDERS,
    quiet_extra: bool = False,
) -> tuple[list[SourceRecord], list[str]]:
    async def call_provider(name: str, function: ProviderFn):
        timeout = _provider_timeout(name, settings, request.filters.deep_search)
        try:
            return await asyncio.wait_for(
                function(
                    client,
                    query=query,
                    filters=request.filters,
                    settings=settings,
                    limit=per_provider,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # A slow third-party API must never keep the student waiting. The
            # other providers' results are still complete and useful.
            logger.info("%s timed out after %.1fs; continuing without it", name, timeout)
            return []

    names = [name for name, _ in providers]
    results = await asyncio.gather(
        *(call_provider(name, function) for name, function in providers),
        return_exceptions=True,
    )

    records: list[SourceRecord] = []
    warnings: list[str] = []

    for name, result in zip(names, results):
        if isinstance(result, BaseException):
            if quiet_extra:
                logger.info("Extra concept search skipped %s: %s", name, result)
            elif isinstance(result, ProviderError):
                if name in QUIET_PROVIDERS:
                    logger.info("Optional provider %s skipped: %s", name, result.message)
                else:
                    warnings.append(result.friendly())
            else:
                warnings.append(f"{name} failed unexpectedly. Results from other sources are still shown.")
                logger.exception("Provider %s crashed", name, exc_info=result)
            continue
        records.extend(result)

    return records, warnings


def _tag_discovery(records: list[SourceRecord], search_query) -> None:
    label = search_query.discovery_label()
    if not label:
        return
    for record in records:
        if not record.discovery:
            record.discovery = label


async def run_search(request: SearchRequest, settings: Settings) -> dict[str, Any]:
    per_provider = min(settings.search_results_per_provider, 50)

    # 1. Work out the real topic and concept plan (handles a pasted assignment).
    interpreted = await interpret_service.interpret_topic(request.query, settings)
    query = interpreted.topic or request.query.strip()
    plan = interpreted.plan

    key = cache_key(
        {
            "query": query.lower(),
            "filters": request.filters.model_dump(),
            "concept_plan": plan.cache_key,
        }
    )

    cached = await CACHE.get_or_none(key)
    if cached is not None:
        return {**cached, "cached": True}

    async def compute() -> dict[str, Any]:
        # The concept plan always has a modern/primary query, plus optional
        # historical, per-concept and relationship searches.
        queries = plan.queries
        primary = queries[0]
        extra_queries = queries[1:]
        extra_per_provider = min(
            per_provider,
            max(4, settings.concept_search_extra_results),
        )

        async with build_client(settings) as client:
            primary_task = _gather(
                client,
                primary.query,
                request,
                settings,
                per_provider,
            )
            extra_tasks = [
                _gather(
                    client,
                    item.query,
                    request,
                    settings,
                    extra_per_provider,
                    providers=EXTRA_PROVIDERS,
                    quiet_extra=True,
                )
                for item in extra_queries
            ]
            gathered = await asyncio.gather(primary_task, *extra_tasks)

            primary_records, warnings = gathered[0]
            _tag_discovery(primary_records, primary)
            records = list(primary_records)

            for search_query, result in zip(extra_queries, gathered[1:]):
                extra_records, extra_warnings = result
                warnings.extend(extra_warnings)
                _tag_discovery(extra_records, search_query)
                records.extend(extra_records)

            merged = merge_records(records)
            # Crossref/PubMed/DOAJ report no citations; fill them from OpenAlex
            # so highly cited papers can actually rank at the top. This is a
            # bonus, not a reason to make the page wait.
            try:
                await asyncio.wait_for(
                    openalex.backfill_citation_counts(
                        client, settings=settings, records=merged
                    ),
                    timeout=settings.citation_backfill_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.info("Citation backfill timed out; using existing counts")

        warnings = list(dict.fromkeys(warnings))
        filtered = apply_filters(merged, request.filters)
        ranked = rank_feed(
            query,
            filtered,
            page_size=SEARCH_PAGE_SIZE,
            max_results=request.filters.limit,
            mode=request.filters.relevance_mode,
            aliases=synonyms.build_aliases(query),
            plan=plan,
        )

        base = {
            "query": request.query,
            "topic": query,
            "input_mode": interpreted.mode,
            "keywords": interpreted.keywords,
            "concepts": plan.to_out(),
            "sources": [],
            "warnings": warnings,
        }

        if not ranked:
            if not warnings:
                warnings.append(
                    "No sources matched. Try different keywords or turn off a filter."
                )
            return {**base, "count": 0}

        if 0 < len(ranked) < min(request.filters.limit, 5):
            warnings.append(
                f"Only {len(ranked)} strong, distinct source(s) matched. Weak or "
                "duplicate matches were not added."
            )

        # Nudge the student when nothing really matches (better than pretending).
        if ranked[0].score_breakdown.get("relevance", 0) < 20:
            warnings.append(
                "No source strongly matches this topic yet. Try rephrasing or adding a "
                "more specific keyword (for example the organism, method or place)."
            )

        # Notes are a bonus and must never delay the results. The UI upgrades
        # them through /api/research/notes after the cards are visible.
        await apply_notes(query, ranked, settings, enrich_llm=False)
        sources = [to_out(record) for record in ranked]
        return {**base, "count": len(sources), "sources": sources}

    value = await CACHE.get_or_set(key, compute)
    # Provider hiccups ("... is rate-limiting us.") are transient — show them on
    # this live response but never remember them for the next 15 minutes.
    durable = [w for w in value.get("warnings", []) if _durable_warning(w)]
    if durable != value.get("warnings"):
        await CACHE.set(key, {**value, "warnings": durable})
    return {**value, "cached": False}
