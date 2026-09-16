"""Index sweep-page audit lookup (credential auto-refresh).

Revision ID: c9d4e5f6a7b8
Revises: b7e2a4f6c8d1
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c9d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b7e2a4f6c8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # collect_sweep_audit() looks up pages via
    # WHERE action=:a AND target_id=:tid — cover with a composite index.
    op.create_index(
        'ix_audit_action_target',
        'audit_events',
        ['action', 'target_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_audit_action_target', table_name='audit_events')
