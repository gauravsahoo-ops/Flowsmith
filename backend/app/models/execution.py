"""Execution record model (spec 5: executions).

Stores a snapshot of the workflow JSON that was run, so retry re-runs
the exact saved version (spec 24.3), plus per-node outcomes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User, WorkflowRecord

class Execution(Base):
    __tablename__ = "executions"
    # Mirrors migration a1b2c3d4e5f6: covers ORDER BY started_at DESC /
    # WHERE workflow_id = :id listings and has_running_execution checks.
    __table_args__ = (
        Index("ix_executions_workflow_started", "workflow_id", text("started_at DESC")),
        Index("ix_executions_wf_status", "workflow_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    trigger_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True, nullable=False)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    node_statuses: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Pause metadata for executions waiting on external input (Phase 32):
    # {"node_id": ..., "message": ...} while status == waiting_approval.
    pause_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Declared so the unit of work orders inserts by FK dependency
    # (executions after workflows) instead of mapper-name sort order.
    workflow: Mapped["WorkflowRecord"] = relationship()
    user: Mapped["User"] = relationship()
