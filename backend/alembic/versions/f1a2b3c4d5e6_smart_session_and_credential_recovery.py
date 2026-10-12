"""Add smart sessions, connection auth policies, recovery jobs, and audit events.

Revision ID: f1a2b3c4d5e6
Revises: e8d9c0a1b2f3
Create Date: 2026-10-12 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e8d9c0a1b2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. auth_sessions
    if not _has_table(bind, "auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_jti", sa.String(length=64), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=False, server_default="unknown"),
            sa.Column("user_agent", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("device_name", sa.String(length=128), nullable=False, server_default="Browser"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("remember_device", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("idle_timeout_minutes", sa.Integer(), nullable=False, server_default="1440"),
            sa.Column("max_lifetime_minutes", sa.Integer(), nullable=False, server_default="10080"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id", "is_active"])
        op.create_index("ix_auth_sessions_token_jti", "auth_sessions", ["token_jti"], unique=True)
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    # 2. connection_auth_policies
    if not _has_table(bind, "connection_auth_policies"):
        op.create_table(
            "connection_auth_policies",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("credential_id", sa.String(length=64), sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=True),
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="automatic"),
            sa.Column("state", sa.String(length=32), nullable=False, server_default="CONNECTED"),
            sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("auth_type", sa.String(length=64), nullable=False, server_default="oauth2"),
            sa.Column("notify_in_app", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("notify_on_recovery_failure", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("notify_on_upcoming_expiry", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_recovery_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_recovery_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("last_error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_conn_policy_user_state", "connection_auth_policies", ["user_id", "state"])
        op.create_index("ix_conn_policy_next_recovery", "connection_auth_policies", ["next_recovery_at"])
        op.create_index("ix_conn_policy_cred_id", "connection_auth_policies", ["credential_id"], unique=True)

    # 3. credential_recovery_jobs
    if not _has_table(bind, "credential_recovery_jobs"):
        op.create_table(
            "credential_recovery_jobs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("credential_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("lock_token", sa.String(length=128), nullable=True),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_rec_jobs_status_scheduled", "credential_recovery_jobs", ["status", "scheduled_at"])
        op.create_index("ix_rec_jobs_cred_status", "credential_recovery_jobs", ["credential_id", "status"])

    # 4. credential_audit_events
    if not _has_table(bind, "credential_audit_events"):
        op.create_table(
            "credential_audit_events",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("credential_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.String(length=64), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("previous_state", sa.String(length=32), nullable=True),
            sa.Column("new_state", sa.String(length=32), nullable=True),
            sa.Column("actor", sa.String(length=128), nullable=False, server_default="system"),
            sa.Column("details", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_cred_audit_cred_created", "credential_audit_events", ["credential_id", "created_at"])
        op.create_index("ix_cred_audit_user_created", "credential_audit_events", ["user_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "credential_audit_events"):
        op.drop_table("credential_audit_events")
    if _has_table(bind, "credential_recovery_jobs"):
        op.drop_table("credential_recovery_jobs")
    if _has_table(bind, "connection_auth_policies"):
        op.drop_table("connection_auth_policies")
    if _has_table(bind, "auth_sessions"):
        op.drop_table("auth_sessions")
