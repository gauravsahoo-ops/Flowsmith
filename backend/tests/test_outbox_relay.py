"""Outbox relay and Redis Streams event bus tests (no external services)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

import app.platform.outbox_relay as outbox_relay_module
from app.platform.events import RUN_COMPLETED, new_event
from app.platform.outbox_relay import OutboxRelay
from app.platform.redis_event_bus import DEFAULT_STREAM_NAME, RedisEventBus


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def xadd(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append((args, kwargs))
        return "1-0"


class _FailingRedis:
    def xadd(self, *_args: Any, **_kwargs: Any) -> str:
        raise ConnectionError("connection refused")


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _event():
    return new_event(
        RUN_COMPLETED,
        tenant_id="org_relay",
        workspace_id="ws_relay",
        run_id="run_relay",
        payload={"status": "success"},
        correlation_id="corr_relay",
    )


async def _publisher(_event) -> None:
    return None


async def test_redis_event_bus_publishes_json_envelope_to_configured_stream():
    client = _FakeRedis()
    bus = RedisEventBus("custom.events", max_len=42, client=client)
    event = _event()

    await bus.publish(event)

    assert len(client.calls) == 1
    args, kwargs = client.calls[0]
    assert args[0] == "custom.events"
    assert set(args[1]) == {"data"}
    assert json.loads(args[1]["data"]) == event.to_dict()
    assert kwargs == {"maxlen": 42, "approximate": True}


async def test_redis_event_bus_defaults_to_shared_client_and_stream(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(
        "app.platform.redis_event_bus.get_shared_redis", lambda: client
    )

    await RedisEventBus().publish(_event())

    args, kwargs = client.calls[0]
    assert args[0] == DEFAULT_STREAM_NAME
    assert kwargs == {"maxlen": 100_000, "approximate": True}


async def test_redis_event_bus_raises_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr("app.platform.redis_event_bus.get_shared_redis", lambda: None)

    with pytest.raises(RuntimeError, match="Redis is unavailable"):
        await RedisEventBus().publish(_event())


async def test_redis_event_bus_wraps_xadd_failures():
    with pytest.raises(RuntimeError, match="Failed to publish event"):
        await RedisEventBus(client=_FailingRedis()).publish(_event())


def test_redis_event_bus_validates_configuration():
    with pytest.raises(ValueError, match="stream_name"):
        RedisEventBus(" ")
    with pytest.raises(ValueError, match="max_len"):
        RedisEventBus("events", max_len=0)


def test_relay_default_interval_and_validation():
    assert OutboxRelay(_publisher).interval == 1.0
    with pytest.raises(ValueError, match="interval"):
        OutboxRelay(_publisher, interval=0)


async def test_relay_run_once_uses_a_fresh_session_per_pass(monkeypatch):
    sessions: list[_FakeSession] = []

    def session_factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    calls: list[tuple[Any, Any, int, int]] = []

    async def fake_relay_once(db, publish, *, limit, max_attempts):
        calls.append((db, publish, limit, max_attempts))
        return 3

    monkeypatch.setattr(outbox_relay_module, "relay_once", fake_relay_once)
    relay = OutboxRelay(
        _publisher,
        interval=0.01,
        batch_size=5,
        max_attempts=2,
        session_factory=session_factory,
    )

    assert await relay.run_once() == 3
    assert await relay.run_once() == 3

    assert len(sessions) == 2
    assert all(session.closed for session in sessions)
    assert [call[2:] for call in calls] == [(5, 2), (5, 2)]
    assert all(call[1] is _publisher for call in calls)
    assert calls[0][0] is sessions[0]
    assert calls[1][0] is sessions[1]


async def test_relay_run_once_propagates_failures_and_closes_the_session(monkeypatch):
    session = _FakeSession()

    async def failing_relay_once(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(outbox_relay_module, "relay_once", failing_relay_once)
    relay = OutboxRelay(
        _publisher,
        interval=0.01,
        session_factory=lambda: session,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await relay.run_once()

    assert session.closed


async def test_relay_loop_logs_failures_and_keeps_running(monkeypatch, caplog):
    passes = 0

    async def flaky_relay_once(*_args, **_kwargs):
        nonlocal passes
        passes += 1
        if passes == 1:
            raise RuntimeError("database unavailable")
        return 0

    monkeypatch.setattr(outbox_relay_module, "relay_once", flaky_relay_once)
    relay = OutboxRelay(
        _publisher,
        interval=0.01,
        session_factory=_FakeSession,
    )

    with caplog.at_level(logging.ERROR, logger="platform.outbox_relay"):
        await relay.start()
        for _ in range(300):
            if passes >= 2:
                break
            await asyncio.sleep(0.005)
        await relay.stop()

    assert passes >= 2
    assert "outbox relay pass failed" in caplog.text


async def test_relay_start_and_stop_lifecycle(monkeypatch):
    passes = 0

    async def fake_relay_once(*_args, **_kwargs):
        nonlocal passes
        passes += 1
        return 0

    monkeypatch.setattr(outbox_relay_module, "relay_once", fake_relay_once)
    relay = OutboxRelay(
        _publisher,
        interval=0.01,
        session_factory=_FakeSession,
    )

    await relay.start()
    await relay.start()  # idempotent while running
    assert relay.running

    for _ in range(200):
        if passes >= 2:
            break
        await asyncio.sleep(0.005)

    await relay.stop()
    assert not relay.running
    assert passes >= 2


async def test_relay_stop_without_start_is_a_noop():
    relay = OutboxRelay(_publisher)

    await relay.stop()

    assert not relay.running
