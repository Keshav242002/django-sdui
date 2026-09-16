"""
Redis cache wrapper (rules.md §6): all Redis access across the project goes
through CacheClient -- no raw redis.Redis() or django.core.cache calls
scattered elsewhere.
"""

import logging
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)


class CacheClient:
    """
    Thin wrapper around Django's cache framework (backed by Redis).

    All cache reads/writes across the project go through this class.

    Redis-down handling (this phase): try/except on every operation.
    On failure, logs a WARNING and returns None / no-op. This is
    functionally correct (Postgres fallback always works) but NOT
    fast-failing -- every request pays the full Redis connection-timeout
    cost while Redis is down. A minimal circuit breaker that skips
    Redis entirely once tripped is deferred to a later phase (see
    master/phase-3-layout-caching/plan.md, "Out of scope" item 2 and
    "Key decisions" §3).
    """

    def get(self, key: str) -> Any:
        try:
            value = cache.get(key)
        except Exception:
            logger.warning("Redis GET failed for key=%s; treating as cache miss", key, exc_info=True)
            return None

        if value is None:
            logger.debug("Cache MISS for %s", key)
        else:
            logger.debug("Cache HIT for %s", key)
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            cache.set(key, value, timeout=ttl)
        except Exception:
            logger.warning("Redis SET failed for key=%s; skipping cache write", key, exc_info=True)

    def delete(self, key: str) -> None:
        try:
            cache.delete(key)
        except Exception:
            logger.warning("Redis DELETE failed for key=%s", key, exc_info=True)


# Module-level singleton -- import this, don't instantiate CacheClient elsewhere.
cache_client = CacheClient()


def layout_cache_key(screen_key: str) -> str:
    return f"layout:{screen_key}:current"


def widget_cache_key(widget_key: str) -> str:
    return f"widget:{widget_key}"


def portfolio_cache_key(user_id: str) -> str:
    return f"portfolio:{user_id}:summary"


def holdings_cache_key(user_id: str) -> str:
    return f"holdings:{user_id}:list"


def flag_cache_key(flag_key: str) -> str:
    return f"flag:{flag_key}"
