"""Mailchimp connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

MAILCHIMP_CONNECTOR_KEY = "mailchimp"
MAILCHIMP_CONNECTOR_VERSION = "1.0.0"
MAILCHIMP_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=MAILCHIMP_CONNECTOR_KEY,
        connector_version=MAILCHIMP_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=MAILCHIMP_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="mailchimp",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["mailchimp"],
    )


def build_mailchimp_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=MAILCHIMP_CONNECTOR_KEY,
        display_name="Mailchimp",
        description="Manage Mailchimp audiences and contacts.",
        category="marketing",
        connector_version=MAILCHIMP_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_lists": _operation(
                "list_lists", "List Audiences", "List Mailchimp audiences.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_list": _operation(
                "get_list", "Get Audience", "Fetch one audience by id.",
                {"list_id": {"type": "string", "title": "Audience id"}}, ["list_id"],
            ),
            "add_member": _operation(
                "add_member", "Add Contact", "Add a contact to an audience.",
                {
                    "list_id": {"type": "string", "title": "Audience id"},
                    "email": {"type": "string", "title": "Email address"},
                    "status": {"type": "string", "title": "Status (subscribed/pending/unsubscribed/cleaned)"},
                },
                ["list_id", "email"], retryable=False, idempotency="non_idempotent",
            ),
            "get_member": _operation(
                "get_member", "Get Contact", "Fetch one contact by email.",
                {
                    "list_id": {"type": "string", "title": "Audience id"},
                    "email": {"type": "string", "title": "Email address"},
                },
                ["list_id", "email"],
            ),
            "update_member": _operation(
                "update_member", "Update Contact", "Patch contact fields by email.",
                {
                    "list_id": {"type": "string", "title": "Audience id"},
                    "email": {"type": "string", "title": "Email address"},
                    "status": {"type": "string", "title": "Status"},
                },
                ["list_id", "email"],
            ),
        },
        triggers={},
        credential_types={
            "mailchimp": CredentialTypeV1(
                type_key="mailchimp",
                display_name="Mailchimp",
                description="Mailchimp API key (Account > Extras > API keys).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API key (ends -usXX)"},
                        "datacenter": {"type": "string", "title": "Datacenter override (optional)"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_lists", "get_list", "add_member", "get_member", "update_member"], "auth": "API key (Basic)"},
        icon="mailchimp",
    )
