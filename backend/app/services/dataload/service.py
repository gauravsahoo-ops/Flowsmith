"""High-Level DataLoad Ingestion, Parsing, Mapping, and Staging Service."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Generator


from app.db import get_session
from app.engine.errors import NodeExecutionError
from app.objectstore.factory import get_object_store
from app.services.dataload.downloader import SecureFileDownloader
from app.services.dataload.registry import DataLoadOptions, FormatRegistry

logger = logging.getLogger(__name__)


class DataLoadService:
    """Core enterprise file ingestion, validation, and staging engine."""

    @classmethod
    async def resolve_payload_bytes(
        cls,
        *,
        source_mode: str = "auto",
        download_url: str = "",
        file_id: str = "",
        file_name: str = "",
        file_path: str = "",
        csv_content: str = "",
        auth_type: str = "none",
        auth_token: str = "",
        timeout_seconds: float = 30.0,
        max_download_bytes: int = 52_428_800,
        allow_loopback_in_dev: bool = False,
        node_id: str = "data_load",
        user_id: int | None = None,
        workspace_id: str | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        """Resolve raw file bytes and filename hint from URL, ObjectStore file_id, file path, or inline content.

        Returns:
            (raw_bytes, filename_hint, metadata)
        """
        meta: dict[str, Any] = {"source_type": "unknown"}

        # 1. Download Link (URL) mode
        if (source_mode == "url" and download_url) or (source_mode == "auto" and download_url.strip().startswith(("http://", "https://"))):
            raw_bytes, hint, dl_meta = await SecureFileDownloader.download_file(
                url=download_url,
                auth_type=auth_type,
                auth_token=auth_token,
                timeout_seconds=timeout_seconds,
                max_download_bytes=max_download_bytes,
                allow_loopback_in_dev=allow_loopback_in_dev,
                node_id=node_id,
            )
            meta.update(dl_meta)
            meta["source_type"] = "download_url"
            return raw_bytes, hint, meta

        # 2. Base64 Data URL (browser upload). Checked before file_id/
        # file_name because a request can carry both a stale upload field and
        # inline content; the caller's explicit inline payload must win.
        if csv_content and csv_content.strip().startswith("data:") and ";base64," in csv_content:
            header, b64_data = csv_content.split(";base64,", 1)
            raw_bytes = base64.b64decode(b64_data)
            hint = "archive.zip" if "zip" in header.lower() else ("data.gz" if "gzip" in header.lower() else "data.csv")
            meta["source_type"] = "upload_data_url"
            return raw_bytes, hint, meta

        # 3. Upload / ObjectStore file_id mode
        if (file_id and file_id.strip()) or (file_name and file_name.strip()):
            clean_id = (file_id or "").strip()
            clean_name = file_name.strip() if file_name and file_name.strip() else ""
            from app.services.file_access import (
                resolve_file_reference,
                resolve_file_reference_by_name,
            )

            db = get_session()
            try:
                if clean_id:
                    ref = resolve_file_reference(
                        db,
                        clean_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        node_id=node_id,
                    )
                else:
                    # Legacy saved workflows may carry only file_name. Resolve
                    # it against the caller's authorized FileRecords instead
                    # of scanning the object store or another user's files.
                    ref = resolve_file_reference_by_name(
                        db,
                        clean_name,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        node_id=node_id,
                    )
            finally:
                db.close()
            store = get_object_store()
            try:
                raw_bytes = store.get(ref.object_key)
            except Exception as exc:
                raise NodeExecutionError(
                    "Uploaded file bytes could not be read from object storage.",
                    code="FILE_NOT_FOUND",
                    node_id=node_id,
                    retryable=False,
                ) from exc
            if max_download_bytes and len(raw_bytes) > max_download_bytes:
                raise NodeExecutionError(
                    "Uploaded file exceeds the maximum allowed size.",
                    code="FILE_TOO_LARGE",
                    node_id=node_id,
                    retryable=False,
                )
            meta["source_type"] = "object_store"
            meta["file_id"] = ref.id
            meta["filename"] = ref.filename
            return raw_bytes, ref.filename or clean_name or ref.id, meta

        # 4. Local or Container File Path
        clean_path = file_path.strip() if file_path else ""
        if clean_path:
            from app.nodes.file_io import FileIONode

            FileIONode._validate_path(clean_path)
            candidate = Path(clean_path)
            if not candidate.is_file():
                raise NodeExecutionError(
                    f"File path '{clean_path}' not found on filesystem.",
                    code="FILE_NOT_FOUND",
                    node_id=node_id,
                    retryable=False,
                )
            raw_bytes = candidate.read_bytes()
            meta["source_type"] = "file_path"
            meta["path"] = str(candidate)
            return raw_bytes, candidate.name, meta

        # 5. Inline raw CSV / TSV text
        if csv_content and csv_content.strip():
            raw_bytes = csv_content.encode("utf-8")
            meta["source_type"] = "inline_content"
            return raw_bytes, "inline_data.csv", meta

        raise NodeExecutionError(
            "No data source provided (file upload, download_url, or file_path required).",
            code="NO_SOURCE_PROVIDED",
            node_id=node_id,
            retryable=False,
        )

    @classmethod
    def stream_parsed_records(
        cls,
        raw_bytes: bytes,
        filename: str,
        options: DataLoadOptions | None = None,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Stream parsed records using the matched FormatHandler from the registry."""
        opts = options or DataLoadOptions()
        handler = FormatRegistry.get_handler(filename, raw_bytes[:1024])
        yield from handler.parse_stream(raw_bytes, filename, opts, node_id=node_id)
