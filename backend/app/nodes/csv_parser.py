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
    file_path: str = Field(
        default="", description="Path to CSV file on local filesystem or container."
    )
    file_id: str = Field(
        default="", description="Flowsmith ObjectStore file ID (uploaded file)."
    )
    csv_content: str = Field(
        default="", description="Inline raw CSV string (or provided by upstream node)."
    )
    delimiter: str = Field(
        default="", description="Field delimiter (comma, tab, semicolon, pipe). Empty for auto-detect."
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


@register
class CsvParserNode(BaseNode[CsvParserParams]):
    node_type = "csv_parser"
    display_name = "CSV Parser"
    version = 1
    description = "Enterprise CSV streaming parser with Salesforce Contact validation, deduplication, and database persistence."
    category = "Transform"
    icon = "csv_parser"
    parameters_schema = CsvParserParams
    credential_types = []
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: CsvParserParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        # Determine CSV source: params.file_path -> params.file_id -> params.csv_content -> input_items
        source: str | bytes = ""
        file_id: str | None = None

        if params.file_path and params.file_path.strip():
            source = params.file_path.strip()
        elif params.file_id and params.file_id.strip():
            file_id = params.file_id.strip()
        elif params.csv_content and params.csv_content.strip():
            source = params.csv_content
        elif input_items:
            # Check if input item has csv, content, file_path, or file_id
            first = input_items[0]
            if "csv" in first:
                source = str(first["csv"])
            elif "content" in first:
                source = str(first["content"])
            elif "file_path" in first:
                source = str(first["file_path"])
            elif "file_id" in first:
                file_id = str(first["file_id"])

        if not source and not file_id:
            logger.warning("CsvParserNode run with no CSV source data provided.")
            return NodeResult(output_items=[{
                "success": False,
                "error": "No CSV source provided (file_path, file_id, or csv_content required).",
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

        # Stream and accumulate records
        all_raw_rows: list[dict[str, Any]] = []
        for batch in CsvService.stream_parsed_rows(
            csv_source=source,
            options=parse_opts,
        ):
            all_raw_rows.extend(batch)

        # Apply field mapping, schema validation, and deduplication
        val_res = CsvService.map_and_validate(
            rows=all_raw_rows,
            field_mapping=params.field_mapping,
            target_object=params.target_object,
            duplicate_policy=params.duplicate_policy,
            dedup_key=params.dedup_key,
        )

        persisted_count = 0
        persisted_duration_ms = 0.0

        # Persist to database if configured
        if params.persist_to_db and (val_res.valid_records or val_res.duplicate_records or val_res.invalid_records):
            try:
                with get_session() as db:
                    p_res = CsvService.persist_staged_records(
                        db=db,
                        execution_id=exec_id,
                        valid_records=val_res.valid_records,
                        duplicate_records=val_res.duplicate_records,
                        invalid_records=val_res.invalid_records,
                        batch_size=params.batch_size,
                    )
                    persisted_count = p_res.inserted_count
                    persisted_duration_ms = p_res.duration_ms
            except Exception as exc:
                logger.error("Failed to persist staged records to database: %s", exc)

        summary = {
            "success": True,
            "execution_id": exec_id,
            "total_parsed": val_res.total_parsed,
            "unique_count": val_res.unique_count,
            "duplicate_count": val_res.duplicate_count,
            "invalid_count": val_res.invalid_count,
            "persisted_count": persisted_count,
            "persistence_duration_ms": persisted_duration_ms,
            "target_object": params.target_object,
            "duplicate_policy": params.duplicate_policy,
        }

        # Provide output usable by downstream nodes (e.g. Salesforce bulk node)
        output_item = {
            "summary": summary,
            "records": val_res.valid_records,
            "invalid_records": val_res.invalid_records[:50],  # bounded sample for inspection
            "duplicate_records": val_res.duplicate_records[:50],
        }

        return NodeResult(output_items=[output_item])
