"""Microsoft Teams connector definition (Phase 11 business connectors).

Graph API operations over the shared 'microsoft_graph' credential
(client-credentials app with Teams permissions):

1. send_message   - post a channel message (HTML auto-escaped)
2. list_teams     - teams the app identity has joined
3. list_channels  - channels inside a team
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

MSTEAMS_CONNECTOR_KEY = "msteams"
MSTEAMS_CONNECTOR_VERSION = "1.0.0"
MSTEAMS_OPERATION_VERSION = "1.0.0"


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
        connector_key=MSTEAMS_CONNECTOR_KEY,
        connector_version=MSTEAMS_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=MSTEAMS_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="microsoft_graph",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["msteams"],
    )


def _msteams_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "send_message": _operation(
            "send_message", "Send Channel Message",
            "Post a message into a Teams channel.",
            {
                "team_id": {"type": "string", "title": "Team id"},
                "channel_id": {"type": "string", "title": "Channel id"},
                "content": {"type": "string", "title": "Message text"},
                "subject": {"type": "string", "title": "Subject (optional)"},
            },
            ["team_id", "channel_id", "content"],
            {
                "type": "object",
                "properties": {"message_id": {"type": "string"}, "success": {"type": "boolean"}},
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "list_teams": _operation(
            "list_teams", "List Teams",
            "List the teams the identity has joined.",
            {},
            [],
            {"type": "object", "properties": {"teams": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
        "list_channels": _operation(
            "list_channels", "List Channels",
            "List channels of one team.",
            {"team_id": {"type": "string", "title": "Team id"}},
            ["team_id"],
            {"type": "object", "properties": {"channels": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
    }


def _microsoft_graph_credential_type() -> dict[str, CredentialTypeV1]:
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


def build_msteams_definition() -> ConnectorDefinitionV1:
    """Build the Microsoft Teams connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=MSTEAMS_CONNECTOR_KEY,
        display_name="Microsoft Teams",
        description="Send messages and browse teams/channels via the Microsoft Graph API.",
        category="communication",
        connector_version=MSTEAMS_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_msteams_operations(),
        triggers={},
        credential_types=_microsoft_graph_credential_type(),
        metadata={
            "initial_operations": ["send_message", "list_teams", "list_channels"],
            "auth": "client-credentials app (microsoft_graph credential)",
        },
        icon="👥",
    )
