"""
Shared HTTP helper.

Free scholarly APIs fail in predictable ways:
  429  -> we are going too fast
  5xx  -> their server is having a bad day
  network timeouts

We retry those with exponential backoff, while still returning a friendly
ProviderError for real problems (bad query, unknown ID, etc.).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .errors import ProviderError
from .rate_limit import RateLimiter


async def fetch(
    client: httpx.AsyncClient,
    *,
    provider: str,
    url: str,
    params: dict[str, Any] | None = None,
    limiter: RateLimiter,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
    parse: str = "json",
) -> Any:
    """GET a URL politely and return parsed JSON or text."""
    last_status: int | None = None

    for attempt in range(attempts):
        await limiter.wait(provider)
        try:
            response = await client.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_status = None
            if attempt < attempts - 1:
                await asyncio.sleep(min(6.0, 1.2 * (2**attempt)))
                continue
            raise ProviderError(provider, "network timeout") from exc

        last_status = response.status_code
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < attempts - 1:
                # Honour Retry-After when the provider sends it.
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 1.5 * (2**attempt)
                except ValueError:
                    delay = 1.5 * (2**attempt)
                await asyncio.sleep(min(8.0, delay))
                continue
            raise ProviderError(
                provider,
                f"HTTP {response.status_code}",
                status=response.status_code,
            )

        if response.status_code >= 400:
            # Read a short snippet for the log, but never expose a wall of HTML.
            snippet = response.text[:200].replace("\n", " ").strip()
            raise ProviderError(
                provider,
                f"HTTP {response.status_code}: {snippet or 'request rejected'}",
                status=response.status_code,
            )

        if parse == "text":
            return response.text
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(provider, "returned an invalid JSON response") from exc

    raise ProviderError(provider, f"HTTP {last_status or 'unknown'}", status=last_status)
