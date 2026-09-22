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


def get_binary_data_buffer(binary_entry: dict[str, Any]) -> bytes:
    """Retrieve raw bytes from an IBinaryData metadata dictionary.

    Attempts ObjectStore retrieval first via objectKey or id; falls back to base64 decoding.
    """
    if not isinstance(binary_entry, dict):
        raise ValueError("binary_entry must be a dictionary")

    # 1. Direct object store retrieval if objectKey is known
    object_key = binary_entry.get("objectKey")
    file_id = binary_entry.get("id")

    if not object_key and file_id:
        try:
            with get_session() as db:
                rec = db.get(FileRecord, file_id)
                if rec:
                    object_key = rec.object_key
        except Exception:
            pass

    if object_key:
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
