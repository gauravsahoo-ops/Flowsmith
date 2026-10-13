"""High-Level DataLoad Ingestion, Parsing, Mapping, and Staging Service."""

from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path
import re
import uuid
from typing import Any, Generator

from sqlalchemy.orm import Session

from app.db import get_session
from app.engine.errors import NodeExecutionError
from app.models.staged_record import StagedContactRecord
from app.objectstore.factory import get_object_store
from app.services.dataload.downloader import SecureFileDownloader
from app.services.dataload.registry import DataLoadOptions, FormatRegistry
from app.services.csv_service import CsvService, ValidationResult, PersistenceResult, SF_CONTACT_CONSTRAINTS

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
        file_path: str = "",
        csv_content: str = "",
        auth_type: str = "none",
        auth_token: str = "",
        timeout_seconds: float = 30.0,
        max_download_bytes: int = 52_428_800,
        allow_loopback_in_dev: bool = False,
        node_id: str = "data_load",
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

        # 2. Upload / ObjectStore file_id mode
        if file_id and file_id.strip():
            clean_id = file_id.strip()
            store = get_object_store()
            try:
                # Try getting directly by object_key / file_id
                raw_bytes = store.get(clean_id)
                meta["source_type"] = "object_store"
                meta["file_id"] = clean_id
                return raw_bytes, clean_id, meta
            except Exception:
                # Check FileRecord database table if exists
                try:
                    from app.models.file import FileRecord
                    with get_session() as db:
                        rec = db.get(FileRecord, clean_id)
                        if rec is not None:
                            raw_bytes = store.get(rec.object_key)
                            meta["source_type"] = "object_store"
                            meta["file_id"] = clean_id
                            meta["filename"] = rec.filename
                            return raw_bytes, rec.filename, meta
                except Exception:
                    pass
                raise NodeExecutionError(
                    f"Uploaded file '{clean_id}' could not be located in object store or may have expired.",
                    code="FILE_NOT_FOUND",
                    node_id=node_id,
                    retryable=False,
                )

        # 3. Base64 Data URL (browser upload)
        if csv_content and csv_content.strip().startswith("data:") and ";base64," in csv_content:
            header, b64_data = csv_content.split(";base64,", 1)
            raw_bytes = base64.b64decode(b64_data)
            hint = "archive.zip" if "zip" in header.lower() else ("data.gz" if "gzip" in header.lower() else "data.csv")
            meta["source_type"] = "upload_data_url"
            return raw_bytes, hint, meta

        # 4. Local or Container File Path
        clean_path = file_path.strip() if file_path else ""
        if clean_path:
            # Check candidate paths on disk
            candidates = [
                Path(clean_path),
                Path.cwd() / clean_path,
                Path.cwd().parent / clean_path,
                Path(__file__).resolve().parents[3] / clean_path,
                Path(r"c:\Flowsmith") / clean_path,
                Path("/app") / clean_path,
                Path("/app/backend") / clean_path,
            ]
            for cand in candidates:
                try:
                    if cand.is_file():
                        raw_bytes = cand.read_bytes()
                        meta["source_type"] = "file_path"
                        meta["path"] = str(cand)
                        return raw_bytes, cand.name, meta
                except Exception:
                    continue
            raise NodeExecutionError(
                f"File path '{clean_path}' not found on filesystem.",
                code="FILE_NOT_FOUND",
                node_id=node_id,
                retryable=False,
            )

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
