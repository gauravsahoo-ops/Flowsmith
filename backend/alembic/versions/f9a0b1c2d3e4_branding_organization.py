"""Add organization scope to branding settings.

Revision ID: f9a0b1c2d3e4
Revises: e7f8a9b0c1d2
Create Date: 2026-11-26 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "branding_settings", "organization_id"):
        op.add_column(
            "branding_settings",
            sa.Column("organization_id", sa.String(length=64), nullable=True),
        )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("branding_settings")}
    if "ix_branding_settings_organization_id" not in indexes:
        op.create_index(
            "ix_branding_settings_organization_id",
            "branding_settings",
            ["organization_id"],
            unique=True,
        )

    # Locally registered accounts already own a personal organization and
    # workspace but legacy rows never recorded them on the user. Pinning them
    # makes organization-scoped settings deterministic without moving users
    # that were provisioned into a shared organization.
    op.execute(sa.text(
        """
        UPDATE users
           SET organization_id = 'org_personal_' || id
         WHERE organization_id IS NULL
           AND EXISTS (
               SELECT 1 FROM organizations o
                WHERE o.id = 'org_personal_' || users.id
           )
        """
    ))
    op.execute(sa.text(
        """
        UPDATE users
           SET workspace_id = 'ws_personal_' || id
         WHERE workspace_id IS NULL
           AND EXISTS (
               SELECT 1 FROM workspaces w
                WHERE w.id = 'ws_personal_' || users.id
           )
        """
    ))


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("branding_settings")}
    if "ix_branding_settings_organization_id" in indexes:
        op.drop_index("ix_branding_settings_organization_id", table_name="branding_settings")
    if _has_column(bind, "branding_settings", "organization_id"):
        op.drop_column("branding_settings", "organization_id")
