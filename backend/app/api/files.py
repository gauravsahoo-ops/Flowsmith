"""File/object-storage API (Phase 19).

Metadata lives in PostgreSQL (FileRecord); bytes live in the configured
object store (local filesystem by default, S3-compatible when enabled).
Workspace ownership is enforced on every operation.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_db
from app.models import FileRecord, User, WorkspaceMember
from app.objectstore.factory import get_object_store

router = APIRouter(prefix="/api/files", tags=["files"])


def _can_access_workspace(db: Session, user_id: int, workspace_id: str | None, *, need_edit: bool = False) -> bool:
    if workspace_id is None:
        return True  # personal files are owner-scoped
    row = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if row is None:
        return False
    if not need_edit:
        return True
    return (row.role or "") in ("owner", "admin", "editor") or (row.permission or "") in ("edit", "admin")


def _workspace_ids_for_user(db: Session, user_id: int) -> set[str]:
    return {
        r.workspace_id
        for r in db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)).all()
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    workspace_id: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if workspace_id and not _can_access_workspace(db, user.id, workspace_id, need_edit=True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot upload to this workspace.")
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:  # 50 MB cap
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds 50 MB limit.")
    filename = file.filename or "upload"
    # Sanitize filename for object key (keep extension, strip path).
    safe_name = filename.split("/")[-1].split("\\")[-1][:180] or "file"
    file_id = f"file_{uuid.uuid4().hex[:16]}"
    object_key = f"{workspace_id or 'personal'}/{file_id}_{safe_name}"
    store = get_object_store()
    mime = file.content_type or "application/octet-stream"
    try:
        store.put(object_key, data, mime_type=mime)
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Object store write failed: {exc}")
    rec = FileRecord(
        id=file_id,
        workspace_id=workspace_id,
        owner_user_id=user.id,
        filename=safe_name,
        mime_type=mime,
        size=len(data),
        object_key=object_key,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"data": _to_dict(rec)}


@router.get("", status_code=status.HTTP_200_OK)
def list_files(
    workspace_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = select(FileRecord)
    if workspace_id is not None:
        if not _can_access_workspace(db, user.id, workspace_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this workspace.")
        q = q.where(FileRecord.workspace_id == workspace_id)
    else:
        # Without filter, show personal + workspaces the user belongs to.
        allowed = _workspace_ids_for_user(db, user.id)
        q = q.where(
            (FileRecord.owner_user_id == user.id) | (FileRecord.workspace_id.in_(allowed))  # type: ignore[arg-type]
            if allowed else (FileRecord.owner_user_id == user.id)
        )
    rows = db.scalars(q.order_by(FileRecord.created_at.desc()).limit(limit)).all()
    return {"data": [_to_dict(r) for r in rows]}


@router.get("/{file_id}", status_code=status.HTTP_200_OK)
def get_file_meta(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rec = db.get(FileRecord, file_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    if rec.owner_user_id != user.id:
        if rec.workspace_id is None or not _can_access_workspace(db, user.id, rec.workspace_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this file.")
    return {"data": _to_dict(rec)}


def _get_user_from_header(
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    raw_token = None
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    if header_val and header_val.startswith("Bearer "):
        raw_token = header_val.removeprefix("Bearer ").strip()

    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authentication token.")

    try:
        from app.security.jwt import decode_token
        payload = decode_token(raw_token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")

    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found.")
    return user


@router.get("/{file_id}/download")
def download_file(
    file_id: str,
    user: User = Depends(_get_user_from_header),
    db: Session = Depends(get_db),
):
    rec = db.get(FileRecord, file_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    if rec.owner_user_id != user.id:
        if rec.workspace_id is None or not _can_access_workspace(db, user.id, rec.workspace_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this file.")
    store = get_object_store()
    try:
        data = store.get(rec.object_key)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File bytes missing from object store.")
    # Stream bytes with attachment disposition.
    return StreamingResponse(
        iter([data]),
        media_type=rec.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{rec.filename}"'},
    )


@router.get("/{file_id}/view")
def view_file(
    file_id: str,
    user: User = Depends(_get_user_from_header),
    db: Session = Depends(get_db),
):
    """Stream file with inline disposition for in-browser image/PDF/text preview."""
    rec = db.get(FileRecord, file_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    if rec.owner_user_id != user.id:
        if rec.workspace_id is None or not _can_access_workspace(db, user.id, rec.workspace_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this file.")
    store = get_object_store()
    try:
        data = store.get(rec.object_key)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File bytes missing from object store.")
    return StreamingResponse(
        iter([data]),
        media_type=rec.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{rec.filename}"'},
    )


@router.delete("/{file_id}", status_code=status.HTTP_200_OK)
def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rec = db.get(FileRecord, file_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    # Delete requires ownership or workspace edit permission.
    is_owner = rec.owner_user_id == user.id
    can_edit = _can_access_workspace(db, user.id, rec.workspace_id, need_edit=True)
    if not (is_owner or can_edit):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No permission to delete this file.")
    store = get_object_store()
    try:
        store.delete(rec.object_key)
    except Exception:
        pass  # best-effort; metadata still deleted
    db.delete(rec)
    db.commit()
    return {"data": {"deleted": True, "id": file_id}}


def _to_dict(rec: FileRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "workspace_id": rec.workspace_id,
        "owner_user_id": rec.owner_user_id,
        "filename": rec.filename,
        "mime_type": rec.mime_type,
        "size": rec.size,
        "object_key": rec.object_key,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }
