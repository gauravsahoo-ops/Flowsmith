"""Error Monitoring & Notification models.

Normalized error event, delivery records, and user notification preferences.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base

if TYPE_CHECKING:
    from app.models import User, WorkflowRecord, Execution


def generate_uuid() -> str:
    return str(uuid.uuid4())


class ErrorEvent(Base):
    """Normalized captured error across workflows, credentials, nodes, or platform."""

    __tablename__ = "error_events"
    __table_args__ = (
        Index("ix_error_events_user_created", "user_id", "created_at"),
        Index("ix_error_events_fingerprint", "fingerprint"),
        Index("ix_error_events_category_severity", "category", "severity"),
        Index("ix_error_events_workflow", "workflow_id"),
        Index("ix_error_events_execution", "execution_id"),
        Index("ix_error_events_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), default="ERROR", nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    workflow_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    workflow_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    execution_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    connector_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retry_exhausted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Technical details safely sanitized (no access tokens or secrets)
    technical_details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )

    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DETECTED", nullable=False)
    notification_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])
    notifications: Mapped[list["NotificationRecord"]] = relationship(
        back_populates="error_event", cascade="all, delete-orphan"
    )


class NotificationRecord(Base):
    """Log of every notification dispatch attempt (email, webhook, etc.)."""

    __tablename__ = "notification_records"
    __table_args__ = (
        Index("ix_notification_records_user", "user_id"),
        Index("ix_notification_records_event", "error_event_id"),
        Index("ix_notification_records_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    error_event_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("error_events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PENDING, SENT, FAILED, SUPPRESSED
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_event: Mapped["ErrorEvent"] = relationship(back_populates="notifications")
    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])


class NotificationPreference(Base):
    """Per-user alert configuration and frequency throttling."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_auth_expired: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_rate_limit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    custom_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
