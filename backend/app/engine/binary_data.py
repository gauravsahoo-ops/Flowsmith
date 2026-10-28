"""Binary Data Service for unified binary storage and metadata calculation.

Provides unified binary storage, metadata calculation, and buffer access.
Coordinates with Flowsmith's ObjectStore (local filesystem or S3/MinIO)
and FileRecord in database.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import uuid
from typing import Any

from app.db import get_session
from app.models.file import FileRecord
from app.objectstore.factory import get_object_store
from sqlalchemy import select


def format_file_size(num_bytes: int) -> str:
    """Format bytes into a human-readable size string (e.g. 1.2 KB, 3.4 MB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.1f} GB"


def prepare_binary_data(
    data: bytes,
    file_name: str | None = None,
    mime_type: str | None = None,
    workspace_id: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Store raw binary bytes in the ObjectStore and return an IBinaryData metadata dictionary.

    Returns dict shape:
    {
        "id": str,                 # Unique FileRecord ID in Flowsmith
        "fileName": str,           # e.g. "invoice.pdf"
        "fileExtension": str,      # e.g. "pdf"
        "mimeType": str,           # e.g. "application/pdf"
        "fileSize": str,           # e.g. "14.2 KB"
        "bytes": int,              # e.g. 14532
        "data": str,               # base64 string for small files (< 1MB) or empty
        "objectKey": str,          # storage key
    }
    """
    num_bytes = len(data)

    # 1. Deduce file name, extension, and mime type
    if not file_name:
        if mime_type:
            ext = mimetypes.guess_extension(mime_type) or ".bin"
            file_name = f"file{ext}"
        else:
            file_name = "file.bin"

    # Clean file name
    safe_name = os.path.basename(file_name)
    _, ext = os.path.splitext(safe_name)
    file_extension = ext.lstrip(".").lower() if ext else "bin"

    if not mime_type:
        guessed_type, _ = mimetypes.guess_type(safe_name)
        mime_type = guessed_type or "application/octet-stream"

    # 2. Store in ObjectStore
    file_id = f"file_{uuid.uuid4().hex[:16]}"
    object_key = f"{workspace_id or 'executions'}/{file_id}_{safe_name}"

    store = get_object_store()
    store.put(object_key, data, mime_type=mime_type)

    # 3. Create FileRecord in DB for tracking and lifecycle management
    try:
        with get_session() as db:
            rec = FileRecord(
                id=file_id,
                workspace_id=workspace_id,
                owner_user_id=user_id or 1,
                filename=safe_name,
                mime_type=mime_type,
                size=num_bytes,
                object_key=object_key,
            )
            db.add(rec)
            db.commit()
    except Exception:
        # Fallback in stateless / mock test environments without active DB session
        pass

    # 4. Generate base64 data for inline preview if under 1MB
    b64_data = ""
    if num_bytes <= 1024 * 1024:
        b64_data = base64.b64encode(data).decode("ascii")

    return {
        "id": file_id,
        "fileName": safe_name,
        "fileExtension": file_extension,
        "mimeType": mime_type,
        "fileSize": format_file_size(num_bytes),
        "bytes": num_bytes,
        "data": b64_data,
        "objectKey": object_key,
    }


def _authorized_object_key(
    object_key: str,
    *,
    user_id: int | None,
    workspace_id: str | None = None,
) -> str:
    """Return *object_key* only when the caller may read its FileRecord.

    Binary metadata is data flowing through a workflow, so ``objectKey`` can
    be supplied by an upstream item. Reading it without authorization would
    turn File I/O / email attachments into an object-store read primitive.
    Trusted internal/test callers (no user context) keep the historical direct
    read; execution paths always pass the caller's identity.
    """
    if user_id is None:
        return object_key
    with get_session() as db:
        rec = db.scalar(
            select(FileRecord).where(FileRecord.object_key == object_key).limit(1)
        )
        if rec is None:
            raise FileNotFoundError(f"Binary object '{object_key}' has no file record.")
        authorized = rec.owner_user_id == user_id
        if not authorized and rec.workspace_id:
            from app.api.access import workspace_can_view

            authorized = workspace_can_view(db, rec.workspace_id, user_id)
        if not authorized:
            raise PermissionError("Binary object access denied.")
    return object_key


def get_binary_data_buffer(
    binary_entry: dict[str, Any],
    *,
    user_id: int | None = None,
    workspace_id: str | None = None,
) -> bytes:
    """Retrieve raw bytes from an IBinaryData metadata dictionary.

    Attempts ObjectStore retrieval first via objectKey or id; falls back to base64 decoding.
    When a user context is supplied, object-store reads are authorized against
    the FileRecord owner/workspace ACL.
    """
    if not isinstance(binary_entry, dict):
        raise ValueError("binary_entry must be a dictionary")

    # 1. Direct object store retrieval if objectKey is known
    object_key = binary_entry.get("objectKey")
    file_id = binary_entry.get("id")

    if file_id:
        try:
            with get_session() as db:
                rec = db.get(FileRecord, file_id)
                if rec:
                    if user_id is not None:
                        authorized = rec.owner_user_id == user_id
                        if not authorized and rec.workspace_id:
                            from app.api.access import workspace_can_view

                            authorized = workspace_can_view(db, rec.workspace_id, user_id)
                        if not authorized:
                            raise PermissionError("Binary object access denied.")
                    object_key = rec.object_key
        except PermissionError:
            raise
        except Exception:
            pass

    if object_key:
        object_key = _authorized_object_key(
            str(object_key), user_id=user_id, workspace_id=workspace_id
        )
        store = get_object_store()
        try:
            return store.get(object_key)
        except Exception:
            pass

    # 2. Base64 fallback if data property is present
    b64_data = binary_entry.get("data")
    if b64_data and isinstance(b64_data, str):
        if b64_data.startswith("data:"):
            b64_data = b64_data.split(",", 1)[-1]
        return base64.b64decode(b64_data)

    raise FileNotFoundError(f"Binary data for file {binary_entry.get('fileName', 'unknown')} could not be retrieved.")
