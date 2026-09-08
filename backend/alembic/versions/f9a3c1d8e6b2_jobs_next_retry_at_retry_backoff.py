"""jobs next_retry_at: retry backoff support (audit phases 7-9)

Adds the delayed-retry anchor for the DB queue backend: recovered jobs
are requeued with ``next_retry_at = now + exponential_backoff(attempts)``
and only become claimable once the timestamp passes. Redis backend
mirrors the semantics with a sorted-set schedule.

Also the terminal marker column needs no schema change (status/error
already exist) — poison jobs end status='failed' with a structured
error payload.

Revision ID: f9a3c1d8e6b2
Revises: e4f2b8c9a7d5
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a3c1d8e6b2'
down_revision: Union[str, Sequence[str], None] = 'e4f2b8c9a7d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("jobs")}
    if "next_retry_at" not in cols:
        op.add_column('jobs', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))
        op.create_index(op.f('ix_jobs_next_retry_at'), 'jobs', ['next_retry_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("jobs")}
    if "next_retry_at" in cols:
        op.drop_index(op.f('ix_jobs_next_retry_at'), table_name='jobs')
        op.drop_column('jobs', 'next_retry_at')
