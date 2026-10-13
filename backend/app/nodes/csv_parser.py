"""Native Flowsmith CSV Parser & Ingestion Node (Production-Grade).

Features:
- Streaming chunked parsing with UTF-8 BOM handling and dialect sniffing.
- Visual/explicit field mapping (source CSV columns -> target Salesforce Contact fields).
- Strict schema validation (required fields, lengths, email format).
- Configurable deduplication policies (skip, update, error).
- Transactional database persistence in bounded batches to `staged_contacts`.
- Structured stage metrics (parsed, valid, invalid, duplicate, persisted counts).
- Downstream output compatibility for Salesforce Batch/Bulk nodes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.services.csv_service import CsvService, CsvParseOptions
from app.db import get_session

logger = logging.getLogger(__name__)


class CsvParserParams(BaseModel):
    source_type: Literal["auto", "upload", "url", "file_path", "inline"] = Field(
        default="auto", description="Source mode: upload (imported file), url (download link), file_path, or inline."
    )
    download_url: str = Field(
        default="", description="Remote HTTP/HTTPS download link to fetch CSV, TSV, or ZIP/GZ archive."
    )
    file_path: str = Field(
        default="", description="Path to CSV, TSV, or ZIP/GZ file on local filesystem or container."
    )
    file_id: str = Field(
        default="", description="Flowsmith ObjectStore file ID (uploaded file)."
    )
    csv_content: str = Field(
        default="", description="Inline raw CSV/TSV string or base64 data URL (e.g. data:application/zip;base64,...)."
    )
    archive_inner_file: str = Field(
        default="", description="Specific filename to extract inside ZIP/TAR archive (auto-detects if empty)."
    )
    file_format: str = Field(
        default="auto", description="Format hint: auto, csv, tsv, zip, gz, tar."
    )
    delimiter: str = Field(
        default="", description="Field delimiter (comma ',', tab '\\t', semicolon ';', pipe '|'). Empty for auto-detect."
    )
    quotechar: str = Field(
        default='"', description="Quote character enclosing fields."
    )
    escapechar: str = Field(
        default="", description="Escape character."
    )
    has_header: bool = Field(
        default=True, description="Whether the first row contains column headers."
    )
    batch_size: int = Field(
        default=1000, ge=10, le=10000, description="Processing and database batch size."
    )
    target_object: str = Field(
        default="Contact", description="Target Salesforce object (Contact, Lead, Account, etc.)."
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
        description="Source CSV column to destination Salesforce field mapping.",
    )
    duplicate_policy: Literal["skip", "update", "error"] = Field(
        default="skip", description="Duplicate handling policy: skip, update, or error."
    )
    dedup_key: str = Field(
        default="Email", description="Primary key used for duplicate detection."
    )
    persist_to_db: bool = Field(
        default=True, description="Persist parsed and validated records into staged_contacts table."
    )
    execution_id: str = Field(
        default="", description="Execution correlation ID (auto-generated if empty)."
    )


from app.nodes.dataload import DataLoadNode


class CsvParserNode(DataLoadNode):
    node_type = "csv_parser"
    display_name = "Flowsmith DataLoad"
    version = 1
    description = "Import, download, extract, parse, validate, and transform files for downstream workflow processing."
    category = "Data Transformation"
    icon = "data_load"
    parameters_schema = CsvParserParams
    credential_types = ["http", "basic_auth", "bearer_auth", "header_auth", "api_key"]
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: CsvParserParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        # Determine data source: params.download_url -> params.file_path -> params.file_id -> params.csv_content -> input_items
        source: str | bytes = ""
        file_id: str | None = None
        download_url: str | None = None

        if params.download_url and params.download_url.strip():
            download_url = params.download_url.strip()
        elif params.file_path and params.file_path.strip():
            if params.file_path.strip().startswith(("http://", "https://")):
                download_url = params.file_path.strip()
            else:
                source = params.file_path.strip()
        elif params.file_id and params.file_id.strip():
            file_id = params.file_id.strip()
        elif params.csv_content and params.csv_content.strip():
            if params.csv_content.strip().startswith(("http://", "https://")):
                download_url = params.csv_content.strip()
            else:
                source = params.csv_content
        elif input_items:
            first = input_items[0]
            if "download_url" in first and str(first["download_url"]).strip():
                download_url = str(first["download_url"]).strip()
            elif "url" in first and str(first["url"]).strip().startswith(("http://", "https://")):
                download_url = str(first["url"]).strip()
            elif "csv" in first:
                source = str(first["csv"])
            elif "content" in first:
                source = str(first["content"])
            elif "file_path" in first:
                source = str(first["file_path"])
            elif "file_id" in first:
                file_id = str(first["file_id"])

        if not source and not file_id and not download_url:
            logger.warning("CsvParserNode run with no CSV/TSV/ZIP source or download URL provided.")
            return NodeResult(output_items=[{
                "success": False,
                "error": "No CSV source provided (file_path, file_id, download_url, or imported csv_content required).",
                "total_parsed": 0,
            }])

        parse_opts = CsvParseOptions(
            delimiter=params.delimiter or None,
            quotechar=params.quotechar or '"',
            escapechar=params.escapechar or None,
            has_header=params.has_header,
            batch_size=params.batch_size,
        )

        exec_id = params.execution_id or (getattr(ctx, "execution_id", None) or f"exec_{uuid.uuid4().hex[:12]}")

        # Stream, validate, and persist in bounded chunks (O(1) Memory Streaming Architecture)
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

        # Keep in-memory records up to 10,000 for downstream compatibility;
        # beyond 10,000, rows are staged in PostgreSQL to protect RAM from OOM.
        MAX_IN_MEMORY_RECORDS = 10000

        meta_info: dict[str, Any] = {}

        with get_session() as db:
            for batch in CsvService.stream_parsed_rows(
                csv_source=source,
                options=parse_opts,
                file_id=file_id,
                download_url=download_url,
                archive_inner_file=params.archive_inner_file or None,
                source_meta_out=meta_info,
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

                # Persist chunk immediately to database if configured
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
                        logger.error("Failed to persist staged records chunk to database: %s", exc)

                # Collect records up to bounded threshold for downstream nodes
                if len(accumulated_records) < MAX_IN_MEMORY_RECORDS:
                    available_slots = MAX_IN_MEMORY_RECORDS - len(accumulated_records)
                    accumulated_records.extend(val_res.valid_records[:available_slots])

                # Sample up to 50 invalid & duplicates for UI debug inspection
                if len(sample_invalid) < 50:
                    sample_invalid.extend(val_res.invalid_records[:50 - len(sample_invalid)])
                if len(sample_duplicates) < 50:
                    sample_duplicates.extend(val_res.duplicate_records[:50 - len(sample_duplicates)])

        summary = {
            "success": True,
            "execution_id": exec_id,
            "detected_format": meta_info.get("detected_format", "csv"),
            "inner_filename": meta_info.get("inner_filename"),
            "archive_files": meta_info.get("archive_files", []),
            "detected_delimiter": meta_info.get("detected_delimiter", params.delimiter or ","),
            "source_type": (
                "url" if download_url else ("file_id" if file_id else ("file_path" if params.file_path else "inline_or_upload"))
            ),
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
        }

        # Provide output usable by downstream nodes (e.g. Salesforce bulk node)
        output_item = {
            "summary": summary,
            "records": accumulated_records,
            "invalid_records": sample_invalid,
            "duplicate_records": sample_duplicates,
        }

        return NodeResult(output_items=[output_item])
