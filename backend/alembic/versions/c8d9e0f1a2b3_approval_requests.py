"""Add durable approval requests.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-12 00:00:00.000000

Approval requests are first-class records so a paused run survives worker
restarts and approval decisions can be audited independently of the execution
row's ``pause_state`` JSON.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "approval_requests"):
        return
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.String(length=64), nullable=True),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("risk_tier", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("arguments", sa.JSON(), nullable=True),
        sa.Column("preview", sa.JSON(), nullable=True),
        sa.Column("affected_resources", sa.JSON(), nullable=True),
        sa.Column(
            "requested_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approvers", sa.JSON(), nullable=True),
        sa.Column("quorum", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("separation_of_duties", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column(
            "decided_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_nonce", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_approval_requests_run_id", "approval_requests", ["run_id"])
    op.create_index("ix_approval_requests_workflow_id", "approval_requests", ["workflow_id"])
    op.create_index("ix_approval_requests_organization_id", "approval_requests", ["organization_id"])
    op.create_index("ix_approval_requests_workspace_id", "approval_requests", ["workspace_id"])
    op.create_index("ix_approval_requests_requested_by", "approval_requests", ["requested_by"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])
    op.create_index("ix_approval_requests_expires_at", "approval_requests", ["expires_at"])
    op.create_index(
        "ix_approval_requests_org_status",
        "approval_requests",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_approval_requests_decision_nonce",
        "approval_requests",
        ["decision_nonce"],
        unique=True,
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "approval_requests"):
        op.drop_table("approval_requests")
