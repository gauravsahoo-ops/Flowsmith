"""security_and_schema_drift_alignment

Revision ID: b1d598391ba2
Revises: a9b8c7d6e5f4
Create Date: 2026-10-18 05:56:27.662313

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1d598391ba2'
down_revision: Union[str, Sequence[str], None] = 'a9b8c7d6e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Expand executions.status from VARCHAR(16) to VARCHAR(32) to prevent truncation of long status strings
    op.alter_column(
        'executions',
        'status',
        existing_type=sa.VARCHAR(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )

    # 2. Expand oauth_states.client_secret from VARCHAR(255) to VARCHAR(512) for long secrets / KMS tokens
    op.alter_column(
        'oauth_states',
        'client_secret',
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=512),
        existing_nullable=True,
    )

    # 3. Expand staged_contacts.row_number from INTEGER to BIGINT to match ORM model
    op.alter_column(
        'staged_contacts',
        'row_number',
        existing_type=sa.INTEGER(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    # 4. Performance & multi-tenant index additions (idempotent with if_not_exists check)
    indexes_to_add = [
        ('ix_auth_sessions_user_id', 'auth_sessions', ['user_id']),
        ('ix_executions_workspace_id', 'executions', ['workspace_id']),
        ('ix_executions_organization_id', 'executions', ['organization_id']),
        ('ix_executions_correlation_id', 'executions', ['correlation_id']),
        ('ix_executions_parent_execution_id', 'executions', ['parent_execution_id']),
        ('ix_executions_error_code', 'executions', ['error_code']),
        ('ix_executions_error_type', 'executions', ['error_type']),
        ('ix_executions_destination_connector', 'executions', ['destination_connector']),
        ('ix_executions_source_connector', 'executions', ['source_connector']),
        ('ix_executions_http_status_code', 'executions', ['http_status_code']),
        ('ix_staged_contacts_exec_row', 'staged_contacts', ['execution_id', 'row_number']),
        ('ix_staged_contacts_exec_status', 'staged_contacts', ['execution_id', 'status']),
    ]

    bind = op.get_bind()
    for idx_name, table_name, cols in indexes_to_add:
        bind.execute(
            sa.text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({', '.join(cols)});")
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes_to_drop = [
        'ix_staged_contacts_exec_status',
        'ix_staged_contacts_exec_row',
        'ix_executions_http_status_code',
        'ix_executions_source_connector',
        'ix_executions_destination_connector',
        'ix_executions_error_type',
        'ix_executions_error_code',
        'ix_executions_parent_execution_id',
        'ix_executions_correlation_id',
        'ix_executions_organization_id',
        'ix_executions_workspace_id',
        'ix_auth_sessions_user_id',
    ]
    for idx_name in indexes_to_drop:
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {idx_name};"))

    op.alter_column(
        'staged_contacts',
        'row_number',
        existing_type=sa.BigInteger(),
        type_=sa.INTEGER(),
        existing_nullable=False,
    )
    op.alter_column(
        'oauth_states',
        'client_secret',
        existing_type=sa.String(length=512),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        'executions',
        'status',
        existing_type=sa.String(length=32),
        type_=sa.VARCHAR(length=16),
        existing_nullable=False,
    )
