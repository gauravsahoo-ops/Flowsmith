"""Transactional outbox tests."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.db import get_session
from app.models import OutboxEvent
from app.platform.events import RUN_COMPLETED, new_event
from app.platform.outbox import (
    mark_failed,
    pending_events,
    record_event,
    relay_once,
    to_envelope,
)


def _event(event_id: str = "evt_outbox_1"):
    return new_event(
        RUN_COMPLETED,
        tenant_id="org_outbox",
        workspace_id="ws_outbox",
        run_id="run_outbox",
        payload={"status": "success"},
        correlation_id="corr_outbox",
    )


def test_record_event_is_idempotent():
    with get_session() as db:
        event = _event()
        first = record_event(db, event)
        second = record_event(db, event)
        assert first.id == second.id
        count = db.scalar(select(func.count()).select_from(OutboxEvent))
        assert count == 1
        restored = to_envelope(first)
        assert restored.event_id == event.event_id
        assert restored.payload == {"status": "success"}


def test_relay_publishes_pending_events_and_marks_them():
    with get_session() as db:
        event = _event("evt_outbox_relay")
        row = record_event(db, event)
        seen = []

        async def publisher(envelope):
            seen.append(envelope)

        published = asyncio.run(relay_once(db, publisher))
        assert published == 1
        assert seen[0].event_id == event.event_id
        db.refresh(row)
        assert row.published_at is not None
        assert row.attempts == 1
        assert pending_events(db) == []


def test_relay_records_failure_without_losing_the_event():
    with get_session() as db:
        event = _event("evt_outbox_fail")
        row = record_event(db, event)

        async def publisher(_envelope):
            raise RuntimeError("broker unavailable")

        published = asyncio.run(relay_once(db, publisher))
        assert published == 0
        db.refresh(row)
        assert row.published_at is None
        assert row.attempts == 1
        assert "RuntimeError" in (row.last_error or "")
        assert pending_events(db, max_attempts=2) == [row]

        mark_failed(db, row, "second failure")
        assert pending_events(db, max_attempts=2) == []
