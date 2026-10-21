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

    # 3. staged_contacts: create it if no earlier migration did, otherwise widen row_number
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('staged_contacts'):
        op.create_table(
            'staged_contacts',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('execution_id', sa.String(length=64), nullable=False),
            sa.Column('row_number', sa.BigInteger(), nullable=False),
            sa.Column('first_name', sa.String(length=255), nullable=True),
            sa.Column('last_name', sa.String(length=255), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('phone', sa.String(length=100), nullable=True),
            sa.Column('department', sa.String(length=255), nullable=True),
            sa.Column('title', sa.String(length=255), nullable=True),
            sa.Column('mailing_street', sa.Text(), nullable=True),
            sa.Column('mailing_city', sa.String(length=255), nullable=True),
            sa.Column('mailing_state', sa.String(length=100), nullable=True),
            sa.Column('mailing_postal_code', sa.String(length=50), nullable=True),
            sa.Column('mailing_country', sa.String(length=100), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('raw_data', sa.JSON(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('salesforce_id', sa.String(length=50), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_staged_contacts_execution_id', 'staged_contacts', ['execution_id'])
        op.create_index('ix_staged_contacts_email', 'staged_contacts', ['email'])
        op.create_index('ix_staged_contacts_status', 'staged_contacts', ['status'])
        op.create_index('ix_staged_contacts_salesforce_id', 'staged_contacts', ['salesforce_id'])
    else:
        op.alter_column(
            'staged_contacts',
            'row_number',
            existing_type=sa.INTEGER(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )

    # 4. Telemetry and search drift alignment for executions, api_request_logs, and execution_retries
    drift_columns = [
        ('executions', 'search_text', 'TEXT'),
        ('executions', 'queue_wait_ms', 'FLOAT'),
        ('api_request_logs', 'node_id', 'VARCHAR(64)'),
        ('api_request_logs', 'connector_name', 'VARCHAR(64)'),
        ('api_request_logs', 'error_message', 'TEXT'),
        ('api_request_logs', 'is_truncated', 'BOOLEAN DEFAULT FALSE'),
        ('api_request_logs', 'created_at', 'TIMESTAMPTZ DEFAULT NOW()'),
        ('execution_retries', 'retry_trigger', "VARCHAR(32) DEFAULT 'manual'"),
        ('execution_retries', 'retry_policy', 'VARCHAR(128)'),
        ('execution_retries', 'failed_step_id', 'VARCHAR(64)'),
    ]
    for table_name, col_name, col_type in drift_columns:
        if sa.inspect(bind).has_table(table_name):
            bind.execute(sa.text(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col_name}" {col_type};'))

    # 5. Performance & multi-tenant index additions (idempotent with if_not_exists check)
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
        ('ix_api_req_step', 'api_request_logs', ['step_id']),
        ('ix_api_req_connector', 'api_request_logs', ['connector_id']),
        ('ix_api_req_status', 'api_request_logs', ['http_status_code']),
        ('ix_api_req_org', 'api_request_logs', ['organization_id', 'request_timestamp']),
        ('ix_api_req_connector_name', 'api_request_logs', ['connector_name']),
        ('ix_exec_retries_retry_policy', 'execution_retries', ['retry_policy']),
    ]

    for idx_name, table_name, cols in indexes_to_add:
        if sa.inspect(bind).has_table(table_name):
            bind.execute(
                sa.text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({', '.join(cols)});")
            )


def downgrade() -> None:
    bind = op.get_bind()
    indexes_to_drop = [
        'ix_exec_retries_retry_policy',
        'ix_api_req_connector_name',
        'ix_api_req_org',
        'ix_api_req_status',
        'ix_api_req_connector',
        'ix_api_req_step',
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

