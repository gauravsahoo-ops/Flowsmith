"""Microsoft Outlook connector definition (Phase 11 business connectors).

Mail operations over the shared 'microsoft_graph' credential:

1. send_mail    - send as the app identity (Mail.Send)
2. list_messages- read a folder (default Inbox), newest first
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

OUTLOOK_CONNECTOR_KEY = "outlook"
OUTLOOK_CONNECTOR_VERSION = "1.0.0"
OUTLOOK_OPERATION_VERSION = "1.0.0"


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
        connector_key=OUTLOOK_CONNECTOR_KEY,
        connector_version=OUTLOOK_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OUTLOOK_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="microsoft_graph",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["outlook"],
    )


def _outlook_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "send": _operation(
            "send", "Send Mail",
            "Send an email from the connected identity.",
            {
                "to": {"type": "array", "title": "To", "items": {"type": "string"}},
                "subject": {"type": "string", "title": "Subject"},
                "body": {"type": "string", "title": "Body"},
                "cc": {"type": "array", "title": "Cc", "items": {"type": "string"}},
                "save_to_sent": {"type": "boolean", "title": "Save to Sent Items", "default": True},
            },
            ["to", "subject", "body"],
            {"type": "object", "properties": {"sent": {"type": "boolean"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "list_messages": _operation(
            "list_messages", "List Messages",
            "List the newest messages of one mail folder.",
            {
                "folder": {"type": "string", "title": "Folder", "default": "Inbox"},
                "top": {"type": "integer", "title": "How many", "default": 10, "minimum": 1, "maximum": 50},
            },
            [],
            {"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
    }


def _outlook_credential_type() -> dict[str, CredentialTypeV1]:
    """Same Azure-app credential type as Teams — declared here too because
    the registry validates per-definition references."""
    return {
        "microsoft_graph": CredentialTypeV1(
            type_key="microsoft_graph",
            display_name="Microsoft Graph",
            description=(
                "Azure app registration used by the Microsoft Teams and Outlook "
                "connectors: tenant id + client id + client secret. The app needs "
                "application permissions (e.g. ChannelMessage.Send, Mail.Send) "
                "granted by an admin."
            ),
            secret_fields=["client_secret"],
            validation_schema={
                "type": "object",
                "properties": {
                    "tenant_id": {"type": "string", "title": "Directory (tenant) id"},
                    "client_id": {"type": "string", "title": "Application (client) id"},
                    "client_secret": {"type": "string", "title": "Client secret"},
                },
                "required": ["tenant_id", "client_id", "client_secret"],
            },
            encryption_required=True,
        )
    }


def build_outlook_definition() -> ConnectorDefinitionV1:
    """Build the Microsoft Outlook connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=OUTLOOK_CONNECTOR_KEY,
        display_name="Microsoft Outlook",
        description="Send and read Outlook mail via the Microsoft Graph API.",
        category="communication",
        connector_version=OUTLOOK_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_outlook_operations(),
        triggers={},
        credential_types=_outlook_credential_type(),
        metadata={
            "initial_operations": ["send", "list_messages"],
            "auth": "client-credentials app (microsoft_graph credential)",
        },
        icon="outlook",
    )
