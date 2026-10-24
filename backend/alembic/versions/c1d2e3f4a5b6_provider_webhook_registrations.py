"""Add provider-side webhook registration records.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if _has_table(op.get_bind(), "provider_webhook_registrations"):
        return
    op.create_table(
        "provider_webhook_registrations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(length=64),
            sa.ForeignKey("workflows.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.String(length=64), nullable=False),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("provider_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("signing_secret", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "workflow_id", "node_id", "provider",
            name="uq_provider_webhook_node",
        ),
    )
    op.create_index(
        "ix_provider_webhook_registrations_workflow_id",
        "provider_webhook_registrations",
        ["workflow_id"],
    )
    op.create_index(
        "ix_provider_webhook_registrations_user_id",
        "provider_webhook_registrations",
        ["user_id"],
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "provider_webhook_registrations"):
        op.drop_table("provider_webhook_registrations")
