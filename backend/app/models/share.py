"""Workflow sharing model (security phase): a workflow can be shared
with other users as viewer or editor. The owner keeps full control;
shares cascade when the workflow is deleted."""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User, WorkflowRecord

class WorkflowShare(Base):
    __tablename__ = "workflow_shares"
    __table_args__ = (UniqueConstraint("workflow_id", "user_id", name="uq_share"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    permission: Mapped[str] = mapped_column(String(16), default="view", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Declared so the unit of work orders inserts by FK dependency.
    workflow: Mapped["WorkflowRecord"] = relationship()
    user: Mapped["User"] = relationship()
