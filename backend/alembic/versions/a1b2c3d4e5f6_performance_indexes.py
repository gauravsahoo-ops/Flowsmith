"""Add composite indexes for performance (P3)

Revision ID: a1b2c3d4e5f6
Revises: b51d7c8a90f2
Create Date: 2026-08-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = ('b51d7c8a90f2', '58767f324966')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P3-C5: jobs claim query — covers WHERE status=:queued AND (next_retry_at IS NULL OR next_retry_at <= :now) ORDER BY created_at, id
    op.create_index(
        'ix_jobs_claim',
        'jobs',
        ['status', 'next_retry_at', 'created_at', 'id'],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )

    # P3-C6: executions list + billing — covers ORDER BY started_at DESC and WHERE workflow_id = :id
    op.create_index(
        'ix_executions_workflow_started',
        'executions',
        ['workflow_id', sa.text('started_at DESC')],
    )

    # P3-C7: execution_events seq lookup — covers WHERE execution_id = :id ORDER BY seq DESC
    op.create_index(
        'ix_exec_events_exec_seq',
        'execution_events',
        ['execution_id', sa.text('seq DESC')],
    )

    # P3-H7: has_running_execution — covers WHERE workflow_id = :id AND status IN (...)
    op.create_index(
        'ix_executions_wf_status',
        'executions',
        ['workflow_id', 'status'],
    )


def downgrade() -> None:
    op.drop_index('ix_executions_wf_status')
    op.drop_index('ix_exec_events_exec_seq')
    op.drop_index('ix_executions_workflow_started')
    op.drop_index('ix_jobs_claim')
