"""Add error_events, notification_records, and notification_preferences tables.

Revision ID: e8d9c0a1b2f3
Revises: b1c2d3e4f5a6
Create Date: 2026-10-10 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e8d9c0a1b2f3'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()

    # error_events
    if not _has_table(bind, "error_events"):
        op.create_table(
            'error_events',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('severity', sa.String(length=16), nullable=False, server_default='ERROR'),
            sa.Column('category', sa.String(length=64), nullable=False),
            sa.Column('code', sa.String(length=64), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('resolution', sa.Text(), nullable=False, server_default=''),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('organization_id', sa.String(length=64), nullable=True),
            sa.Column('workspace_id', sa.String(length=64), nullable=True),
            sa.Column('workflow_id', sa.String(length=64), nullable=True),
            sa.Column('workflow_name', sa.String(length=255), nullable=True),
            sa.Column('execution_id', sa.String(length=64), nullable=True),
            sa.Column('node_id', sa.String(length=64), nullable=True),
            sa.Column('node_name', sa.String(length=255), nullable=True),
            sa.Column('connector_type', sa.String(length=64), nullable=True),
            sa.Column('credential_id', sa.String(length=64), nullable=True),
            sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('retry_exhausted', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('technical_details', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column('fingerprint', sa.String(length=64), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='DETECTED'),
            sa.Column('notification_attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('trace_id', sa.String(length=64), nullable=True),
            sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_error_events_created_at', 'error_events', ['created_at'])
        op.create_index('ix_error_events_user_created', 'error_events', ['user_id', 'created_at'])
        op.create_index('ix_error_events_fingerprint', 'error_events', ['fingerprint'])
        op.create_index('ix_error_events_category_severity', 'error_events', ['category', 'severity'])
        op.create_index('ix_error_events_workflow', 'error_events', ['workflow_id'])
        op.create_index('ix_error_events_execution', 'error_events', ['execution_id'])
        op.create_index('ix_error_events_status', 'error_events', ['status'])

    # notification_records
    if not _has_table(bind, "notification_records"):
        op.create_table(
            'notification_records',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('error_event_id', sa.String(length=64), sa.ForeignKey('error_events.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('recipient_email', sa.String(length=255), nullable=False),
            sa.Column('channel', sa.String(length=32), nullable=False, server_default='email'),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING'),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('idempotency_key', sa.String(length=128), unique=True, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_notification_records_user', 'notification_records', ['user_id'])
        op.create_index('ix_notification_records_event', 'notification_records', ['error_event_id'])
        op.create_index('ix_notification_records_status', 'notification_records', ['status'])

    # notification_preferences
    if not _has_table(bind, "notification_preferences"):
        op.create_table(
            'notification_preferences',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('email_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('notify_on_failure', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('notify_on_auth_expired', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('notify_on_rate_limit', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('notify_on_warning', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default='15'),
            sa.Column('custom_email', sa.String(length=255), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "notification_records"):
        op.drop_table('notification_records')
    if _has_table(bind, "notification_preferences"):
        op.drop_table('notification_preferences')
    if _has_table(bind, "error_events"):
        op.drop_table('error_events')
