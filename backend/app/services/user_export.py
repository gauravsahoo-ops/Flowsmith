"""Per-user account data export.

The MCP backup tools used to dump the whole PostgreSQL database, which is an
operator recovery action and leaks every account's data. This module provides
the account-scoped equivalent: a JSON export of only the caller's workflows,
templates, credentials metadata, data tables, RAG metadata, recent executions,
and audit events. Secrets are never exported.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.importexport import sanitize_workflow_data
from app.models import (
    AuditEvent,
    Credential,
    DataTable,
    DataTableColumn,
    DataTableRow,
    Execution,
    RagCollection,
    User,
    WorkflowRecord,
    WorkflowTemplate,
)
from app.security.crypto import encrypt_text

_ROOT = Path(os.getenv("MAT_BACKUP_DIR", "backups")) / "users"
_NAME_CHARS = set("._-")


def _safe_name(name: str | None) -> str:
    if name is None:
        return f"account_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    if not (
        1 <= len(name) <= 64
        and name[0].isalnum()
        and all(c.isalnum() or c in _NAME_CHARS for c in name)
    ):
        raise ValueError(
            "Invalid export name: use 1-64 characters starting with a "
            "letter or digit (letters, digits, '.', '_', '-')."
        )
    return name


def user_export_dir(user_id: int, out_dir: str | Path | None = None) -> Path:
    return (Path(out_dir) if out_dir else _ROOT) / str(int(user_id))


def _prune_user_exports(directory: Path) -> None:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(
        days=settings.account_export_retention_days
    )
    # Remove legacy plaintext exports from earlier builds.
    for legacy in directory.glob("*.json.gz"):
        legacy.unlink(missing_ok=True)
    for path in directory.glob("*.json.enc"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    remaining = sorted(
        directory.glob("*.json.enc"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in remaining[settings.max_account_exports_per_user:]:
        path.unlink(missing_ok=True)


def create_user_export(
    db: Session,
    user_id: int,
    name: str | None = None,
    *,
    out_dir: str | Path | None = None,
) -> Path:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("User not found.")

    directory = user_export_dir(user_id, out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _prune_user_exports(directory)
    filepath = directory / f"{_safe_name(name)}.json.enc"

    workflows = []
    for rec in db.scalars(
        select(WorkflowRecord)
        .where(
            WorkflowRecord.user_id == user_id,
            WorkflowRecord.deleted_at.is_(None),
        )
        .order_by(WorkflowRecord.created_at)
    ).all():
        workflows.append({
            "id": rec.id,
            "name": rec.name,
            "description": rec.description,
            "version": rec.version,
            "active": rec.active,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
            "data": sanitize_workflow_data(
                rec.data or {}, strip_credentials=True, strip_secrets=True
            ),
        })

    templates = []
    for tmpl in db.scalars(
        select(WorkflowTemplate).where(WorkflowTemplate.created_by == user_id)
    ).all():
        raw = tmpl.workflow_data
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            data = {}
        templates.append({
            "id": tmpl.id,
            "name": tmpl.name,
            "description": tmpl.description,
            "category": tmpl.category,
            "created_at": tmpl.created_at,
            "workflow_data": sanitize_workflow_data(
                data, strip_credentials=True, strip_secrets=True
            ),
        })

    credentials = [
        {
            "id": rec.id,
            "name": rec.name,
            "type": rec.type,
            "created_at": rec.created_at,
        }
        for rec in db.scalars(
            select(Credential).where(Credential.user_id == user_id)
        ).all()
    ]

    tables = []
    for table in db.scalars(
        select(DataTable).where(DataTable.user_id == user_id)
    ).all():
        columns = db.scalars(
            select(DataTableColumn)
            .where(DataTableColumn.table_id == table.id)
            .order_by(DataTableColumn.position)
        ).all()
        rows = db.scalars(
            select(DataTableRow)
            .where(DataTableRow.table_id == table.id)
            .order_by(DataTableRow.created_at)
            .limit(10_000)
        ).all()
        tables.append({
            "id": table.id,
            "name": table.name,
            "description": table.description,
            "created_at": table.created_at,
            "columns": [
                {
                    "name": column.name,
                    "type": column.type,
                    "required": column.required,
                    "default_value": column.default_value,
                    "position": column.position,
                }
                for column in columns
            ],
            "rows": [
                {"id": row.id, "data": row.data, "created_at": row.created_at}
                for row in rows
            ],
        })

    collections = [
        {
            "id": rec.id,
            "name": rec.name,
            "description": rec.description,
            "embedding_model": rec.embedding_model,
            "dim": rec.dim,
            "created_at": rec.created_at,
        }
        for rec in db.scalars(
            select(RagCollection).where(RagCollection.owner_user_id == user_id)
        ).all()
    ]

    executions = [
        {
            "id": rec.id,
            "workflow_id": rec.workflow_id,
            "status": rec.status,
            "trigger": rec.trigger,
            "started_at": rec.started_at,
            "finished_at": rec.finished_at,
            "records_processed": rec.records_processed,
            "records_failed": rec.records_failed,
        }
        for rec in db.scalars(
            select(Execution)
            .where(Execution.user_id == user_id)
            .order_by(Execution.started_at.desc())
            .limit(1000)
        ).all()
    ]

    audit = [
        {
            "id": rec.id,
            "created_at": rec.created_at,
            "action": rec.action,
            "target_type": rec.target_type,
            "target_id": rec.target_id,
            "detail": rec.detail,
        }
        for rec in db.scalars(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(2000)
        ).all()
    ]

    payload: dict[str, Any] = {
        "export_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at,
        },
        "workflows": workflows,
        "templates": templates,
        "credentials": credentials,
        "data_tables": tables,
        "rag_collections": collections,
        "executions": executions,
        "audit_events": audit,
    }

    token = encrypt_text(
        json.dumps(payload, default=str, ensure_ascii=False)
    )
    fd = os.open(filepath, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(token)
    return filepath


def list_user_exports(
    user_id: int, out_dir: str | Path | None = None
) -> list[dict[str, Any]]:
    directory = user_export_dir(user_id, out_dir)
    if not directory.exists():
        return []
    _prune_user_exports(directory)
    exports = []
    for path in sorted(directory.glob("*.json.enc"), reverse=True):
        stat = path.stat()
        exports.append({
            "name": path.name.removesuffix(".json.enc"),
            "filename": path.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        })
    return exports
