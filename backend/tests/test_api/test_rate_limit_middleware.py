"""Tests for the per-user rate limiting middleware.

The suite-wide harness disables the limiter (RATE_LIMIT_ENABLED=false)
because execution polling legitimately exceeds any small budget; these
tests exercise the middleware itself on an isolated app with explicit
settings.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import rate_limit as rl


@pytest.fixture
def mini_app():
    """Isolated app carrying only the rate limit middleware."""
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app


def _settings(enabled=True, per_minute=3, api_key_per_minute=5):
    return SimpleNamespace(
        rate_limit_enabled=enabled,
        rate_limit_per_minute=per_minute,
        rate_limit_api_key_per_minute=api_key_per_minute,
    )


@pytest.fixture
def limited_client(mini_app, monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings(per_minute=3))
    mini_app.add_middleware(rl.RateLimitMiddleware, redis_client=None)
    return TestClient(mini_app)


def _bearer(n: int) -> dict[str, str]:
    return {"Authorization": f"Bearer token-{n}"}


def test_disabled_middleware_never_limits(mini_app, monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings(enabled=False))
    mini_app.add_middleware(rl.RateLimitMiddleware, redis_client=None)
    client = TestClient(mini_app)
    for _ in range(50):
        assert client.get("/ping", headers=_bearer(1)).status_code == 200


def test_limits_after_budget_and_returns_retry_after(limited_client):
    statuses = [
        limited_client.get("/ping", headers=_bearer(1)).status_code
        for _ in range(5)
    ]
    assert statuses == [200, 200, 200, 429, 429]
    r = limited_client.get("/ping", headers=_bearer(1))
    assert r.headers["Retry-After"].isdigit()
    assert r.json()["error"] == "rate_limit_exceeded"


def test_budget_is_per_principal(limited_client):
    for _ in range(3):
        assert limited_client.get("/ping", headers=_bearer(1)).status_code == 200
    assert limited_client.get("/ping", headers=_bearer(1)).status_code == 429
    # A different token has its own budget
    assert limited_client.get("/ping", headers=_bearer(2)).status_code == 200


def test_health_path_is_skipped(limited_client):
    for _ in range(10):
        assert limited_client.get("/api/health").status_code == 200


def test_unauthenticated_requests_are_not_limited(limited_client):
    # No Authorization/X-API-Key header -> no principal -> no limiting
    for _ in range(10):
        assert limited_client.get("/ping").status_code == 200


def test_api_key_has_separate_budget(mini_app, monkeypatch):
    monkeypatch.setattr(rl, "get_settings", lambda: _settings(per_minute=2, api_key_per_minute=4))
    mini_app.add_middleware(rl.RateLimitMiddleware, redis_client=None)
    client = TestClient(mini_app)
    codes = [
        client.get("/ping", headers={"X-API-Key": "k-1"}).status_code
        for _ in range(5)
    ]
    assert codes == [200, 200, 200, 200, 429]


class _FakeRedis:
    """Minimal pipeline/redis stand-in for the sliding-window path."""

    def __init__(self, counts: dict[str, int]):
        self.counts = counts

    def pipeline(self):
        return self

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, ttl):
        return True

    def execute(self):
        return [self.counts.get("last", 0)]


def test_redis_backend_enforces_limit(mini_app, monkeypatch):
    counts: dict[str, int] = {}

    class _Pipe:
        def incr(self, key):
            counts[key] = counts.get(key, 0) + 1
            return counts[key]

        def expire(self, key, ttl):
            return True

        def execute(self):
            return [max(counts.values())]

    class _Redis:
        def pipeline(self):
            return _Pipe()

    monkeypatch.setattr(rl, "get_settings", lambda: _settings(per_minute=2))
    mini_app.add_middleware(rl.RateLimitMiddleware, redis_client=_Redis())
    client = TestClient(mini_app)
    codes = [client.get("/ping", headers=_bearer(9)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_redis_failure_fails_open(mini_app, monkeypatch):
    class _Boom:
        def pipeline(self):
            raise RuntimeError("redis down")

    monkeypatch.setattr(rl, "get_settings", lambda: _settings())
    mini_app.add_middleware(rl.RateLimitMiddleware, redis_client=_Boom())
    client = TestClient(mini_app)
    for _ in range(10):
        assert client.get("/ping", headers=_bearer(3)).status_code == 200
