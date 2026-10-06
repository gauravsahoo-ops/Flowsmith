"""Workflow record model (spec 5: workflows).

`data` holds the full workflow JSON (the section 6 contract). `version`
bumps on every save so executions can reference the exact saved version
(spec 24.2/24.3). Versions are immutable snapshots - once created, a
workflow version's data never changes; new saves create new version
entries rather than mutating existing ones.

Each workflow belongs to a workspace (spec 38: multi-tenancy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User, Workspace

class WorkflowRecord(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # Version is now a snapshot identifier. Each save creates a new
    # WorkflowRecord with an incremented version; existing records are
    # never mutated (immutable workflow versions, spec 24.2/24.3).
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # The workspace this workflow belongs to (spec 38)
    workspace_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("workspaces.id"), index=True, nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    # Soft-delete marker (Phase: workflow delete). Deleted workflows are
    # hidden from every access path but their rows stay: versions,
    # shares, and — critically — execution history remain auditable, and
    # PostgreSQL FK constraints (no ON DELETE on executions/versions)
    # are never violated.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Declared so the unit of work orders inserts by FK dependency.
    user: Mapped["User"] = relationship()
    workspace: Mapped["Workspace | None"] = relationship()
