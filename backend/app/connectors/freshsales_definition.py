"""Freshsales CRM connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

FRESHSALES_CONNECTOR_KEY = "freshsales"
FRESHSALES_CONNECTOR_VERSION = "1.0.0"
FRESHSALES_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=FRESHSALES_CONNECTOR_KEY,
        connector_version=FRESHSALES_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=FRESHSALES_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="freshsales",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["freshsales"],
    )


def build_freshsales_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=FRESHSALES_CONNECTOR_KEY,
        display_name="Freshsales",
        description="Manage customer accounts, leads, deals, and sales pipelines in Freshworks Freshsales.",
        category="crm",
        connector_version=FRESHSALES_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_contacts": _operation(
                "list_contacts", "List Contacts", "Enumerate sales leads and contacts.",
                {
                    "page": {"type": "integer", "title": "Page", "default": 1},
                    "per_page": {"type": "integer", "title": "Per Page", "default": 25},
                },
                [],
            ),
            "get_contact": _operation(
                "get_contact", "Get Contact", "Retrieve contact details by ID.",
                {
                    "contact_id": {"type": "string", "title": "Contact ID"},
                },
                ["contact_id"],
            ),
            "create_contact": _operation(
                "create_contact", "Create Contact", "Insert a new contact into Freshsales.",
                {
                    "first_name": {"type": "string", "title": "First Name"},
                    "last_name": {"type": "string", "title": "Last Name"},
                    "email": {"type": "string", "title": "Email Address"},
                    "mobile_number": {"type": "string", "title": "Mobile Number"},
                },
                ["first_name", "last_name", "email"],
                retryable=False, idempotency="non_idempotent",
            ),
            "list_deals": _operation(
                "list_deals", "List Deals", "Enumerate sales pipeline deals.",
                {
                    "page": {"type": "integer", "title": "Page", "default": 1},
                    "per_page": {"type": "integer", "title": "Per Page", "default": 25},
                },
                [],
            ),
            "create_deal": _operation(
                "create_deal", "Create Deal", "Add a new deal opportunity to the sales pipeline.",
                {
                    "name": {"type": "string", "title": "Deal Name"},
                    "amount": {"type": "number", "title": "Deal Value / Amount"},
                },
                ["name", "amount"],
                retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "freshsales": CredentialTypeV1(
                type_key="freshsales",
                display_name="Freshsales API Credentials",
                description="Freshsales domain name (e.g. mycompany) and API token.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "title": "Domain Name (e.g. acme)"},
                        "api_key": {"type": "string", "title": "API Token"},
                    },
                    "required": ["domain", "api_key"],
                },
                encryption_required=True,
            )
        },
    )
