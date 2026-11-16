"""Add per-server MCP stdio sandbox policy.

Revision ID: e7f8a9b0c1d2
Revises: c3d4e5f6a7b8
Create Date: 2026-11-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    columns = (
        sa.Column(
            "sandbox_backend",
            sa.String(length=16),
            nullable=False,
            server_default="subprocess",
        ),
        sa.Column("sandbox_image", sa.String(length=255), nullable=True),
        sa.Column(
            "sandbox_workspace_mode",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
        sa.Column("sandbox_workspace_path", sa.String(length=2000), nullable=True),
        sa.Column(
            "sandbox_network",
            sa.String(length=64),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "sandbox_read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    for column in columns:
        if _has_column(bind, "mcp_servers", column.name):
            continue
        op.add_column("mcp_servers", column)


def downgrade() -> None:
    bind = op.get_bind()
    for name in (
        "sandbox_read_only",
        "sandbox_network",
        "sandbox_workspace_path",
        "sandbox_workspace_mode",
        "sandbox_image",
        "sandbox_backend",
    ):
        if _has_column(bind, "mcp_servers", name):
            op.drop_column("mcp_servers", name)
