"""
Polite per-provider rate limiting.

Each free API has different limits. We space requests out with a minimum
interval, and serialise requests per provider so parallel searches stay safe.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval = min_interval_seconds
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._next_allowed: dict[str, float] = defaultdict(float)

    async def wait(self, provider: str) -> None:
        async with self._locks[provider]:
            now = time.monotonic()
            delay = self._next_allowed[provider] - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_allowed[provider] = time.monotonic() + self.min_interval
