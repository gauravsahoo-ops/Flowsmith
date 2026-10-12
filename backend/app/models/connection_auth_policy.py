"""Connection Authentication Policy, Recovery Job, and Credential Audit Models.

Stores per-integration recovery configurations, state machine statuses,
background retry orchestration jobs, and safe audit logs.
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
from app.models.recovery_state import ConnectionState, RecoveryMode

if TYPE_CHECKING:
    from app.models import Credential, User


def generate_uuid() -> str:
    return str(uuid.uuid4())


class ConnectionAuthPolicy(Base):
    """Per-connection recovery settings, state machine state, and health metrics."""

    __tablename__ = "connection_auth_policies"
    __table_args__ = (
        Index("ix_conn_policy_user_state", "user_id", "state"),
        Index("ix_conn_policy_next_recovery", "next_recovery_at"),
        Index("ix_conn_policy_cred_id", "credential_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    credential_id: Mapped[str] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Policy mode: automatic | manual | automatic_with_notifications
    mode: Mapped[str] = mapped_column(String(32), default=RecoveryMode.AUTOMATIC.value, nullable=False)

    # Current explicit lifecycle state
    state: Mapped[str] = mapped_column(String(32), default=ConnectionState.CONNECTED.value, nullable=False)

    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    auth_type: Mapped[str] = mapped_column(String(64), default="oauth2", nullable=False)

    # Notification preferences
    notify_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_recovery_failure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_upcoming_expiry: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps & Tracking
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_recovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    credential: Mapped["Credential"] = relationship()
    user: Mapped["User"] = relationship()


class CredentialRecoveryJob(Base):
    """Durable queue of background credential recovery tasks."""

    __tablename__ = "credential_recovery_jobs"
    __table_args__ = (
        Index("ix_rec_jobs_status_scheduled", "status", "scheduled_at"),
        Index("ix_rec_jobs_cred_status", "credential_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    credential_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    lock_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CredentialAuditEvent(Base):
    """Sanitized audit trail of credential state transitions and recovery attempts."""

    __tablename__ = "credential_audit_events"
    __table_args__ = (
        Index("ix_cred_audit_cred_created", "credential_id", "created_at"),
        Index("ix_cred_audit_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    credential_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), default="system", nullable=False)

    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
