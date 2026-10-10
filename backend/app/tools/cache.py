"""Tiny in-memory TTL cache (saves API quota, speeds up repeated requests).

On Vercel each serverless instance has its own memory, so this is a best-effort
cache. Later we can swap it for Upstash Redis without changing the adapters.
Only successful (non-None) results are cached.
"""
import time
from collections.abc import Awaitable, Callable
from typing import Any


class TTLCache:
    def __init__(self, max_items: int = 500) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self.max_items = max_items

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if len(self._data) >= self.max_items:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest, None)
        self._data[key] = (time.monotonic() + ttl, value)

    async def get_or_set(
        self, key: str, ttl: float, factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        if value is not None:
            self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        self._data.clear()


cache = TTLCache()


def make_key(*parts: object) -> str:
    return "|".join(str(p).strip().lower() for p in parts)
