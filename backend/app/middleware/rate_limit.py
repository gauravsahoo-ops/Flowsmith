"""Per-user API rate limiting middleware.

Uses Redis-backed sliding window rate limiting when a Redis client is
provided; otherwise falls back to an in-memory fixed-window counter
(per-process, not distributed — configure Redis for multi-instance
deployments).

Limits (requests per minute, configurable via settings):
- ``RATE_LIMIT_PER_MINUTE`` (default 300) for Bearer-token requests.
- ``RATE_LIMIT_API_KEY_PER_MINUTE`` (default 600) for X-API-Key requests.

Set ``RATE_LIMIT_ENABLED=false`` to disable the middleware entirely
(tests, or deployments where an API gateway already enforces limits).
The default budget is deliberately UI-safe: the canvas polls execution
status every 500ms while a run is live, so a single active tab can
legitimately issue hundreds of requests per minute.
"""

from __future__ import annotations

import hashlib
import logging
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({"/api/health", "/health", "/docs", "/openapi.json"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-user rate limiting (Redis sliding window, in-memory fallback)."""

    def __init__(self, app, redis_client=None):
        super().__init__(app)
        self.redis = redis_client
        self._memory_counts: dict[str, int] = {}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not get_settings().rate_limit_enabled:
            return await call_next(request)

        # Skip rate limiting for health checks and static docs
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        user_id = self._get_user_id(request)
        if user_id is None:
            return await call_next(request)

        is_limited, retry_after = await self._check_rate_limit(user_id)
        if is_limited:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    def _get_user_id(self, request: Request) -> str | None:
        """Extract a stable per-principal identifier from auth material."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            return f"token:{hashlib.sha256(token.encode()).hexdigest()[:16]}"
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        return None

    def _limit_for(self, user_id: str) -> int:
        settings = get_settings()
        if user_id.startswith("apikey:"):
            return settings.rate_limit_api_key_per_minute
        return settings.rate_limit_per_minute

    async def _check_rate_limit(self, user_id: str) -> tuple[bool, int]:
        if self.redis is None:
            return self._check_rate_limit_memory(user_id)
        try:
            now = time.time()
            window = 60
            key = f"ratelimit:{user_id}:{int(now // window)}"
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window + 1)
            count = pipe.execute()[0]
            limit = self._limit_for(user_id)
            if count > limit:
                return True, int(window - (now % window)) + 1
            return False, 0
        except Exception as e:
            logger.warning("Rate limit check failed: %s", e)
            return self._check_rate_limit_memory(user_id)

    def _check_rate_limit_memory(self, user_id: str) -> tuple[bool, int]:
        """In-memory fixed-window fallback (per-process)."""
        now = time.time()
        window = int(now // 60)
        key = f"{user_id}:{window}"

        count = self._memory_counts.get(key, 0) + 1
        self._memory_counts[key] = count

        # Cleanup old windows
        for old in [k for k in self._memory_counts if int(k.rsplit(":", 1)[-1]) < window]:
            del self._memory_counts[old]

        limit = self._limit_for(user_id)
        if count > limit:
            retry_after = int((window + 1) * 60 - now) + 1
            return True, retry_after
        return False, 0


def setup_rate_limiting(app, redis_client=None) -> None:
    """Configure rate limiting on the FastAPI app."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        logger.info("Rate limiting disabled by configuration")
        return
    if redis_client is not None:
        app.add_middleware(RateLimitMiddleware, redis_client=redis_client)
        logger.info("Rate limiting enabled with Redis backend")
    else:
        app.add_middleware(RateLimitMiddleware, redis_client=None)
        logger.info("Rate limiting enabled with in-memory fallback")
