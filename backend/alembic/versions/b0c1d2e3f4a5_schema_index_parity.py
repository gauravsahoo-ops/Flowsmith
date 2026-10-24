"""Align historical indexes with the SQLAlchemy metadata.

Revision ID: b0c1d2e3f4a5
Revises: a9c0d1e2f3b4
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9c0d1e2f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {item["name"] for item in inspector.get_indexes(table) if item.get("name")}


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _rename(bind, table: str, old: str, new: str) -> None:
    if old in _indexes(bind, table) and new not in _indexes(bind, table):
        bind.execute(sa.text(f'ALTER INDEX "{old}" RENAME TO "{new}"'))


def _create(bind, table: str, name: str, columns: str) -> None:
    if _has_table(bind, table) and name not in _indexes(bind, table):
        bind.execute(sa.text(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})'))


def upgrade() -> None:
    bind = op.get_bind()
    _rename(bind, "api_request_logs", "ix_api_req_connector_name", "ix_api_request_logs_connector_name")
    _rename(bind, "execution_retries", "ix_exec_retries_retry_policy", "ix_execution_retries_retry_policy")
    _rename(bind, "execution_steps", "ix_execution_steps_status", "ix_exec_steps_status")
    _rename(bind, "execution_steps", "ix_execution_steps_connector_id", "ix_exec_steps_connector")

    _create(bind, "execution_retries", "ix_exec_retries_retry", "retry_execution_id")
    _create(bind, "execution_retries", "ix_exec_retries_org", "organization_id, created_at")
    _create(bind, "execution_steps", "ix_exec_steps_org_started", "organization_id, started_at")
    _create(bind, "executions", "ix_executions_status_started", "status, started_at DESC")
    _create(bind, "executions", "ix_executions_user_started", "user_id, started_at DESC")
    _create(bind, "workflows", "ix_workflows_updated_at", "updated_at DESC")
    _create(bind, "workflows", "ix_workflows_user_updated", "user_id, deleted_at, updated_at DESC")

    for name, column in (
        ("ix_error_events_category", "category"),
        ("ix_error_events_code", "code"),
        ("ix_error_events_execution_id", "execution_id"),
        ("ix_error_events_user_id", "user_id"),
        ("ix_error_events_workflow_id", "workflow_id"),
    ):
        _create(bind, "error_events", name, column)


def downgrade() -> None:
    bind = op.get_bind()
    for table, name in (
        ("error_events", "ix_error_events_category"),
        ("error_events", "ix_error_events_code"),
        ("error_events", "ix_error_events_execution_id"),
        ("error_events", "ix_error_events_user_id"),
        ("error_events", "ix_error_events_workflow_id"),
        ("workflows", "ix_workflows_updated_at"),
        ("workflows", "ix_workflows_user_updated"),
        ("executions", "ix_executions_status_started"),
        ("executions", "ix_executions_user_started"),
        ("execution_steps", "ix_exec_steps_org_started"),
        ("execution_retries", "ix_exec_retries_retry"),
        ("execution_retries", "ix_exec_retries_org"),
    ):
        if name in _indexes(bind, table):
            op.drop_index(name, table_name=table)

    _rename(bind, "execution_steps", "ix_exec_steps_status", "ix_execution_steps_status")
    _rename(bind, "execution_steps", "ix_exec_steps_connector", "ix_execution_steps_connector_id")
    _rename(bind, "execution_retries", "ix_execution_retries_retry_policy", "ix_exec_retries_retry_policy")
    _rename(bind, "api_request_logs", "ix_api_request_logs_connector_name", "ix_api_req_connector_name")
