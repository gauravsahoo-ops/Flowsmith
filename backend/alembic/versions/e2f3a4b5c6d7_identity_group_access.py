"""Add identity-provider group-to-workspace access mapping.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "identity_group_access"):
        return
    op.create_table(
        "identity_group_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("group_name", sa.String(length=255), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(length=64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("permission", sa.String(length=16), nullable=False, server_default="edit"),
        sa.Column(
            "created_workspace_membership",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "source", "group_name", "workspace_id",
            name="uq_identity_group_access",
        ),
    )
    op.create_index(
        "ix_identity_group_access_user_id", "identity_group_access", ["user_id"]
    )
    op.create_index(
        "ix_identity_group_access_workspace_id", "identity_group_access", ["workspace_id"]
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "identity_group_access"):
        op.drop_table("identity_group_access")
