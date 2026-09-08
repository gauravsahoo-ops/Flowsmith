"""Redis connector tests (Phase 11 business connectors).

fakeredis backs the connection seam (same library the queue throttle
tests use). Proves: get/set/delete/incr/publish round-trips, REDIS_URL
fallback, URI scheme enforcement.
"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors

CREDS = {"uri": "redis://localhost:6379/0"}


@pytest.fixture(autouse=True)
def _connectors(monkeypatch):
    import app.providers.redis_provider as mod

    monkeypatch.setattr(
        mod.aioredis, "from_url",
        lambda uri, **kw: fakeredis.aioredis.FakeRedis.from_url(uri, **kw),
    )
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_set_get_roundtrip():
    from app.providers.redis_provider import RedisProviderClient

    client = RedisProviderClient()
    out = _run(client.set(CREDS, "wf:counter", "42", ttl_seconds=60))
    assert out["set"] is True and out["ttl"] == 60
    got = _run(client.get(CREDS, "wf:counter"))
    assert got == {"found": True, "key": "wf:counter", "value": "42"}


def test_delete_and_missing_key():
    from app.providers.redis_provider import RedisProviderClient

    client = RedisProviderClient()
    _run(client.set(CREDS, "k", "v"))
    deleted = _run(client.delete(CREDS, "k"))
    assert deleted["deleted"] == 1
    missing = _run(client.get(CREDS, "k"))
    assert missing["found"] is False and missing["value"] is None


def test_incr_by_amount():
    from app.providers.redis_provider import RedisProviderClient

    client = RedisProviderClient()
    first = _run(client.incr(CREDS, "hits", 1))
    second = _run(client.incr(CREDS, "hits", 4))
    assert first["value"] == 1 and second["value"] == 5


def test_publish_reports_receivers(monkeypatch):
    from app.providers.redis_provider import RedisProviderClient

    client = RedisProviderClient()
    # No subscriber -> 0 receivers; proves the call path executes.
    out = _run(client.publish(CREDS, "events", "hello"))
    assert out["receivers"] == 0


def test_empty_uri_falls_back_to_server_redis_url(monkeypatch):
    from app.providers.redis_provider import RedisProviderClient

    class FakeSettings:
        redis_url = "redis://fallback-host:6379/0"

    monkeypatch.setattr("app.providers.redis_provider.get_settings", lambda: FakeSettings())
    captured: dict = {}

    def fake_from_url(uri, **kw):
        captured["uri"] = uri
        return fakeredis.aioredis.FakeRedis.from_url(uri, **kw)

    import app.providers.redis_provider as mod

    monkeypatch.setattr(mod.aioredis, "from_url", fake_from_url)
    _run(RedisProviderClient().get({}, "any-key"))
    assert captured["uri"] == FakeSettings.redis_url


def test_bad_scheme_rejected():
    from app.providers.redis_provider import RedisProviderClient

    async def go():
        await RedisProviderClient().get({"uri": "http://not-redis"}, "k")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("http scheme should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


def test_no_uri_anywhere_rejected(monkeypatch):
    from app.providers.redis_provider import RedisProviderClient

    class FakeSettings:
        redis_url = ""

    monkeypatch.setattr("app.providers.redis_provider.get_settings", lambda: FakeSettings())

    async def go():
        await RedisProviderClient().get({}, "k")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("missing uri should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


def test_connector_layer_routes_operations():
    """The connector maps op names onto provider calls with payload keys."""
    from app.connectors.redis_connector import RedisConnector
    from app.providers.redis_provider import RedisProviderClient

    conn = RedisConnector()

    async def fake_set(creds, key, value, ttl_seconds=0):
        return {"key": key, "set": True, "ttl": None}

    conn._provider.set = fake_set  # type: ignore[method-assign]
    out = _run(conn.op_execute("", {"operation": "set", "key": "a", "value": "b"}, {"credentials": {"redis": {}}}))
    assert out["key"] == "a"
