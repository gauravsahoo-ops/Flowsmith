"""Per-user tenant scope: private branding and generated-connector ownership.

Revision ID: b2c3d4e5f6a7
Revises: f9a0b1c2d3e4
Create Date: 2026-11-26 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(bind, "branding_settings", "user_id"):
        op.add_column(
            "branding_settings",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )

    indexes = {item["name"] for item in inspector.get_indexes("branding_settings")}
    if "ix_branding_settings_user_id" not in indexes:
        op.create_index(
            "ix_branding_settings_user_id",
            "branding_settings",
            ["user_id"],
            unique=True,
        )

    # Existing organization branding becomes private to the founder. A user
    # with several branded organizations keeps one row; the rest are dropped.
    op.execute(sa.text(
        """
        UPDATE branding_settings AS b
           SET user_id = (
               SELECT o.founder_id FROM organizations AS o WHERE o.id = b.organization_id
           )
         WHERE b.organization_id IS NOT NULL
           AND b.user_id IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM branding_settings AS b2
                WHERE b2.user_id = (
                    SELECT o2.founder_id FROM organizations AS o2
                     WHERE o2.id = b.organization_id
                )
           )
        """
    ))
    op.execute(sa.text(
        "DELETE FROM branding_settings "
        "WHERE user_id IS NULL AND organization_id IS NOT NULL"
    ))

    if not inspector.has_table("generated_connectors"):
        op.create_table(
            "generated_connectors",
            sa.Column("connector_key", sa.String(length=128), primary_key=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="import"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_generated_connectors_user_id",
            "generated_connectors",
            ["user_id"],
            unique=False,
        )

    # Existing packs already record their installer; preserve that ownership
    # while keeping shipped generated connectors (no row) public.
    op.execute(sa.text(
        """
        INSERT INTO generated_connectors (connector_key, user_id, source, created_at)
        SELECT p.connector_key, p.installed_by, 'pack', p.created_at
          FROM connector_packs AS p
         WHERE NOT EXISTS (
               SELECT 1 FROM generated_connectors AS g
                WHERE g.connector_key = p.connector_key
         )
        """
    ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("generated_connectors"):
        op.drop_table("generated_connectors")
    indexes = {item["name"] for item in inspector.get_indexes("branding_settings")}
    if "ix_branding_settings_user_id" in indexes:
        op.drop_index("ix_branding_settings_user_id", table_name="branding_settings")
    if _has_column(bind, "branding_settings", "user_id"):
        op.drop_column("branding_settings", "user_id")
