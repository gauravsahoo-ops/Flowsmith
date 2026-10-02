"""Pipedrive connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

PIPEDRIVE_CONNECTOR_KEY = "pipedrive"
PIPEDRIVE_CONNECTOR_VERSION = "1.0.0"
PIPEDRIVE_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=PIPEDRIVE_CONNECTOR_KEY,
        connector_version=PIPEDRIVE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=PIPEDRIVE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="pipedrive",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["pipedrive"],
    )


def build_pipedrive_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=PIPEDRIVE_CONNECTOR_KEY,
        display_name="Pipedrive",
        description="Work with Pipedrive deals and notes.",
        category="productivity",
        connector_version=PIPEDRIVE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_deals": _operation(
                "list_deals", "List Deals", "List deals in the pipeline.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_deal": _operation(
                "get_deal", "Get Deal", "Fetch one deal by id.",
                {"deal_id": {"type": "string", "title": "Deal id"}}, ["deal_id"],
            ),
            "create_deal": _operation(
                "create_deal", "Create Deal", "Create a new deal.",
                {
                    "title": {"type": "string", "title": "Deal title"},
                    "value": {"type": "string", "title": "Value"},
                    "currency": {"type": "string", "title": "Currency"},
                },
                ["title"], retryable=False, idempotency="non_idempotent",
            ),
            "update_deal": _operation(
                "update_deal", "Update Deal", "Update title/value/currency.",
                {
                    "deal_id": {"type": "string", "title": "Deal id"},
                    "title": {"type": "string", "title": "Deal title"},
                    "value": {"type": "string", "title": "Value"},
                    "currency": {"type": "string", "title": "Currency"},
                },
                ["deal_id"],
            ),
            "add_note": _operation(
                "add_note", "Add Note", "Attach a note to a deal.",
                {
                    "deal_id": {"type": "string", "title": "Deal id"},
                    "content": {"type": "string", "title": "Note content"},
                },
                ["deal_id", "content"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "pipedrive": CredentialTypeV1(
                type_key="pipedrive",
                display_name="Pipedrive",
                description="Pipedrive API token + company domain.",
                secret_fields=["api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_token": {"type": "string", "title": "API token"},
                        "domain": {"type": "string", "title": "Company domain (e.g. acme.pipedrive.com)"},
                    },
                    "required": ["api_token", "domain"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_deals", "get_deal", "create_deal", "update_deal", "add_note"], "auth": "API token (query)"},
        icon="pipedrive",
    )
