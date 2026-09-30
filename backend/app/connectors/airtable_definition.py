"""Airtable connector definition (Phase 11 business connectors).

1. list_records  - offset-paginated listing
2. get_record    - fetch one record
3. create_record - add a record
4. update_record - patch record fields
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

AIRTABLE_CONNECTOR_KEY = "airtable"
AIRTABLE_CONNECTOR_VERSION = "1.0.0"
AIRTABLE_OPERATION_VERSION = "1.0.0"


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
        connector_key=AIRTABLE_CONNECTOR_KEY,
        connector_version=AIRTABLE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=AIRTABLE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="airtable",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["airtable"],
    )


_BASE = {"type": "string", "title": "Base id (app…)"}
_TABLE = {"type": "string", "title": "Table name or id"}


def _airtable_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "list_records": _operation(
            "list_records", "List Records",
            "List records of one table (offset pagination).",
            {
                "base_id": _BASE, "table_name": _TABLE,
                "view": {"type": "string", "title": "View name"},
                "filter_by_formula": {"type": "string", "title": "Filter by formula"},
                "page_size": {"type": "integer", "title": "Page size", "default": 100, "minimum": 1, "maximum": 100},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
            },
            ["base_id", "table_name"],
            {"type": "object", "properties": {"records": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
        "get_record": _operation(
            "get_record", "Get Record",
            "Fetch one record by id (rec…).",
            {
                "base_id": _BASE, "table_name": _TABLE,
                "record_id": {"type": "string", "title": "Record id"},
            },
            ["base_id", "table_name", "record_id"],
            {"type": "object", "properties": {"record": {"type": "object"}}},
            retryable=True,
        ),
        "create_record": _operation(
            "create_record", "Create Record",
            "Create a record from a fields map.",
            {
                "base_id": _BASE, "table_name": _TABLE,
                "fields": {"type": "object", "title": "Fields"},
            },
            ["base_id", "table_name", "fields"],
            {"type": "object", "properties": {"record_id": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "update_record": _operation(
            "update_record", "Update Record",
            "Patch fields of an existing record.",
            {
                "base_id": _BASE, "table_name": _TABLE,
                "record_id": {"type": "string", "title": "Record id"},
                "fields": {"type": "object", "title": "Field updates"},
            },
            ["base_id", "table_name", "record_id", "fields"],
            {"type": "object", "properties": {"record_id": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=True,
        ),
    }


def _airtable_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "airtable": CredentialTypeV1(
            type_key="airtable",
            display_name="Airtable",
            description=(
                "Airtable personal access token with the data.records scopes for "
                "the bases your workflows touch."
            ),
            secret_fields=["personal_access_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "personal_access_token": {"type": "string", "title": "Personal access token"},
                    "base_hint": {"type": "string", "title": "Base(s) used (display)"},
                },
                "required": ["personal_access_token"],
            },
            encryption_required=True,
        )
    }


def build_airtable_definition() -> ConnectorDefinitionV1:
    """Build the Airtable connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=AIRTABLE_CONNECTOR_KEY,
        display_name="Airtable",
        description="Read and write Airtable records via Web API v0.",
        category="productivity",
        connector_version=AIRTABLE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_airtable_operations(),
        triggers={},
        credential_types=_airtable_credential_type(),
        metadata={
            "initial_operations": ["list_records", "get_record", "create_record", "update_record"],
            "auth": "personal access token",
        },
        icon="🧮",
    )
