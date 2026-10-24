"""Add generic HTTP polling triggers.

Revision ID: b6c7d8e9f0a1
Revises: a5c6d7e8f9a0
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "a5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "polling_triggers"):
        return
    op.create_table(
        "polling_triggers",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "workflow_id", sa.String(length=64),
            sa.ForeignKey("workflows.id"), nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id"), nullable=False, index=True,
        ),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("workflow_data", sa.JSON(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="GET"),
        sa.Column("headers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("json_body", sa.JSON(), nullable=True),
        sa.Column("items_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("dedupe_field", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("seen_keys", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workflow_id", "node_id", name="uq_polling_trigger_node"),
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "polling_triggers"):
        op.drop_table("polling_triggers")
