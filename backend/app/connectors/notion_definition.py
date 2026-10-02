"""Notion connector definition (Phase 11 business connectors).

Internal-integration token operations:

1. query_database - filter + cursor-paginate a database
2. create_page    - add a page to a database (raw property objects)
3. update_page    - change properties or archive
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

NOTION_CONNECTOR_KEY = "notion"
NOTION_CONNECTOR_VERSION = "1.0.0"
NOTION_OPERATION_VERSION = "1.0.0"


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
        connector_key=NOTION_CONNECTOR_KEY,
        connector_version=NOTION_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=NOTION_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="notion",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["notion"],
    )


def _notion_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "query_database": _operation(
            "query_database", "Query Database",
            "Query a Notion database with an optional filter; follows start_cursor.",
            {
                "database_id": {"type": "string", "title": "Database id"},
                "filter": {"type": "object", "title": "Filter (Notion JSON)"},
                "page_size": {"type": "integer", "title": "Page size", "default": 50, "minimum": 1, "maximum": 100},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
            },
            ["database_id"],
            {
                "type": "object",
                "properties": {
                    "pages": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "create_page": _operation(
            "create_page", "Create Page",
            "Create a page inside a database. Properties use Notion's JSON shape.",
            {
                "database_id": {"type": "string", "title": "Database id"},
                "properties": {"type": "object", "title": "Page properties"},
            },
            ["database_id", "properties"],
            {
                "type": "object",
                "properties": {"page_id": {"type": "string"}, "url": {"type": "string"}},
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "update_page": _operation(
            "update_page", "Update Page",
            "Update page properties, or archive the page.",
            {
                "page_id": {"type": "string", "title": "Page id"},
                "properties": {"type": "object", "title": "Property updates"},
                "archived": {"type": "boolean", "title": "Archive", "default": False},
            },
            ["page_id"],
            {"type": "object", "properties": {"page_id": {"type": "string"}, "archived": {"type": "boolean"}}},
            retryable=True,
        ),
    }


def _notion_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "notion": CredentialTypeV1(
            type_key="notion",
            display_name="Notion",
            description=(
                "Notion internal integration token (ntn_… / secret_…). Share the "
                "databases/pages the connector should reach with the integration."
            ),
            secret_fields=["integration_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "integration_token": {"type": "string", "title": "Integration token"},
                    "workspace_name": {"type": "string", "title": "Workspace name (display)"},
                },
                "required": ["integration_token"],
            },
            encryption_required=True,
        )
    }


def build_notion_definition() -> ConnectorDefinitionV1:
    """Build the Notion connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=NOTION_CONNECTOR_KEY,
        display_name="Notion",
        description="Query databases and create/update pages in Notion.",
        category="productivity",
        connector_version=NOTION_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_notion_operations(),
        triggers={},
        credential_types=_notion_credential_type(),
        metadata={
            "initial_operations": ["query_database", "create_page", "update_page"],
            "auth": "internal integration token",
        },
        icon="notion",
    )
