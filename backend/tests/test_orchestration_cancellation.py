"""Process-local cancellation registry and durable DB watcher.

The registry only ever contains executions running in the current process;
everything else is covered by the watcher polling the durable
``Execution.status`` flag at ``CANCEL_POLL_S``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from app.orchestration import cancellation


class _StatusSession:
    """Fake session that exposes only ``scalar`` — no row hydration API."""

    def __init__(self, factory: _FakeSessionFactory) -> None:
        self._factory = factory

    def __enter__(self) -> _StatusSession:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def scalar(self, statement: Any) -> str:
        self._factory.statements.append(statement)
        self._factory.first_read.set()
        if self._factory.statuses:
            return self._factory.statuses.pop(0)
        return self._factory.default

    def get(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("cancel watcher must not hydrate execution rows")

    def query(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("cancel watcher must use a status-only scalar query")


class _FakeSessionFactory:
    """Hands out one fresh fake session per polling tick."""

    def __init__(self, statuses: list[str], *, default: str = "running") -> None:
        self.statuses = list(statuses)
        self.default = default
        self.statements: list[Any] = []
        self.session_count = 0
        self.first_read = asyncio.Event()

    def __call__(self) -> _StatusSession:
        self.session_count += 1
        return _StatusSession(self)


def test_register_signal_and_unregister() -> None:
    execution_id = "exec_registry"
    cancellation.unregister(execution_id)
    assert cancellation.signal(execution_id) is False

    event = cancellation.register(execution_id)
    assert event is not None
    assert event.is_set() is False

    assert cancellation.signal(execution_id) is True
    assert event.is_set() is True

    cancellation.unregister(execution_id)
    # Unregistered ids are no longer process-local runs.
    assert cancellation.signal(execution_id) is False


def test_unregister_leaves_no_registry_entries() -> None:
    execution_ids = [f"exec_leak_{i}" for i in range(5)]
    try:
        for execution_id in execution_ids:
            cancellation.register(execution_id)
        for execution_id in execution_ids:
            assert execution_id in cancellation._ACTIVE_CANCEL_EVENTS

        for execution_id in execution_ids:
            cancellation.unregister(execution_id)
        assert not any(
            execution_id in cancellation._ACTIVE_CANCEL_EVENTS
            for execution_id in execution_ids
        )

        # Unknown ids are a no-op, repeated unregister included.
        cancellation.unregister("exec_never_registered")
        cancellation.unregister("exec_never_registered")
        assert "exec_never_registered" not in cancellation._ACTIVE_CANCEL_EVENTS
    finally:
        for execution_id in execution_ids:
            cancellation.unregister(execution_id)


def test_execution_runtime_signal_cancel_delegates() -> None:
    from app.execution_runtime import signal_cancel

    execution_id = "exec_runtime_delegate"
    cancellation.unregister(execution_id)
    assert signal_cancel(execution_id) is False

    event = cancellation.register(execution_id)
    try:
        assert signal_cancel(execution_id) is True
        assert event.is_set() is True
    finally:
        cancellation.unregister(execution_id)

    # No in-process run remains: the API's call reports the external case.
    assert signal_cancel(execution_id) is False


@pytest.mark.parametrize("durable_status", ["cancelling", "cancelled"])
async def test_watch_durable_cancel_flips_on_durable_status(
    durable_status: str,
) -> None:
    event = asyncio.Event()
    factory = _FakeSessionFactory(["running", durable_status])

    await asyncio.wait_for(
        cancellation.watch_durable_cancel(
            "exec_watch", event, session_factory=factory, poll_s=0
        ),
        timeout=2,
    )

    assert event.is_set() is True
    assert factory.session_count == 2
    assert len(factory.statements) == 2
    # One fresh status-only query per tick: no full-row hydration.
    description = factory.statements[0].column_descriptions[0]
    assert description["name"] == "status"
    assert list(factory.statements[0].selected_columns.keys()) == ["status"]


async def test_watch_durable_cancel_exits_when_event_set() -> None:
    event = asyncio.Event()
    event.set()
    factory = _FakeSessionFactory([])

    await asyncio.wait_for(
        cancellation.watch_durable_cancel(
            "exec_already_set", event, session_factory=factory, poll_s=0
        ),
        timeout=1,
    )

    assert factory.session_count == 0


async def test_watch_durable_cancel_exits_on_process_local_signal() -> None:
    event = asyncio.Event()
    factory = _FakeSessionFactory([], default="running")
    task = asyncio.create_task(
        cancellation.watch_durable_cancel(
            "exec_local_signal", event, session_factory=factory, poll_s=0.01
        )
    )
    try:
        await asyncio.wait_for(factory.first_read.wait(), timeout=1)
        event.set()
        await asyncio.wait_for(task, timeout=1)
    finally:
        task.cancel()

    assert task.done() is True
    assert task.cancelled() is False


async def test_watch_durable_cancel_logs_db_error_and_exits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = asyncio.Event()

    def broken_factory() -> _StatusSession:
        raise RuntimeError("database unavailable")

    with caplog.at_level(logging.ERROR, logger="orchestration.cancellation"):
        await asyncio.wait_for(
            cancellation.watch_durable_cancel(
                "exec_db_error", event, session_factory=broken_factory, poll_s=0
            ),
            timeout=1,
        )

    assert event.is_set() is False
    assert "cancel watch failed for exec_db_error" in caplog.text


async def test_watch_durable_cancel_exits_after_scalar_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = asyncio.Event()

    class _BrokenSession:
        def __enter__(self) -> _BrokenSession:
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def scalar(self, statement: Any) -> str:
            raise RuntimeError("query failed")

    with caplog.at_level(logging.ERROR, logger="orchestration.cancellation"):
        await asyncio.wait_for(
            cancellation.watch_durable_cancel(
                "exec_scalar_error", event, session_factory=_BrokenSession, poll_s=0
            ),
            timeout=1,
        )

    assert event.is_set() is False
    assert "cancel watch failed for exec_scalar_error" in caplog.text
