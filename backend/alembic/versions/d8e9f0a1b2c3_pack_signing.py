"""Add signed pack metadata and pack-owned template tracking.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table) if index.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    pack_columns = _columns(bind, "connector_packs")
    if "signed" not in pack_columns:
        op.add_column(
            "connector_packs",
            sa.Column("signed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "signing_key_id" not in pack_columns:
        op.add_column(
            "connector_packs",
            sa.Column("signing_key_id", sa.String(length=128), nullable=True),
        )
    if "manifest_sha256" not in pack_columns:
        op.add_column(
            "connector_packs",
            sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        )
    if "updated_at" not in pack_columns:
        op.add_column(
            "connector_packs",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    template_columns = _columns(bind, "workflow_templates")
    if "pack_key" not in template_columns:
        op.add_column(
            "workflow_templates",
            sa.Column("pack_key", sa.String(length=128), nullable=True),
        )
    if "ix_workflow_templates_pack_key" not in _indexes(bind, "workflow_templates"):
        op.create_index(
            "ix_workflow_templates_pack_key",
            "workflow_templates",
            ["pack_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "ix_workflow_templates_pack_key" in _indexes(bind, "workflow_templates"):
        op.drop_index("ix_workflow_templates_pack_key", table_name="workflow_templates")
    template_columns = _columns(bind, "workflow_templates")
    if "pack_key" in template_columns:
        op.drop_column("workflow_templates", "pack_key")

    pack_columns = _columns(bind, "connector_packs")
    for column in ("updated_at", "manifest_sha256", "signing_key_id", "signed"):
        if column in pack_columns:
            op.drop_column("connector_packs", column)
