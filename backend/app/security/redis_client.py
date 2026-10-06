"""Shared Redis client helper (Phase 35).

One lazy connection factory used by the API rate limiter (and reusable
by future cross-process features). Returns ``None`` when Redis is not
configured, so callers fall back to their in-process behaviour.

Connection failures surface to the caller: the rate limiters catch
them and fall back to their per-process in-memory limiters (never
unbounded).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import get_settings

logger = logging.getLogger("redis")

_lock = threading.Lock()
_client: Any | None = None
_checked_url: str = ""


def get_shared_redis() -> Any | None:
    """A process-wide Redis client, or None when REDIS_URL is unset."""
    global _client, _checked_url
    url = get_settings().redis_url or ""
    if not url:
        return None
    with _lock:
        if _client is not None and _checked_url == url:
            return _client
        try:
            import redis  # optional dependency (requirements.txt)

            _client = redis.Redis.from_url(url, decode_responses=True)
            _checked_url = url
            logger.info("shared Redis client ready")
        except Exception as exc:
            logger.warning("Redis unavailable (%s); falling back to in-process mode", exc)
            _client = None
        return _client


def reset_shared_redis() -> None:
    """Test helper: forget the cached client."""
    global _client, _checked_url
    with _lock:
        _client = None
        _checked_url = ""
