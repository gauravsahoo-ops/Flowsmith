"""Flowsmith DataLoad Node.

Universal File Ingestion and Transformation Engine.
Supports:
- Option A: Upload File (Direct drag-and-drop, ObjectStore file_id, Base64 Data URL)
- Option B: Download from URL (SSRF-protected, safe redirects, auth, size caps)
- Delimited text (CSV, TSV, custom delimiters, quotes, null values)
- ZIP archives (single file or combined files, nested directories, nested archives)
- GZIP archives (.gz)
- Field validation, visual mapping, deduplication, and database persistence.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.engine.errors import NodeExecutionError
from app.engine.expressions import interpolate
from app.nodes.registry import register
from app.services.dataload.registry import DataLoadOptions
from app.services.dataload.service import DataLoadService
from app.services.csv_service import CsvService
from app.db import get_session

logger = logging.getLogger(__name__)


class DataLoadParams(BaseModel):
    # Source configuration
    source_mode: Literal["upload", "url", "file_path", "inline", "auto"] = Field(
        default="auto",
        description="Source mode: 'upload' (imported/uploaded file), 'url' (download link), 'file_path', or 'inline'.",
    )
    download_url: str = Field(
        default="",
        description="Remote HTTP/HTTPS download link (supports {{ expressions }}).",
    )
    credential_id: str = Field(
        default="",
        description="Flowsmith credential ID for authenticated URL downloads.",
    )
    auth_type: Literal["none", "bearer", "basic", "custom_header"] = Field(
        default="none",
        description="Authentication type for download link: none, bearer, basic, or custom_header.",
    )
    auth_token: str = Field(
        default="",
        description="Authentication token or Basic user:pass string (supports {{ expressions }}).",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Maximum download timeout in seconds.",
    )
    max_download_bytes: int = Field(
        default=52_428_800,
        ge=1024,
        le=209_715_200,
        description="Maximum allowed download size in bytes (default 50 MB, max 200 MB).",
    )

    # Local / ObjectStore sources
    file_id: str = Field(
        default="",
        description="Flowsmith ObjectStore file ID.",
    )
    file_name: str = Field(
        default="",
        description="Original uploaded file name.",
    )
    file_path: str = Field(
        default="",
        description="Path to file on local filesystem or container.",
    )
    csv_content: str = Field(
        default="",
        description="Inline raw text or base64 data URL (e.g. data:application/zip;base64,...).",
    )

    # Format & Delimiter Settings
    format_override: str = Field(
        default="auto",
        description="Format override: auto, csv, tsv, zip, gz.",
    )
    delimiter: str = Field(
        default="",
        description="Field delimiter (comma ',', tab '\\t', semicolon ';', pipe '|'). Empty for auto-detect.",
    )
    encoding: str = Field(
        default="utf-8",
        description="Text encoding (default utf-8, handles UTF-8 BOM automatically).",
    )
    has_header: bool = Field(
        default=True,
        description="Whether the first row contains column headers.",
    )
    quotechar: str = Field(
        default='"',
        description="Quote character enclosing fields.",
    )
    escapechar: str = Field(
        default="",
        description="Escape character.",
    )
    null_values: list[str] = Field(
        default_factory=lambda: ["", "null", "NULL", "None", "NA", "N/A"],
        description="Strings to treat as null values.",
    )

    # Archive Settings
    archive_inner_file: str = Field(
        default="",
        description="Target filename or path inside archive to extract.",
    )
    archive_pattern: str = Field(
        default="*",
        description="Glob pattern for selecting files inside archive (e.g. *.csv or **/*.tsv).",
    )
    archive_process_mode: Literal["single", "combine"] = Field(
        default="single",
        description="Archive process mode: 'single' (first matching file) or 'combine' (combine all matching files).",
    )
    archive_header_mode: Literal["union", "strict", "first"] = Field(
        default="union",
        description="Header handling when combining archive files: union, strict, or first.",
    )
    max_nesting_depth: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum allowed nested archive depth.",
    )

    # Processing & Downstream options
    batch_size: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Processing and database batch size (range: 1-10000).",
    )
    row_limit: int = Field(
        default=0,
        ge=0,
        description="Maximum rows to process (0 for unlimited).",
    )
    target_object: str = Field(
        default="Contact",
        description="Target schema object (Contact, Lead, etc.).",
    )
    field_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "FirstName": "FirstName",
            "LastName": "LastName",
            "Email": "Email",
            "Phone": "Phone",
            "Department": "Department",
            "Title": "Title",
            "MailingStreet": "MailingStreet",
            "MailingCity": "MailingCity",
            "MailingState": "MailingState",
            "MailingPostalCode": "MailingPostalCode",
            "MailingCountry": "MailingCountry",
            "Description": "Description",
        },
        description="Source column to target field mapping.",
    )
    duplicate_policy: Literal["skip", "update", "error"] = Field(
        default="skip",
        description="Duplicate handling policy: skip, update, or error.",
    )
    dedup_key: str = Field(
        default="Email",
        description="Primary key used for duplicate detection.",
    )
    persist_to_db: bool = Field(
        default=True,
        description="Persist parsed and validated records into staged_contacts table.",
    )
    execution_id: str = Field(
        default="",
        description="Execution correlation ID (auto-generated if empty).",
    )


@register
class DataLoadNode(BaseNode[DataLoadParams]):
    node_type = "flowsmith.data_load"
    display_name = "Flowsmith DataLoad"
    version = 1
    description = "Import, download, extract, parse, validate, and transform files for downstream workflow processing."
    category = "Data Transformation"
    icon = "data_load"
    parameters_schema = DataLoadParams
    credential_types = ["http", "basic_auth", "bearer_auth", "header_auth", "api_key"]
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: DataLoadParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        first_item = input_items[0] if input_items else {}

        # 1. Resolve expressions in download_url and auth_token if present
        raw_url = params.download_url
        if not raw_url and "download_url" in first_item:
            raw_url = str(first_item["download_url"])
        elif not raw_url and "url" in first_item:
            raw_url = str(first_item["url"])

        resolved_url = ""
        if raw_url:
            resolved_url = str(interpolate(raw_url, base_item=first_item))

        # Check credentials from ctx if credential_id is set
        auth_type = params.auth_type
        auth_token = params.auth_token
        if params.credential_id and hasattr(ctx, "get_credential"):
            try:
                cred = await ctx.get_credential(params.credential_id)
                if cred:
                    if "token" in cred:
                        auth_type = "bearer"
                        auth_token = cred["token"]
                    elif "api_key" in cred:
                        auth_type = "bearer"
                        auth_token = cred["api_key"]
                    elif "username" in cred and "password" in cred:
                        auth_type = "basic"
                        auth_token = f"{cred['username']}:{cred['password']}"
            except Exception:
                pass

        if auth_token:
            auth_token = str(interpolate(auth_token, base_item=first_item))

        # Check if environment is dev (to allow loopback in tests)
        from app.config import get_settings
        allow_loopback = False
        try:
            allow_loopback = get_settings().app_env != "production"
        except Exception:
            pass

        # 2. Resolve payload bytes using DataLoadService
        try:
            raw_bytes, filename_hint, source_meta = await DataLoadService.resolve_payload_bytes(
                source_mode=params.source_mode,
                download_url=resolved_url,
                file_id=params.file_id or str(first_item.get("file_id", "")),
                file_path=params.file_path or str(first_item.get("file_path", "")),
                csv_content=params.csv_content or str(first_item.get("csv", first_item.get("content", ""))),
                auth_type=auth_type,
                auth_token=auth_token,
                timeout_seconds=params.timeout_seconds,
                max_download_bytes=params.max_download_bytes,
                allow_loopback_in_dev=allow_loopback,
                node_id="flowsmith.data_load",
            )
        except NodeExecutionError as exc:
            logger.warning("DataLoadNode failed during payload resolution: %s", exc)
            raise

        # 3. Build options
        load_opts = DataLoadOptions(
            delimiter=params.delimiter or None,
            encoding=params.encoding,
            has_header=params.has_header,
            quotechar=params.quotechar or '"',
            escapechar=params.escapechar or None,
            batch_size=params.batch_size,
            null_values=params.null_values,
            archive_inner_file=params.archive_inner_file,
            archive_pattern=params.archive_pattern,
            archive_process_mode=params.archive_process_mode,
            archive_header_mode=params.archive_header_mode,
            max_nesting_depth=params.max_nesting_depth,
            row_limit=params.row_limit,
        )

        exec_id = params.execution_id or (getattr(ctx, "execution_id", None) or f"exec_{uuid.uuid4().hex[:12]}")

        # 4. Stream, validate, deduplicate, and stage records
        total_parsed = 0
        unique_count = 0
        duplicate_count = 0
        invalid_count = 0
        persisted_count = 0
        persisted_duration_ms = 0.0

        seen_keys: set[str] = set()
        accumulated_records: list[dict[str, Any]] = []
        sample_invalid: list[dict[str, Any]] = []
        sample_duplicates: list[dict[str, Any]] = []
        MAX_IN_MEMORY_RECORDS = 10000

        try:
            with get_session() as db:
                for batch in DataLoadService.stream_parsed_records(
                    raw_bytes=raw_bytes,
                    filename=filename_hint,
                    options=load_opts,
                    node_id="flowsmith.data_load",
                ):
                    val_res = CsvService.map_and_validate(
                        rows=batch,
                        field_mapping=params.field_mapping,
                        target_object=params.target_object,
                        duplicate_policy=params.duplicate_policy,
                        dedup_key=params.dedup_key,
                        seen_keys=seen_keys,
                    )

                    total_parsed += val_res.total_parsed
                    unique_count += val_res.unique_count
                    duplicate_count += val_res.duplicate_count
                    invalid_count += val_res.invalid_count

                    # Persist chunk to database if enabled
                    if params.persist_to_db and (val_res.valid_records or val_res.duplicate_records or val_res.invalid_records):
                        try:
                            p_res = CsvService.persist_staged_records(
                                db=db,
                                execution_id=exec_id,
                                valid_records=val_res.valid_records,
                                duplicate_records=val_res.duplicate_records,
                                invalid_records=val_res.invalid_records,
                                batch_size=params.batch_size,
                            )
                            persisted_count += p_res.inserted_count
                            persisted_duration_ms += p_res.duration_ms
                        except Exception as exc:
                            logger.error("Failed to persist staged records chunk: %s", exc)

                    if len(accumulated_records) < MAX_IN_MEMORY_RECORDS:
                        avail = MAX_IN_MEMORY_RECORDS - len(accumulated_records)
                        accumulated_records.extend(val_res.valid_records[:avail])

                    if len(sample_invalid) < 50:
                        sample_invalid.extend(val_res.invalid_records[:50 - len(sample_invalid)])
                    if len(sample_duplicates) < 50:
                        sample_duplicates.extend(val_res.duplicate_records[:50 - len(sample_duplicates)])

        except NodeExecutionError as exc:
            logger.warning("DataLoadNode failed during parsing: %s", exc)
            return NodeResult(output_items=[{
                "success": False,
                "error": str(exc.message if hasattr(exc, "message") else exc),
                "error_code": getattr(exc, "code", "DATA_LOAD_ERROR"),
                "total_parsed": total_parsed,
            }])

        summary = {
            "success": True,
            "execution_id": exec_id,
            "filename": filename_hint,
            "source_type": source_meta.get("source_type", params.source_mode),
            "total_parsed": total_parsed,
            "unique_count": unique_count,
            "duplicate_count": duplicate_count,
            "invalid_count": invalid_count,
            "persisted_count": persisted_count,
            "persistence_duration_ms": round(persisted_duration_ms, 2),
            "target_object": params.target_object,
            "duplicate_policy": params.duplicate_policy,
            "streaming_mode": "constant_memory_chunked",
            "staged_table": "staged_contacts" if params.persist_to_db else None,
            "source_metadata": source_meta,
        }

        output_item = {
            "summary": summary,
            "records": accumulated_records,
            "rows": accumulated_records,
            "invalid_records": sample_invalid,
            "duplicate_records": sample_duplicates,
        }

        return NodeResult(output_items=[output_item])
