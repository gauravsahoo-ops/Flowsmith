"""File record model (Phase 19: S3-compatible object storage).

Metadata lives in PostgreSQL; the bytes live in the configured object
store (local filesystem by default, S3-compatible when enabled).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("workspaces.id"), index=True, nullable=True
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, server_default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    object_key: Mapped[str] = mapped_column(String(512), unique=True, index=True, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata_", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
