"""Outbox persistence and relay.

Domain services call ``record_event`` in the same transaction as their state
change. A relay claims unpublished rows and publishes them at least once;
consumers dedupe by ``event_id``.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OutboxEvent
from app.platform.contracts import EventEnvelope

Publisher = Callable[[EventEnvelope], Awaitable[None] | None]


def to_envelope(row: OutboxEvent) -> EventEnvelope:
    return EventEnvelope(
        event_id=row.event_id,
        event_type=row.event_type,
        schema_version=row.schema_version,
        occurred_at=row.created_at.replace(tzinfo=row.created_at.tzinfo or UTC),
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        node_id=row.node_id,
        trace_id=None,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        idempotency_key=row.idempotency_key,
        payload=dict(row.payload or {}),
    )


def record_event(
    db: Session,
    event: EventEnvelope,
    *,
    commit: bool = True,
) -> OutboxEvent:
    """Persist an event; idempotent on ``event_id``."""
    existing = db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_id == event.event_id)
    )
    if existing is not None:
        return existing

    row = OutboxEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        tenant_id=event.tenant_id,
        workspace_id=event.workspace_id,
        run_id=event.run_id,
        node_id=event.node_id,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        idempotency_key=event.idempotency_key,
        payload=dict(event.payload),
        attempts=0,
    )
    db.add(row)
    if not commit:
        return row
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(OutboxEvent).where(OutboxEvent.event_id == event.event_id)
        )
        if existing is None:
            raise
        return existing
    db.refresh(row)
    return row


def pending_events(
    db: Session,
    *,
    limit: int = 100,
    max_attempts: int = 10,
) -> list[OutboxEvent]:
    return list(
        db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.attempts < max_attempts,
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(max(1, min(limit, 1000)))
            .with_for_update(skip_locked=True)
        ).all()
    )


def mark_published(db: Session, row: OutboxEvent, *, commit: bool = True) -> None:
    row.attempts += 1
    row.published_at = datetime.now(UTC)
    row.last_error = None
    if commit:
        db.commit()


def mark_failed(
    db: Session,
    row: OutboxEvent,
    error: str,
    *,
    commit: bool = True,
) -> None:
    row.attempts += 1
    row.last_error = error[:4000]
    if commit:
        db.commit()


async def relay_once(
    db: Session,
    publish: Publisher,
    *,
    limit: int = 100,
    max_attempts: int = 10,
) -> int:
    """Publish one batch and return the number of successfully published rows."""
    rows = pending_events(db, limit=limit, max_attempts=max_attempts)
    published = 0
    for row in rows:
        try:
            result = publish(to_envelope(row))
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 - relay must record failures
            mark_failed(db, row, f"{type(exc).__name__}: {exc}", commit=False)
            continue
        mark_published(db, row, commit=False)
        published += 1
    if rows:
        db.commit()
    return published
