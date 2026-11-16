"""Add tenant-scoped MCP server registry.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-11-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "mcp_servers"):
        return
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(length=64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("transport", sa.String(length=16), nullable=False, server_default="http"),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column(
            "credential_id",
            sa.String(length=64),
            sa.ForeignKey("credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trust_level", sa.String(length=16), nullable=False, server_default="untrusted"),
        sa.Column("allowed_tools", sa.JSON(), nullable=True),
        sa.Column("denied_tools", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint("workspace_id", "name", name="uq_mcp_server_workspace_name"),
    )
    op.create_index("ix_mcp_servers_organization_id", "mcp_servers", ["organization_id"])
    op.create_index("ix_mcp_servers_workspace_id", "mcp_servers", ["workspace_id"])
    op.create_index("ix_mcp_servers_credential_id", "mcp_servers", ["credential_id"])
    op.create_index("ix_mcp_servers_created_by", "mcp_servers", ["created_by"])
    op.create_index(
        "ix_mcp_servers_workspace_enabled", "mcp_servers", ["workspace_id", "enabled"]
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "mcp_servers"):
        op.drop_table("mcp_servers")
