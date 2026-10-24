"""Add LDAP sync state and organization-level group access mappings.

Revision ID: a5c6d7e8f9a0
Revises: f3a4b5c6d7e8
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "users")
    if "ldap_dn" not in existing:
        op.add_column("users", sa.Column("ldap_dn", sa.String(length=1024), nullable=True))
        op.create_index("ix_users_ldap_dn", "users", ["ldap_dn"])
    if "ldap_groups" not in existing:
        op.add_column("users", sa.Column("ldap_groups", sa.Text(), nullable=True))
    if "ldap_synced_at" not in existing:
        op.add_column(
            "users", sa.Column("ldap_synced_at", sa.DateTime(timezone=True), nullable=True)
        )

    if not sa.inspect(bind).has_table("identity_organization_access"):
        op.create_table(
            "identity_organization_access",
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
                "organization_id",
                sa.String(length=64),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
            sa.Column("permission", sa.String(length=16), nullable=False, server_default="view"),
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
            sa.UniqueConstraint(
                "user_id", "source", "group_name", "organization_id",
                name="uq_identity_organization_access",
            ),
        )
        op.create_index(
            "ix_identity_organization_access_user_id",
            "identity_organization_access",
            ["user_id"],
        )
        op.create_index(
            "ix_identity_organization_access_organization_id",
            "identity_organization_access",
            ["organization_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("identity_organization_access"):
        op.drop_table("identity_organization_access")
    existing = _columns(bind, "users")
    if "ldap_synced_at" in existing:
        op.drop_column("users", "ldap_synced_at")
    if "ldap_groups" in existing:
        op.drop_column("users", "ldap_groups")
    if "ldap_dn" in existing:
        op.drop_index("ix_users_ldap_dn", table_name="users")
        op.drop_column("users", "ldap_dn")
