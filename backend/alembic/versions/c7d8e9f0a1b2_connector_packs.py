"""Add connector pack marketplace records.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if _has_table(op.get_bind(), "connector_packs"):
        return
    op.create_table(
        "connector_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("connector_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False, server_default="1.0.0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="api"),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("template_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_sources", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "installed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_connector_packs_connector_key", "connector_packs", ["connector_key"], unique=True)
    op.create_index("ix_connector_packs_installed_by", "connector_packs", ["installed_by"])


def downgrade() -> None:
    if _has_table(op.get_bind(), "connector_packs"):
        op.drop_table("connector_packs")
