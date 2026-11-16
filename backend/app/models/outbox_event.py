"""Transactional outbox for immutable platform events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_pending", "published_at", "created_at"),
        Index("ix_outbox_events_tenant_type", "tenant_id", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
