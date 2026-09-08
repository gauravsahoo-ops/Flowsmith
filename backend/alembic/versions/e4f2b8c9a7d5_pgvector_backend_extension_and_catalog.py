"""pgvector backend: enable extension + collection catalog

Production vector store moves into PostgreSQL (audit phases 3-6):

- enables the ``vector`` extension shipped by the pgvector/pgvector image,
- creates the ``vector_collections`` catalog used by
  ``app/vectorstores/pgvector.py`` to map logical collections to their
  per-collection chunk tables (those tables are runtime-managed by the
  store module because their embedding columns are typed per collection
  dimension; everything else about them lives in this database).

Revision ID: e4f2b8c9a7d5
Revises: d7f1a2b3c4e5
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f2b8c9a7d5'
down_revision: Union[str, Sequence[str], None] = 'd7f1a2b3c4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Vector storage requires PostgreSQL; dev/test SQLite-less setups
        # never reach this code path (the app refuses sqlite in production).
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    if not _has_table(bind, "vector_collections"):
        op.create_table(
            'vector_collections',
            sa.Column('name', sa.Text(), primary_key=True),
            sa.Column('suffix', sa.Text(), nullable=False, unique=True),
            sa.Column('dim', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "vector_collections"):
        op.drop_table('vector_collections')
    # The extension itself is left installed: other objects may depend on it.
