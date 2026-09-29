"""Zoho CRM connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

ZOHO_CRM_CONNECTOR_KEY = "zoho_crm"
ZOHO_CRM_CONNECTOR_VERSION = "1.0.0"
ZOHO_CRM_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=ZOHO_CRM_CONNECTOR_KEY,
        connector_version=ZOHO_CRM_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ZOHO_CRM_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="zoho_crm",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["zoho_crm"],
    )


def build_zoho_crm_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=ZOHO_CRM_CONNECTOR_KEY,
        display_name="Zoho CRM",
        description="Synchronize leads, contacts, deals, and accounts with Zoho CRM v2 API.",
        category="crm",
        connector_version=ZOHO_CRM_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_records": _operation(
                "list_records", "List Records", "List records from a Zoho CRM module (Leads, Contacts, Accounts, Deals).",
                {
                    "module": {"type": "string", "title": "Module Name", "default": "Leads"},
                    "page": {"type": "integer", "title": "Page", "default": 1},
                    "per_page": {"type": "integer", "title": "Per Page", "default": 50},
                },
                ["module"],
            ),
            "get_record": _operation(
                "get_record", "Get Record", "Retrieve single record by module and record ID.",
                {
                    "module": {"type": "string", "title": "Module Name", "default": "Leads"},
                    "record_id": {"type": "string", "title": "Record ID"},
                },
                ["module", "record_id"],
            ),
            "create_records": _operation(
                "create_records", "Create Records", "Insert new records into a Zoho CRM module.",
                {
                    "module": {"type": "string", "title": "Module Name", "default": "Leads"},
                    "data": {"type": "array", "items": {"type": "object"}, "title": "Records Array"},
                },
                ["module", "data"],
                retryable=False, idempotency="non_idempotent",
            ),
            "update_records": _operation(
                "update_records", "Update Records", "Update existing records in a Zoho CRM module.",
                {
                    "module": {"type": "string", "title": "Module Name", "default": "Leads"},
                    "data": {"type": "array", "items": {"type": "object"}, "title": "Records Array"},
                },
                ["module", "data"],
                retryable=True, idempotency="idempotent",
            ),
            "search_records": _operation(
                "search_records", "Search Records", "Search module records by email, phone, word, or criteria.",
                {
                    "module": {"type": "string", "title": "Module Name", "default": "Leads"},
                    "criteria": {"type": "string", "title": "Search Criteria (e.g. ((Email:equals:user@example.com)))"},
                    "word": {"type": "string", "title": "Search Keyword"},
                    "email": {"type": "string", "title": "Search Email"},
                },
                ["module"],
            ),
        },
        triggers={},
        credential_types={
            "zoho_crm": CredentialTypeV1(
                type_key="zoho_crm",
                display_name="Zoho CRM OAuth Token",
                description="Zoho OAuth 2.0 Access Token.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string", "title": "OAuth Access Token"},
                    },
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
    )
