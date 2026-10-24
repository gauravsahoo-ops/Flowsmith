"""Add uninstall tombstones for multi-process pack propagation.

Revision ID: e0f1a2b3c4d5
Revises: d8e9f0a1b2c3
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if _has_table(op.get_bind(), "connector_pack_tombstones"):
        return
    op.create_table(
        "connector_pack_tombstones",
        sa.Column("connector_key", sa.String(length=128), primary_key=True),
        sa.Column(
            "uninstalled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    if _has_table(op.get_bind(), "connector_pack_tombstones"):
        op.drop_table("connector_pack_tombstones")
