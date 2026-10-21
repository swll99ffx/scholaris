"""
Tiny async TTL cache.

Why: free APIs (especially Semantic Scholar) rate-limit quickly. Repeating the
same search within 15 minutes should cost zero API calls.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

_MISSING = object()


class TTLCache:
    """In-memory LRU cache with per-entry expiry and single-flight loading."""

    def __init__(self, max_entries: int = 256, default_ttl: int = 900) -> None:
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def get(self, key: str) -> Any:
        entry = self._data.get(key)
        if entry is None:
            return _MISSING
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return _MISSING
        self._data.move_to_end(key)
        return value

    async def get_or_none(self, key: str) -> Any | None:
        """Like get(), but returns None instead of the internal sentinel."""
        value = await self.get(key)
        return None if value is _MISSING else value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        self._data[key] = (time.monotonic() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: int | None = None,
    ) -> Any:
        """Return a cached value or call factory exactly once for this key."""
        cached = await self.get(key)
        if cached is not _MISSING:
            return cached

        # One lock per key prevents a burst of duplicate provider calls.
        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            cached = await self.get(key)
            if cached is not _MISSING:
                return cached
            value = await factory()
            await self.set(key, value, ttl)
            return value

    def clear(self) -> None:
        self._data.clear()
