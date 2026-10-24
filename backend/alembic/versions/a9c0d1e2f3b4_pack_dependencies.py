"""Add connector-pack dependency declarations.

Revision ID: a9c0d1e2f3b4
Revises: e0f1a2b3c4d5
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c0d1e2f3b4"
down_revision: Union[str, Sequence[str], None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column(op.get_bind(), "connector_packs", "dependencies"):
        op.add_column(
            "connector_packs",
            sa.Column(
                "dependencies",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )


def downgrade() -> None:
    if _has_column(op.get_bind(), "connector_packs", "dependencies"):
        op.drop_column("connector_packs", "dependencies")
