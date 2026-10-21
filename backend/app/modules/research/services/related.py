"""
"Find related sources" for a chosen paper.

We use OpenAlex because it exposes three useful discovery signals for free:
  * referenced_works -> what this paper cites
  * cites:W...       -> what cites this paper
  * related_works    -> OpenAlex's own similarity recommendations
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings
from app.core.errors import ProviderError

from ..models import SourceRecord
from ..schemas import RelatedRequest
from . import openalex
from .merge import merge_records
from .notes import apply_notes
from .presenter import to_out
from .ranking import rank_records
from .search import build_client
from .text import normalize_doi

logger = logging.getLogger(__name__)


def _is_same_work(record: SourceRecord, parent: SourceRecord, parent_openalex_id: str) -> bool:
    if normalize_doi(record.doi) and normalize_doi(record.doi) == normalize_doi(parent.doi):
        return True
    return record.provider_ids.get("openalex") == parent_openalex_id


async def find_related(request: RelatedRequest, settings: Settings) -> dict[str, Any]:
    async with build_client(settings) as client:
        raw = await openalex.get_work_raw(
            client,
            settings=settings,
            doi=request.doi,
            openalex_id=request.openalex_id,
            title=request.title,
        )
        if not raw:
            raise ProviderError(
                "OpenAlex",
                "we could not find that paper. Check the DOI or try searching by title.",
            )

        parent = openalex.to_record(raw)
        parent_openalex_id = str(raw.get("id") or "").rsplit("/", 1)[-1]
        reference_ids = raw.get("referenced_works") or []
        recommended_ids = raw.get("related_works") or []

        warnings: list[str] = []

        async def safe(coro) -> list[SourceRecord]:
            try:
                return await coro
            except ProviderError as exc:
                warnings.append(exc.friendly())
                return []
            except Exception:  # noqa: BLE001
                logger.exception("Related-source lookup failed")
                warnings.append("Some related sources could not be loaded.")
                return []

        references, citing, recommended = await asyncio.gather(
            safe(
                openalex.fetch_by_ids(
                    client, settings=settings, openalex_ids=reference_ids, limit=request.limit
                )
            ),
            safe(
                openalex.fetch_citing(
                    client, settings=settings, openalex_id=parent_openalex_id, limit=request.limit
                )
            ),
            safe(
                openalex.fetch_by_ids(
                    client, settings=settings, openalex_ids=recommended_ids, limit=request.limit
                )
            ),
        )

    for record in references:
        record.discovery = "Referenced by this paper"
    for record in citing:
        record.discovery = "Cites this paper"
    for record in recommended:
        record.discovery = "Recommended by OpenAlex"

    combined = [
        record
        for record in (*references, *citing, *recommended)
        if not _is_same_work(record, parent, parent_openalex_id)
    ]

    merged = merge_records(combined)
    ranked = rank_records(parent.title, merged, request.limit, apply_gate=False)

    if not ranked:
        warnings.append("No related sources were found for this paper yet.")
    else:
        await apply_notes(parent.title, ranked, settings)

    return {
        "query": parent.title,
        "parent_title": parent.title,
        "count": len(ranked),
        "sources": [to_out(record) for record in ranked],
        "warnings": warnings,
    }
