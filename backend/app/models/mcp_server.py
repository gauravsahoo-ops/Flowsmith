"""Tenant-scoped MCP server registry.

Credentials are referenced by id; the registry never stores raw MCP secrets.
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
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class MCPServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_mcp_server_workspace_name"),
        Index("ix_mcp_servers_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    transport: Mapped[str] = mapped_column(String(16), default="http", nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    auth_type: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    credential_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("credentials.id", ondelete="SET NULL"), index=True, nullable=True
    )
    trust_level: Mapped[str] = mapped_column(String(16), default="untrusted", nullable=False)
    allowed_tools: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    denied_tools: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Per-server stdio sandbox policy. Docker is always opt-in: the default is
    # the historical host subprocess backend. Empty image/workspace fields fall
    # back to the global MCP_STDIO_* settings at client construction time.
    sandbox_backend: Mapped[str] = mapped_column(
        String(16), default="subprocess", server_default="subprocess", nullable=False
    )
    sandbox_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sandbox_workspace_mode: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none", nullable=False
    )
    sandbox_workspace_path: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )
    sandbox_network: Mapped[str] = mapped_column(
        String(64), default="none", server_default="none", nullable=False
    )
    sandbox_read_only: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
