"""Trigger registration models (spec 32: webhooks table, 33: schedules).

Triggers snapshot the workflow JSON and version at activation time, so
a webhook/schedule fires the exact version the user activated. `sync` in app/triggers/registry.py keeps these tables in line
with the active workflows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User, WorkflowRecord

class WebhookTrigger(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    method: Mapped[str] = mapped_column(String(16), default="POST", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Declared so the unit of work orders inserts by FK dependency.
    workflow: Mapped["WorkflowRecord"] = relationship()
    user: Mapped["User"] = relationship()


class ScheduleTrigger(Base):
    __tablename__ = "schedule_triggers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cron: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    # Interval metadata for scheduler (seconds/minutes/hours/etc.)
    interval_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    interval_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Declared so the unit of work orders inserts by FK dependency.
    workflow: Mapped["WorkflowRecord"] = relationship()
    user: Mapped["User"] = relationship()


class PollingTrigger(Base):
    """A generic HTTP polling trigger snapshot for an active workflow."""

    __tablename__ = "polling_triggers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(16), default="GET", nullable=False)
    headers: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False)
    json_body: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    items_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    dedupe_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    seen_keys: Mapped[list] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped["WorkflowRecord"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("workflow_id", "node_id", name="uq_polling_trigger_node"),
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # Declared so the unit of work orders inserts by FK dependency.
    workflow: Mapped["WorkflowRecord"] = relationship()
    user: Mapped["User"] = relationship()
