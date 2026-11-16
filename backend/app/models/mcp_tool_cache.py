"""Cached MCP tool discovery results.

One row per tool exposed by an MCP server. Discovery upserts rows and disables
tools that disappeared from ``tools/list`` so policy checks fail closed instead
of silently retaining stale capabilities.
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class MCPToolCache(Base):
    __tablename__ = "mcp_tool_cache"
    __table_args__ = (
        UniqueConstraint("server_id", "tool_name", name="uq_mcp_tool_cache_server_tool"),
        Index("ix_mcp_tool_cache_server_enabled", "server_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    server_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), default="write", nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
