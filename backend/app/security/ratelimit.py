"""In-memory rate limiting (single-worker; multi-worker deployments
should back this with a shared store — see docs/security.md)."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Any

from app.security.redis_client import get_shared_redis  # noqa: E402  (late bind ok)

logger = logging.getLogger("ratelimit")


class SlidingWindowLimiter:
    """Fixed-capacity sliding window of request timestamps per key.

    `allow(key)` returns (allowed, retry_after_seconds); the window is
    keyed per path (webhooks) or per account/IP (login attempts).
    """

    def __init__(self, capacity: int, window_s: float) -> None:
        self.capacity = capacity
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> None:
        window = self._hits[key]
        cutoff = now - self.window_s
        while window and window[0] <= cutoff:
            window.popleft()
        if not window:
            del self._hits[key]

    def allow(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        self._prune(key, now)
        window = self._hits[key]
        if len(window) >= self.capacity:
            retry_after = max(1.0, self.window_s - (now - window[0]))
            return False, round(retry_after)
        window.append(now)
        return True, 0.0

    def reset(self) -> None:
        self._hits.clear()


class FailureThrottle:
    """Lockout after N failures within a window, keyed by account and IP."""

    def __init__(self, max_failures: int, window_s: float, lockout_s: float) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self.lockout_s = lockout_s
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def retry_after(self, key: str) -> int:
        """Seconds until the key may try again (0 when not locked)."""
        locked_until = self._locked_until.get(key, 0.0)
        return max(0, int(locked_until - time.monotonic()) + 1)

    def is_locked(self, key: str) -> bool:
        now = time.monotonic()
        if self._locked_until.get(key, 0.0) > now:
            return True
        self._locked_until.pop(key, None)
        self._prune(key, now)
        return len(self._fails[key]) >= self.max_failures

    def _prune(self, key: str, now: float) -> None:
        window = self._fails[key]
        cutoff = now - self.window_s
        while window and window[0] <= cutoff:
            window.popleft()
        if not window:
            self._fails.pop(key, None)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now)
        self._fails[key].append(now)
        if len(self._fails[key]) >= self.max_failures:
            self._locked_until[key] = now + self.lockout_s

    def clear(self, key: str) -> None:
        self._fails.pop(key, None)
        self._locked_until.pop(key, None)

    def reset(self) -> None:
        self._fails.clear()
        self._locked_until.clear()


class RedisFailureThrottle:
    """Redis-backed failure throttle for multi-instance deployments.

    Same contract as :class:`FailureThrottle` but counters live in the
    shared Redis so N API replicas enforce ONE budget per account/IP.
    Fixed-window semantics: ``login:fail:{key}`` counts failures and
    expires after the window; on reaching the cap,
    ``login:lock:{key}`` is set with the lockout TTL.

    Availability policy (audit phase 12): a Redis outage must not turn
    login into a 500. Throttle checks FALL BACK to a per-process
    in-memory :class:`FailureThrottle` (same policy as the API
    rate-limit middleware) instead of failing open.
    """

    def __init__(self, redis: Any, max_failures: int, window_s: float, lockout_s: float) -> None:
        self._redis = redis
        self.max_failures = max_failures
        self.window_s = int(window_s)
        self.lockout_s = int(lockout_s)
        self._prefix = "login"
        self._local = FailureThrottle(max_failures, window_s, lockout_s)

    def _fail_key(self, key: str) -> str:
        return f"{self._prefix}:fail:{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self._prefix}:lock:{key}"

    def is_locked(self, key: str) -> bool:
        try:
            return bool(self._redis.exists(self._lock_key(key)))
        except Exception as exc:
            logger.warning("login throttle unavailable (%s); using in-memory fallback", exc)
            return self._local.is_locked(key)

    def retry_after(self, key: str) -> int:
        try:
            ttl = self._redis.ttl(self._lock_key(key))
            return max(0, int(ttl)) if ttl is not None and ttl > 0 else 0
        except Exception as exc:
            logger.warning("login throttle retry-after unavailable (%s); using in-memory fallback", exc)
            return self._local.retry_after(key)

    def record_failure(self, key: str) -> None:
        try:
            fail_key = self._fail_key(key)
            count = self._redis.incr(fail_key)
            if count == 1:
                self._redis.expire(fail_key, self.window_s)
            if count >= self.max_failures:
                self._redis.set(self._lock_key(key), "1", ex=self.lockout_s)
        except Exception as exc:
            logger.warning("login throttle record failed (%s); using in-memory fallback", exc)
            self._local.record_failure(key)

    def clear(self, key: str) -> None:
        self._local.clear(key)
        try:
            self._redis.delete(self._fail_key(key), self._lock_key(key))
        except Exception as exc:
            logger.warning("login throttle clear failed (%s); ignoring", exc)

    def reset(self) -> None:
        self._local.reset()
        try:
            for pattern in (f"{self._prefix}:fail:*", f"{self._prefix}:lock:*"):
                keys = list(self._redis.scan_iter(match=pattern))
                if keys:
                    self._redis.delete(*keys)
        except Exception as exc:
            logger.warning("login throttle reset failed (%s); in-memory state cleared only", exc)


def get_login_throttle():
    """Memory throttle locally; shared Redis throttle when REDIS_URL is
    configured (Phase 38: multi-instance login budgets)."""
    from app.config import get_settings

    settings = get_settings()
    shared = get_shared_redis()
    if shared is not None:
        return RedisFailureThrottle(
            shared, settings.login_max_attempts, settings.login_window_seconds, settings.login_lockout_seconds
        )
    return FailureThrottle(
        settings.login_max_attempts, settings.login_window_seconds, settings.login_lockout_seconds
    )


class RedisWindowLimiter:
    """Shared fixed-window limiter for per-path budgets (webhooks).

    Same ``allow(key) -> (allowed, retry_after_s)`` contract as
    :class:`SlidingWindowLimiter`, but the counter lives in the shared
    Redis so N API replicas enforce ONE budget per path.
    On Redis errors, falls back to a per-process in-memory sliding
    window (matching the API rate-limit middleware policy)."""

    def __init__(self, redis: Any, capacity: int, window_s: float, prefix: str = "webhookrl") -> None:
        self._redis = redis
        self.capacity = capacity
        self.window_s = max(int(window_s), 1)
        self._prefix = prefix
        self._local = SlidingWindowLimiter(capacity, self.window_s)

    def _bucket_key(self, key: str, bucket: int) -> str:
        return f"{self._prefix}:{key}:{bucket}"

    def allow(self, key: str) -> tuple[bool, float]:
        now = time.time()
        bucket = int(now // self.window_s)
        redis_key = self._bucket_key(key, bucket)
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, self.window_s + 1)
            count = int(pipe.execute()[0])
        except Exception as exc:
            logger.warning("path rate limit check failed (%s); using in-memory fallback", exc)
            return self._local.allow(key)
        if count > self.capacity:
            retry_after = max(1, self.window_s - int(now % self.window_s) + 1)
            return False, float(retry_after)
        return True, 0.0

    def reset(self) -> None:
        self._local.reset()
        try:
            keys = list(self._redis.scan_iter(match=f"{self._prefix}:*"))
            if keys:
                self._redis.delete(*keys)
        except Exception as exc:
            logger.warning("path rate limit reset failed (%s); in-memory state cleared only", exc)


def get_webhook_limiter(capacity: int, window_s: float):
    """Shared Redis budget when REDIS_URL is configured; per-process
    sliding window otherwise (single-instance deployments/tests)."""
    from app.config import get_settings

    get_settings()  # ensure settings loaded before shared client resolves env
    shared = get_shared_redis()
    if shared is not None:
        return RedisWindowLimiter(shared, capacity, window_s)
    return SlidingWindowLimiter(capacity, window_s)
