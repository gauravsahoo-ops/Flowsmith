"""Add logs and monitoring telemetry: execution extensions, execution_steps, api_request_logs, and execution_retries.

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-10-14 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_column(bind, table: str, column: str) -> bool:
    if not _has_table(bind, table):
        return False
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Extend executions table with monitoring and record metrics
    if _has_table(bind, "executions"):
        exec_cols = [
            ("organization_id", sa.String(length=64), True),
            ("workspace_id", sa.String(length=64), True),
            ("correlation_id", sa.String(length=64), True),
            ("parent_execution_id", sa.String(length=64), True),
            ("retry_count", sa.Integer(), False, 0),
            ("duration_ms", sa.Float(), True),
            ("source_connector", sa.String(length=64), True),
            ("destination_connector", sa.String(length=64), True),
            ("source_object", sa.String(length=64), True),
            ("destination_object", sa.String(length=64), True),
            ("http_method", sa.String(length=16), True),
            ("api_endpoint", sa.String(length=512), True),
            ("http_status_code", sa.Integer(), True),
            ("records_read", sa.Integer(), False, 0),
            ("records_created", sa.Integer(), False, 0),
            ("records_updated", sa.Integer(), False, 0),
            ("records_skipped", sa.Integer(), False, 0),
            ("records_failed", sa.Integer(), False, 0),
            ("records_processed", sa.Integer(), False, 0),
            ("error_type", sa.String(length=64), True),
            ("error_code", sa.String(length=64), True),
            ("error_summary", sa.Text(), True),
        ]
        for item in exec_cols:
            col_name = item[0]
            col_type = item[1]
            nullable = item[2]
            default = item[3] if len(item) > 3 else None
            if not _has_column(bind, "executions", col_name):
                op.add_column(
                    "executions",
                    sa.Column(col_name, col_type, nullable=nullable, server_default=str(default) if default is not None else None),
                )

        # Performance Indexes for executions
        try:
            op.create_index("ix_executions_org_started", "executions", ["organization_id", "started_at"])
        except Exception:
            pass
        try:
            op.create_index("ix_executions_parent", "executions", ["parent_execution_id"])
        except Exception:
            pass
        try:
            op.create_index("ix_executions_correlation", "executions", ["correlation_id"])
        except Exception:
            pass

    # 2. Create execution_steps table
    if not _has_table(bind, "execution_steps"):
        op.create_table(
            "execution_steps",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("execution_id", sa.String(length=64), sa.ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("organization_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("node_id", sa.String(length=64), nullable=False),
            sa.Column("node_type", sa.String(length=64), nullable=False),
            sa.Column("step_name", sa.String(length=255), nullable=True),
            sa.Column("operation", sa.String(length=64), nullable=True),
            sa.Column("connector_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("parent_step_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="success", index=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("input_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_type", sa.String(length=64), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("inputs", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("outputs", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("error_details", sa.JSON(), nullable=True),
        )
        op.create_index("ix_exec_steps_exec_seq", "execution_steps", ["execution_id", "sequence_number"])
        op.create_index("ix_exec_steps_exec_node", "execution_steps", ["execution_id", "node_id"])

    # 3. Create api_request_logs table
    if not _has_table(bind, "api_request_logs"):
        op.create_table(
            "api_request_logs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("execution_id", sa.String(length=64), sa.ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("step_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("organization_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("connector_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("operation", sa.String(length=64), nullable=True),
            sa.Column("http_method", sa.String(length=16), nullable=False),
            sa.Column("endpoint_url", sa.String(length=1024), nullable=False),
            sa.Column("request_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("query_params", sa.JSON(), nullable=True),
            sa.Column("request_headers", sa.JSON(), nullable=True),
            sa.Column("request_payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("http_status_code", sa.Integer(), nullable=True, index=True),
            sa.Column("response_headers", sa.JSON(), nullable=True),
            sa.Column("response_payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("error_details", sa.Text(), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("payload_truncated", sa.Boolean(), nullable=False, server_default="false"),
        )
        op.create_index("ix_api_req_exec", "api_request_logs", ["execution_id", "request_timestamp"])

    # 4. Create execution_retries table
    if not _has_table(bind, "execution_retries"):
        op.create_table(
            "execution_retries",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("original_execution_id", sa.String(length=64), sa.ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("retry_execution_id", sa.String(length=64), sa.ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("organization_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("retry_type", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("initiated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("target_node_id", sa.String(length=64), nullable=True),
            sa.Column("retry_reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_exec_retries_orig", "execution_retries", ["original_execution_id", "attempt_number"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "execution_retries"):
        op.drop_table("execution_retries")
    if _has_table(bind, "api_request_logs"):
        op.drop_table("api_request_logs")
    if _has_table(bind, "execution_steps"):
        op.drop_table("execution_steps")
