"""
GC-PERF-CACHE-001 — process-local definition/settings cache (+ optional Redis).

Never stores authoritative game state (resources, queues, fleets).
Owner for ephemeral shared cache; definitions remain in their domain modules.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_LOCK = threading.RLock()
_CACHE: dict[str, tuple[float, Any]] = {}
_CONFIG_VERSION = 0


def get_config_version() -> int:
    return int(_CONFIG_VERSION)


def bump_config_version() -> int:
    """Call after admin definition/settings changes to invalidate caches."""
    global _CONFIG_VERSION
    with _LOCK:
        _CONFIG_VERSION += 1
        _CACHE.clear()
        ver = _CONFIG_VERSION
    _redis_set_config_version(ver)
    return ver


def cache_get(key: str) -> Any | None:
    with _LOCK:
        row = _CACHE.get(str(key))
        if row is None:
            return None
        expires_at, value = row
        if expires_at and expires_at < time.time():
            _CACHE.pop(str(key), None)
            return None
        return value


def cache_set(key: str, value: Any, *, ttl_sec: float | None = None) -> None:
    if ttl_sec is None:
        try:
            from game.config import get_definition_cache_ttl_sec

            ttl_sec = float(get_definition_cache_ttl_sec())
        except Exception:
            ttl_sec = 300.0
    expires = time.time() + max(0.0, float(ttl_sec)) if ttl_sec else 0.0
    with _LOCK:
        _CACHE[str(key)] = (expires, value)


def cached(key: str, factory: Callable[[], T], *, ttl_sec: float | None = None) -> T:
    """Return cached value or compute via factory (process-local)."""
    hit = cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    # Optional Redis shared layer for identical cold starts across workers.
    redis_hit = _redis_get(key)
    if redis_hit is not None:
        cache_set(key, redis_hit, ttl_sec=ttl_sec)
        return redis_hit  # type: ignore[return-value]
    value = factory()
    cache_set(key, value, ttl_sec=ttl_sec)
    _redis_set(key, value, ttl_sec=ttl_sec)
    return value


def clear_definition_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _redis_client():
    try:
        from game.config import get_redis_url

        url = get_redis_url()
        if not url:
            return None
        import redis  # type: ignore

        return redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        return None


def _redis_get(key: str) -> Any | None:
    client = _redis_client()
    if client is None:
        return None
    try:
        import json

        raw = client.get(f"gc:def:{get_config_version()}:{key}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.debug("redis get failed key=%s", key, exc_info=True)
        return None


def _redis_set(key: str, value: Any, *, ttl_sec: float | None) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        import json

        ttl = int(ttl_sec or 300)
        client.setex(
            f"gc:def:{get_config_version()}:{key}",
            max(1, ttl),
            json.dumps(value, default=str),
        )
    except Exception:
        logger.debug("redis set failed key=%s", key, exc_info=True)


def _redis_set_config_version(ver: int) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.set("gc:config_version", int(ver))
    except Exception:
        pass
