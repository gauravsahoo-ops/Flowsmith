"""Coda connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

CODA_CONNECTOR_KEY = "coda"
CODA_CONNECTOR_VERSION = "1.0.0"
CODA_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=CODA_CONNECTOR_KEY,
        connector_version=CODA_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=CODA_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="coda",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["coda"],
    )


def build_coda_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CODA_CONNECTOR_KEY,
        display_name="Coda",
        description="Interact with Coda docs, tables, rows, and structured workspaces.",
        category="productivity",
        connector_version=CODA_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_docs": _operation(
                "list_docs", "List Documents", "List Coda docs accessible to the API token.",
                {
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "query": {"type": "string", "title": "Search Query"},
                },
                [],
            ),
            "get_doc": _operation(
                "get_doc", "Get Document", "Retrieve metadata and details for a Coda document.",
                {
                    "doc_id": {"type": "string", "title": "Doc ID"},
                },
                ["doc_id"],
            ),
            "list_tables": _operation(
                "list_tables", "List Tables", "List all tables within a Coda doc.",
                {
                    "doc_id": {"type": "string", "title": "Doc ID"},
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                },
                ["doc_id"],
            ),
            "list_rows": _operation(
                "list_rows", "List Rows", "List rows from a Coda table.",
                {
                    "doc_id": {"type": "string", "title": "Doc ID"},
                    "table_id": {"type": "string", "title": "Table ID or Name"},
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "query": {"type": "string", "title": "Filter Query"},
                },
                ["doc_id", "table_id"],
            ),
            "insert_rows": _operation(
                "insert_rows", "Insert Rows", "Insert or upsert rows into a Coda table.",
                {
                    "doc_id": {"type": "string", "title": "Doc ID"},
                    "table_id": {"type": "string", "title": "Table ID or Name"},
                    "rows": {"type": "array", "items": {"type": "object"}, "title": "Rows Array"},
                },
                ["doc_id", "table_id", "rows"],
                retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "coda": CredentialTypeV1(
                type_key="coda",
                display_name="Coda API Token",
                description="Personal API token from coda.io/account.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API Token"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
    )
