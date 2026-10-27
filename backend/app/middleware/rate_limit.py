"""Per-user API rate limiting middleware.

Uses Redis-backed sliding window rate limiting when a Redis client is
provided; otherwise falls back to an in-memory fixed-window counter
(per-process, not distributed — configure Redis for multi-instance
deployments).

Limits (requests per minute, configurable via settings):
- ``RATE_LIMIT_PER_MINUTE`` (default 300) for Bearer-token requests.
- ``RATE_LIMIT_API_KEY_PER_MINUTE`` (default 600) for X-API-Key requests.
- Anonymous / unauthenticated IP fallback with anti-abuse limits.
- Sensitive auth endpoints (/api/auth/*) receive strict rate limits.

Set ``RATE_LIMIT_ENABLED=false`` to disable the middleware entirely
(tests, or deployments where an API gateway already enforces limits).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings
from app.security.client_ip import client_ip

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({
    "/api/health",
    "/health",
    "/readyz",
    "/api/readyz",
    "/docs",
    "/redoc",
    "/openapi.json",
})

# Static SPA assets are immutable and are fetched in large batches by the
# browser (a single catalogue page can request hundreds of brand marks).
# They are not API calls and must never consume a user's API budget.
_SKIP_PREFIXES = (
    "/assets/",
    "/brand-logos/",
    "/fonts/",
    "/static/",
    "/trigger-beacon",
    "/favicon",
    "/manifest.webmanifest",
    "/robots.txt",
)

_AUTH_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/reset-password",
    "/api/auth/forgot-password",
})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-user rate limiting (Redis sliding window, in-memory fallback)."""

    def __init__(self, app: Any, redis_client: Any | None = None) -> None:
        super().__init__(app)
        self._redis_client: Any = redis_client
        self._memory_counts: dict[str, int] = {}

    @property
    def redis(self) -> Any | None:
        if self._redis_client is not None:
            return self._redis_client
        try:
            from app.security.redis_client import get_shared_redis

            return get_shared_redis()
        except Exception:
            return None

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not get_settings().rate_limit_enabled:
            return await call_next(request)

        # Skip rate limiting for health checks, readiness probes, static docs,
        # and browser-fetched immutable assets.
        path = request.url.path
        if path in _SKIP_PATHS or path.startswith(_SKIP_PREFIXES):
            return await call_next(request)

        user_id = self._get_user_id(request)

        is_limited, retry_after = await self._check_rate_limit(user_id, path)
        if is_limited:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """Extract the client IP, trusting forwarding headers only from
        configured proxies (see ``app.security.client_ip``)."""
        return client_ip(request)

    def _get_user_id(self, request: Request) -> str:
        """Extract a stable per-principal identifier from auth material or client IP."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            return f"token:{hashlib.sha256(token.encode()).hexdigest()[:16]}"
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        client_ip = self._get_client_ip(request)
        return f"ip:{hashlib.sha256(client_ip.encode()).hexdigest()[:16]}"

    def _limit_for(self, user_id: str, path: str = "") -> int:
        settings = get_settings()
        if path in _AUTH_PATHS:
            # Sensitive endpoints: brute force / credential stuffing prevention
            return min(20, settings.rate_limit_per_minute)
        if user_id.startswith("apikey:"):
            return settings.rate_limit_api_key_per_minute
        if user_id.startswith("ip:"):
            # Anonymous IP budget
            return min(120, settings.rate_limit_per_minute)
        return settings.rate_limit_per_minute

    async def _check_rate_limit(self, user_id: str, path: str = "") -> tuple[bool, int]:
        client = self.redis
        if client is None:
            return self._check_rate_limit_memory(user_id, path)
        try:
            # The shared client is sync redis: run its pipeline off-loop so
            # one slow Redis hop cannot stall every in-flight request.
            return await asyncio.to_thread(self._redis_window_check, user_id, path)
        except Exception as e:
            logger.warning("Rate limit check failed: %s", e)
            return self._check_rate_limit_memory(user_id, path)

    def _redis_window_check(self, user_id: str, path: str = "") -> tuple[bool, int]:
        client = self.redis
        if client is None:
            return self._check_rate_limit_memory(user_id, path)
        now = time.time()
        window = 60
        key_prefix = f"ratelimit:auth:{user_id}" if path in _AUTH_PATHS else f"ratelimit:{user_id}"
        key = f"{key_prefix}:{int(now // window)}"
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window + 1)
        count = pipe.execute()[0]
        limit = self._limit_for(user_id, path)
        if count > limit:
            return True, int(window - (now % window)) + 1
        return False, 0

    def _check_rate_limit_memory(self, user_id: str, path: str = "") -> tuple[bool, int]:
        """In-memory fixed-window fallback (per-process)."""
        now = time.time()
        window = int(now // 60)
        key_prefix = f"auth:{user_id}" if path in _AUTH_PATHS else user_id
        key = f"{key_prefix}:{window}"

        count = self._memory_counts.get(key, 0) + 1
        self._memory_counts[key] = count

        # Cleanup old windows
        for old in [k for k in list(self._memory_counts.keys()) if int(k.rsplit(":", 1)[-1]) < window]:
            del self._memory_counts[old]

        limit = self._limit_for(user_id, path)
        if count > limit:
            retry_after = int((window + 1) * 60 - now) + 1
            return True, retry_after
        return False, 0


def setup_rate_limiting(app: Any, redis_client: Any | None = None) -> None:
    """Configure rate limiting on the FastAPI app."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        logger.info("Rate limiting disabled by configuration")
        return
    app.add_middleware(RateLimitMiddleware, redis_client=redis_client)
    if redis_client is not None:
        logger.info("Rate limiting enabled with explicit Redis backend")
    else:
        logger.info("Rate limiting enabled with lazy Redis / in-memory fallback")
