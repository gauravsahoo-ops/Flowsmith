"""Add cached MCP tool discovery results.

Revision ID: c3d4e5f6a7b8
Revises: f4a5b6c7d8e9
Create Date: 2026-11-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "mcp_tool_cache"):
        return
    op.create_table(
        "mcp_tool_cache",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "server_id",
            sa.String(length=64),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column(
            "risk_class", sa.String(length=32), nullable=False, server_default="write"
        ),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("server_id", "tool_name", name="uq_mcp_tool_cache_server_tool"),
    )
    op.create_index("ix_mcp_tool_cache_server_id", "mcp_tool_cache", ["server_id"])
    op.create_index(
        "ix_mcp_tool_cache_server_enabled", "mcp_tool_cache", ["server_id", "enabled"]
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "mcp_tool_cache"):
        op.drop_table("mcp_tool_cache")
