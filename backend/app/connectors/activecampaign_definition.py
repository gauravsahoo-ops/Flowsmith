"""ActiveCampaign connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

ACTIVECAMPAIGN_CONNECTOR_KEY = "activecampaign"
ACTIVECAMPAIGN_CONNECTOR_VERSION = "1.0.0"
ACTIVECAMPAIGN_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=ACTIVECAMPAIGN_CONNECTOR_KEY,
        connector_version=ACTIVECAMPAIGN_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ACTIVECAMPAIGN_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="activecampaign",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["activecampaign"],
    )


def build_activecampaign_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=ACTIVECAMPAIGN_CONNECTOR_KEY,
        display_name="ActiveCampaign",
        description="Automate marketing automation, subscriber list management, contacts, and campaigns with ActiveCampaign.",
        category="marketing",
        connector_version=ACTIVECAMPAIGN_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_contacts": _operation(
                "list_contacts", "List Contacts", "List subscribers and contacts with pagination.",
                {
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                    "search": {"type": "string", "title": "Search Keyword"},
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
                "create_contact", "Create or Update Contact", "Add a new subscriber or contact.",
                {
                    "email": {"type": "string", "title": "Email Address"},
                    "first_name": {"type": "string", "title": "First Name"},
                    "last_name": {"type": "string", "title": "Last Name"},
                    "phone": {"type": "string", "title": "Phone Number"},
                },
                ["email"],
                retryable=True, idempotency="idempotent",
            ),
            "list_lists": _operation(
                "list_lists", "List Mailing Lists", "Enumerate marketing lists.",
                {
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                [],
            ),
            "list_campaigns": _operation(
                "list_campaigns", "List Campaigns", "Enumerate email marketing campaigns.",
                {
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                [],
            ),
        },
        triggers={},
        credential_types={
            "activecampaign": CredentialTypeV1(
                type_key="activecampaign",
                display_name="ActiveCampaign API Credentials",
                description="ActiveCampaign account subdomain and API token.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "account": {"type": "string", "title": "Account / Subdomain (e.g. myaccount)"},
                        "api_key": {"type": "string", "title": "API Token"},
                    },
                    "required": ["account", "api_key"],
                },
                encryption_required=True,
            )
        },
    )
