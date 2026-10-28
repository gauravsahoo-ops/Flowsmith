"""Authorized file-reference resolution for node and service file access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.api.access import workspace_can_view
from app.engine.errors import NodeExecutionError
from app.models import FileRecord


@dataclass(frozen=True)
class FileReference:
    id: str
    object_key: str
    filename: str


def _authorized(db: Session, rec: Any, user_id: int) -> bool:
    if rec.owner_user_id == user_id:
        return True
    return bool(rec.workspace_id) and workspace_can_view(db, rec.workspace_id, user_id)


def resolve_file_reference(
    db: Session,
    file_id: str,
    *,
    user_id: int | None,
    workspace_id: str | None = None,
    node_id: str = "data_load",
) -> FileReference:
    """Resolve a FileRecord only when the executing user may read its bytes.

    Personal files require ownership. Workspace files require workspace view
    access. A missing user context fails closed so internal code cannot become
    an authorization bypass.
    """
    if user_id is None:
        raise NodeExecutionError(
            "File access requires an authenticated execution user.",
            code="FILE_ACCESS_DENIED",
            node_id=node_id,
            retryable=False,
        )
    rec = db.get(FileRecord, (file_id or "").strip())
    if rec is None:
        raise NodeExecutionError(
            "File not found.",
            code="FILE_NOT_FOUND",
            node_id=node_id,
            retryable=False,
        )
    if not _authorized(db, rec, user_id):
        raise NodeExecutionError(
            "File not found or access denied.",
            code="FILE_ACCESS_DENIED",
            node_id=node_id,
            retryable=False,
        )
    return FileReference(id=rec.id, object_key=rec.object_key, filename=rec.filename)


def resolve_file_reference_by_name(
    db: Session,
    filename: str,
    *,
    user_id: int | None,
    workspace_id: str | None = None,
    node_id: str = "data_load",
) -> FileReference:
    """Resolve a legacy filename-only upload reference without leaking files.

    Older saved workflows may carry only ``file_name``. Lookup is bounded to
    records the caller owns or can view in a workspace; it never scans the
    object store or another user's files.
    """
    clean = (filename or "").strip()
    if user_id is None or not clean:
        raise NodeExecutionError(
            "File access requires an authenticated execution user and a file name.",
            code="FILE_ACCESS_DENIED",
            node_id=node_id,
            retryable=False,
        )
    from sqlalchemy import select

    candidates = db.scalars(
        select(FileRecord)
        .where(FileRecord.filename == clean)
        .order_by(FileRecord.created_at.desc())
        .limit(100)
    ).all()
    for rec in candidates:
        if _authorized(db, rec, user_id):
            return FileReference(id=rec.id, object_key=rec.object_key, filename=rec.filename)
    raise NodeExecutionError(
        "File not found or access denied.",
        code="FILE_ACCESS_DENIED",
        node_id=node_id,
        retryable=False,
    )
