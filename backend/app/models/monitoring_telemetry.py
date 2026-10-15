"""Execution Steps, API Request Telemetry, and Retry History models.

Provides structured persistence for:
1. Individual execution steps with record counts and error taxonomy.
2. Outbound HTTP request/response inspection with sanitization.
3. Execution retry correlation and attempt tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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
    from app.models.execution import Execution
    from app.models.user import User


def generate_uuid() -> str:
    return str(uuid.uuid4())


class ExecutionStep(Base):
    """Normalized step trace for DAG nodes and connector operations."""

    __tablename__ = "execution_steps"
    __table_args__ = (
        Index("ix_exec_steps_exec_seq", "execution_id", "sequence_number"),
        Index("ix_exec_steps_exec_node", "execution_id", "node_id"),
        Index("ix_exec_steps_status", "status"),
        Index("ix_exec_steps_connector", "connector_id"),
        Index("ix_exec_steps_org_started", "organization_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    step_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    sequence_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="success", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    input_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    inputs: Mapped[Any | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    outputs: Mapped[Any | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    error_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def step_metadata(self) -> dict | None:
        return self.error_details

    @step_metadata.setter
    def step_metadata(self, val: dict | None) -> None:
        self.error_details = val


class ApiRequestTelemetry(Base):
    """Captured outbound HTTP requests and responses from connectors and HTTP nodes."""

    __tablename__ = "api_request_logs"
    __table_args__ = (
        Index("ix_api_req_exec", "execution_id", "request_timestamp"),
        Index("ix_api_req_step", "step_id"),
        Index("ix_api_req_connector", "connector_id"),
        Index("ix_api_req_status", "http_status_code"),
        Index("ix_api_req_org", "organization_id", "request_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    step_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    connector_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    operation: Mapped[str | None] = mapped_column(String(64), nullable=True)

    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    request_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False
    )

    query_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_payload: Mapped[Any | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)

    http_status_code: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    response_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_payload: Mapped[Any | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)

    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connector_name: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False
    )


class ExecutionRetryHistory(Base):
    """Tracks manual and automatic retry relationships between execution runs."""

    __tablename__ = "execution_retries"
    __table_args__ = (
        Index("ix_exec_retries_orig", "original_execution_id", "attempt_number"),
        Index("ix_exec_retries_retry", "retry_execution_id"),
        Index("ix_exec_retries_org", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    original_execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    retry_execution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retry_type: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    retry_trigger: Mapped[str | None] = mapped_column(String(32), default="manual", nullable=True)
    retry_policy: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    failed_step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    initiated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False
    )
