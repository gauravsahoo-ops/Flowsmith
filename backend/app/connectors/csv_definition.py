"""CSV Connector Definition for Flowsmith.

Versioned ConnectorDefinitionV1 defining operations for:
1. parse             - Stream/parse CSV rows with dialect options and BOM stripping.
2. validate_and_map - Validate schema and map fields to target Salesforce object.
3. deduplicate       - Detect and isolate duplicate records using designated keys.
4. stage_to_database - Persist records into staged_contacts table with batch transactions.
5. reconcile         - Reconcile Salesforce Bulk ingestion responses with staged records.
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
)

CSV_CONNECTOR_KEY = "csv"
CSV_CONNECTOR_VERSION = "1.0.0"
CSV_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    output_schema: dict,
    *,
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=CSV_CONNECTOR_KEY,
        connector_version=CSV_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=CSV_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require=None,
        retryable=retryable,
        idempotency=idempotency,
        node_types=["flowsmith.data_load", "csv", "csv_parser"],
    )


def build_csv_definition() -> ConnectorDefinitionV1:
    operations = {
        "parse": _operation(
            "parse",
            "Parse CSV / TSV / Archive",
            "Parse CSV, TSV, or ZIP/GZ archive file, URL, or raw string content into structured row dictionaries.",
            {
                "download_url": {"type": "string", "description": "Remote HTTP/HTTPS download link."},
                "file_path": {"type": "string", "description": "Local or container file path."},
                "file_id": {"type": "string", "description": "Flowsmith ObjectStore file ID."},
                "csv_content": {"type": "string", "description": "Raw CSV/TSV string or base64 data URL."},
                "archive_inner_file": {"type": "string", "description": "Specific file inside ZIP/TAR archive."},
                "delimiter": {"type": "string", "description": "Field delimiter (comma, tab, pipe, semicolon)."},
                "has_header": {"type": "boolean", "default": True, "description": "Whether first line is headers."},
                "batch_size": {"type": "integer", "default": 1000, "minimum": 1, "maximum": 10000, "description": "Streaming chunk size (range: 1-10000)."},
            },
            [],
            {
                "type": "object",
                "properties": {
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "total_parsed": {"type": "integer"},
                },
            },
        ),
        "validate_and_map": _operation(
            "validate_and_map",
            "Validate and Map Fields",
            "Map CSV source fields to target schema and enforce field length/format constraints.",
            {
                "rows": {"type": "array", "items": {"type": "object"}, "description": "Parsed CSV rows."},
                "field_mapping": {"type": "object", "description": "Source column to target field mapping."},
                "target_object": {"type": "string", "default": "Contact", "description": "Salesforce object name."},
                "duplicate_policy": {"type": "string", "enum": ["skip", "update", "error"], "default": "skip"},
                "dedup_key": {"type": "string", "default": "Email"},
            },
            ["rows", "field_mapping"],
            {
                "type": "object",
                "properties": {
                    "valid_records": {"type": "array", "items": {"type": "object"}},
                    "invalid_records": {"type": "array", "items": {"type": "object"}},
                    "duplicate_records": {"type": "array", "items": {"type": "object"}},
                    "unique_count": {"type": "integer"},
                    "duplicate_count": {"type": "integer"},
                    "invalid_count": {"type": "integer"},
                },
            },
        ),
        "stage_to_database": _operation(
            "stage_to_database",
            "Stage to Database",
            "Persist records into staged_contacts table with bounded batch transactions.",
            {
                "execution_id": {"type": "string", "description": "Execution correlation ID."},
                "valid_records": {"type": "array", "items": {"type": "object"}},
                "duplicate_records": {"type": "array", "items": {"type": "object"}},
                "invalid_records": {"type": "array", "items": {"type": "object"}},
                "batch_size": {"type": "integer", "default": 1000, "minimum": 1, "maximum": 10000, "description": "Database batch insert size (range: 1-10000)."},
            },
            ["execution_id", "valid_records"],
            {
                "type": "object",
                "properties": {
                    "total_processed": {"type": "integer"},
                    "inserted_count": {"type": "integer"},
                    "duplicate_count": {"type": "integer"},
                    "invalid_count": {"type": "integer"},
                    "duration_ms": {"type": "number"},
                },
            },
        ),
        "reconcile": _operation(
            "reconcile",
            "Reconcile Salesforce Results",
            "Update staged_contacts records with Salesforce upload IDs or error messages.",
            {
                "execution_id": {"type": "string", "description": "Execution correlation ID."},
                "successful_records": {"type": "array", "items": {"type": "object"}},
                "failed_records": {"type": "array", "items": {"type": "object"}},
            },
            ["execution_id", "successful_records"],
            {
                "type": "object",
                "properties": {
                    "reconciled_success": {"type": "integer"},
                    "reconciled_failed": {"type": "integer"},
                },
            },
        ),
    }

    return ConnectorDefinitionV1(
        connector_key=CSV_CONNECTOR_KEY,
        display_name="CSV Parser",
        description="Enterprise streaming parser and ingestion connector for CSV, TSV, and ZIP archives with URL download and upload support.",
        category="transform",
        connector_version=CSV_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=operations,
        triggers={},
        credential_types={},
        metadata={"tags": ["csv", "tsv", "zip", "archive", "files", "salesforce", "staging", "bulk"]},
        icon="csv",
    )
