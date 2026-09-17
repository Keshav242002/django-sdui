"""
Redis cache wrapper (rules.md §6): all Redis access across the project goes
through CacheClient -- no raw redis.Redis() or django.core.cache calls
scattered elsewhere.
"""

import logging
from typing import Any

import pybreaker
from django.core.cache import cache
from prometheus_client import Counter

logger = logging.getLogger(__name__)

CACHE_REQUESTS = Counter(
    "sdui_cache_requests_total",
    "Cache get() calls by domain and result",
    ["domain", "result"],
)

# One breaker guards get/set/delete together -- Redis is a single dependency,
# so if it's down all three operations should trip and recover as a unit
# (plan.md phase-9 Key Decision #1). fail_max=3: after 3 consecutive
# failures, further calls skip Redis entirely (raise CircuitBreakerError
# instead of attempting the call) for reset_timeout seconds, instead of
# every request paying the full socket_connect_timeout/socket_timeout cost
# (Phase 3) while Redis is down.
_REDIS_BREAKER = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=5,
    name="redis",
)


def _domain(key: str) -> str:
    return key.split(":", 1)[0] if ":" in key else "unknown"


class CacheClient:
    """
    Thin wrapper around Django's cache framework (backed by Redis).

    All cache reads/writes across the project go through this class.

    Redis-down handling: every operation is guarded by a shared circuit
    breaker (_REDIS_BREAKER, plan.md phase-9 Key Decision #1). While closed,
    a failing call is still attempted and logged as a WARNING (functionally
    identical to pre-Phase-9 behavior). After 3 consecutive failures, the
    breaker opens and further calls skip Redis entirely -- fast-failing
    instead of paying the connection-timeout cost per call -- until
    reset_timeout (5s) elapses, at which point one trial call is allowed
    through to decide whether to close again.
    """

    def get(self, key: str) -> Any:
        try:
            value = _REDIS_BREAKER.call(cache.get, key)
        except pybreaker.CircuitBreakerError:
            logger.warning("Redis circuit breaker OPEN; skipping GET for key=%s", key)
            return None
        except Exception:
            logger.warning("Redis GET failed for key=%s; treating as cache miss", key, exc_info=True)
            return None

        if value is None:
            logger.debug("Cache MISS for %s", key)
            CACHE_REQUESTS.labels(domain=_domain(key), result="miss").inc()
        else:
            logger.debug("Cache HIT for %s", key)
            CACHE_REQUESTS.labels(domain=_domain(key), result="hit").inc()
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        try:
            _REDIS_BREAKER.call(cache.set, key, value, timeout=ttl)
        except pybreaker.CircuitBreakerError:
            logger.warning("Redis circuit breaker OPEN; skipping SET for key=%s", key)
        except Exception:
            logger.warning("Redis SET failed for key=%s; skipping cache write", key, exc_info=True)

    def delete(self, key: str) -> None:
        try:
            _REDIS_BREAKER.call(cache.delete, key)
        except pybreaker.CircuitBreakerError:
            logger.warning("Redis circuit breaker OPEN; skipping DELETE for key=%s", key)
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
