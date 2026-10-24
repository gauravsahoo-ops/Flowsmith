"""Add SCIM groups and group membership mappings.

Revision ID: a3c4d5e6f7b8
Revises: b1d598391ba2
Create Date: 2026-10-23 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3c4d5e6f7b8"
down_revision: Union[str, Sequence[str], None] = "b1d598391ba2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "scim_groups"):
        op.create_table(
            "scim_groups",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column(
                "workspace_id",
                sa.String(length=64),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("organization_role", sa.String(length=16), nullable=True),
            sa.Column("organization_permission", sa.String(length=16), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
            sa.UniqueConstraint("display_name", name="uq_scim_groups_display_name"),
            sa.UniqueConstraint("workspace_id", name="uq_scim_groups_workspace_id"),
        )
        op.create_index("ix_scim_groups_external_id", "scim_groups", ["external_id"])
        op.create_index("ix_scim_groups_workspace_id", "scim_groups", ["workspace_id"])

    if not _has_table(bind, "scim_group_members"):
        op.create_table(
            "scim_group_members",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "group_id",
                sa.String(length=64),
                sa.ForeignKey("scim_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "member_group_id",
                sa.String(length=64),
                sa.ForeignKey("scim_groups.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "added_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("group_id", "user_id", name="uq_scim_group_member"),
            sa.UniqueConstraint(
                "group_id", "member_group_id", name="uq_scim_group_member_group"
            ),
        )
        op.create_index("ix_scim_group_members_group_id", "scim_group_members", ["group_id"])
        op.create_index("ix_scim_group_members_user_id", "scim_group_members", ["user_id"])
        op.create_index(
            "ix_scim_group_members_member_group_id", "scim_group_members", ["member_group_id"]
        )

    if not _has_table(bind, "scim_group_access"):
        op.create_table(
            "scim_group_access",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "group_id",
                sa.String(length=64),
                sa.ForeignKey("scim_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_workspace_membership",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_organization_membership",
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
            sa.UniqueConstraint("group_id", "user_id", name="uq_scim_group_access"),
        )
        op.create_index("ix_scim_group_access_group_id", "scim_group_access", ["group_id"])
        op.create_index("ix_scim_group_access_user_id", "scim_group_access", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "scim_group_access"):
        op.drop_table("scim_group_access")
    if _has_table(bind, "scim_group_members"):
        op.drop_table("scim_group_members")
    if _has_table(bind, "scim_groups"):
        op.drop_table("scim_groups")
