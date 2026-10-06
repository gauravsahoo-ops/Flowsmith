"""Audit fixes: missing indexes, subscriptions FK, JSON -> JSONB.

Revision ID: d4a1c7e9f3b5
Revises: a7b8c9d0e1f2
Create Date: 2026-10-06 00:00:00.000000

Addresses audit findings:
- Missing single-column indexes on hot filters (executions.user_id,
  audit_events.user_id, credentials.type, execution_events.timestamp,
  webhook_deliveries.received_at). All created with IF NOT EXISTS so
  databases created via Base.metadata.create_all are not double-indexed.
- subscriptions.organization_id had no FK to organizations.id.
- Large JSON snapshot columns converted to JSONB for containment queries
  and smaller on-disk representation (PostgreSQL only).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a1c7e9f3b5'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (index name, table, column)
_INDEXES = (
    ('ix_executions_user_id', 'executions', 'user_id'),
    ('ix_audit_events_user_id', 'audit_events', 'user_id'),
    ('ix_credentials_type', 'credentials', 'type'),
    ('ix_execution_events_timestamp', 'execution_events', 'timestamp'),
    ('ix_webhook_deliveries_received_at', 'webhook_deliveries', 'received_at'),
)

# (table, column) pairs converted JSON -> JSONB on PostgreSQL.
_JSONB_COLUMNS = (
    ('executions', 'workflow_data'),
    ('workflows', 'data'),
    ('workflow_versions', 'data'),
    ('webhooks', 'workflow_data'),
    ('schedule_triggers', 'workflow_data'),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column], unique=False, if_not_exists=True)

    # Subscriptions must reference a live organization. Orphan rows (org
    # hard-deleted before the FK existed) are invalid and removed first so
    # constraint creation cannot fail.
    op.execute(
        "DELETE FROM subscriptions "
        "WHERE organization_id NOT IN (SELECT id FROM organizations)"
    )
    op.create_foreign_key(
        'fk_subscriptions_organization_id',
        'subscriptions',
        'organizations',
        ['organization_id'],
        ['id'],
    )

    if op.get_bind().dialect.name == 'postgresql':
        for table, column in _JSONB_COLUMNS:
            op.execute(
                f'ALTER TABLE {table} '
                f'ALTER COLUMN {column} TYPE JSONB USING {column}::jsonb'
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        for table, column in reversed(_JSONB_COLUMNS):
            op.execute(
                f'ALTER TABLE {table} '
                f'ALTER COLUMN {column} TYPE JSON USING {column}::json'
            )

    op.drop_constraint('fk_subscriptions_organization_id', 'subscriptions', type_='foreignkey')
    for name, _table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=_table, if_exists=True)
