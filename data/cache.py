"""In-memory cache for FRED API responses.

Provides a simple TTL-based cache that wraps the FredClient to reduce
external API calls and improve latency.  Thread-safe via a lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class FredCache:
    """Thread-safe in-memory cache with configurable TTL.

    Usage::

        cache = FredCache(ttl=3600)
        result = cache.get("CPIAUCSL:2020-01-01:2024-01-01")
        if result is None:
            result = fred_client.get_observations("CPIAUCSL", ...)
            cache.set("CPIAUCSL:2020-01-01:2024-01-01", result)
    """

    def __init__(self, ttl: int | None = None) -> None:
        if ttl is None:
            from config import FRED_CACHE_TTL
            ttl = FRED_CACHE_TTL
        self.ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(*parts: Any) -> str:
        """Build a deterministic cache key from arbitrary arguments."""
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        """Return the cached value, or ``None`` if missing / expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if time.monotonic() - ts > self.ttl:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* with the configured TTL."""
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        """Evict all entries."""
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, int]:
        """Return cache hit/miss statistics."""
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
            }
