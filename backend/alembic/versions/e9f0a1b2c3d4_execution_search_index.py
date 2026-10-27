"""Add a trigram index for execution log search.

Revision ID: e9f0a1b2c3d4
Revises: d2e3f4a5b6c7
Create Date: 2026-10-26 00:00:00.000000

Execution search uses ``ILIKE '%term%'`` against the consolidated
``executions.search_text`` column. A standard btree cannot serve a leading
wildcard, so this migration installs pg_trgm and builds a GIN trigram index.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_executions_search_text_trgm "
        'ON "executions" USING gin (search_text gin_trgm_ops)'
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_executions_search_text_trgm")
