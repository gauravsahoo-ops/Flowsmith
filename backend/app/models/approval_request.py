"""Durable human-approval requests.

An approval is a first-class record: it survives worker restarts, supports
quorum and separation-of-duties, and is linked to the run/node/tool it gates.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_org_status", "organization_id", "status", "created_at"),
        Index("ix_approval_requests_expires_at", "expires_at"),
        Index("ix_approval_requests_decision_nonce", "decision_nonce", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workflow_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    node_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    risk_tier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    affected_resources: Mapped[list | None] = mapped_column(JSON, nullable=True)

    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    approvers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quorum: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    separation_of_duties: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True, nullable=False
    )
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_nonce: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
