"""Slack connector definition (Phase 11 business connectors).

Bot-token Slack Web API operations. The legacy webhook-only 'slack'
*node* keeps its node type; this connector registers as 'slack_api':

1. send_message  - chat.postMessage (supports thread_ts)
2. list_channels - conversations.list with cursor pagination
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

SLACK_CONNECTOR_KEY = "slack"
SLACK_CONNECTOR_VERSION = "1.0.0"
SLACK_OPERATION_VERSION = "1.0.0"


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
        connector_key=SLACK_CONNECTOR_KEY,
        connector_version=SLACK_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SLACK_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="slack",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["slack_api"],
    )


def _slack_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "send_message": _operation(
            "send_message", "Send Message",
            "Post a message to a channel via chat.postMessage.",
            {
                "channel": {"type": "string", "title": "Channel id or name"},
                "text": {"type": "string", "title": "Message text"},
                "thread_ts": {"type": "string", "title": "Thread timestamp", "description": "Reply in a thread when set."},
            },
            ["channel", "text"],
            {
                "type": "object",
                "properties": {
                    "ts": {"type": "string"},
                    "channel": {"type": "string"},
                    "sent": {"type": "boolean"},
                },
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "list_channels": _operation(
            "list_channels", "List Channels",
            "List workspace channels (conversations.list) with pagination.",
            {
                "limit": {"type": "integer", "title": "Page size", "default": 100, "minimum": 1, "maximum": 200},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
                "exclude_archived": {"type": "boolean", "title": "Exclude archived", "default": True},
            },
            [],
            {
                "type": "object",
                "properties": {
                    "channels": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                },
            },
            retryable=True,
        ),
        "add_reaction": _operation(
            "add_reaction", "Add Reaction",
            "Add an emoji reaction to a message via reactions.add.",
            {
                "channel": {"type": "string", "title": "Channel id", "description": "Channel containing the message."},
                "timestamp": {"type": "string", "title": "Message timestamp", "description": "Timestamp (ts) of the target message."},
                "name": {"type": "string", "title": "Emoji name", "description": "Emoji name without colons (e.g. thumbsup)."},
            },
            ["channel", "timestamp", "name"],
            {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "channel": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "reaction": {"type": "string"},
                },
            },
            retryable=False,
            idempotency="idempotent",
        ),
        "get_user_by_email": _operation(
            "get_user_by_email", "Get User by Email",
            "Look up a Slack workspace user by their email address via users.lookupByEmail.",
            {
                "email": {"type": "string", "title": "Email address", "description": "User email address to look up."},
            },
            ["email"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "real_name": {"type": "string"},
                    "email": {"type": "string"},
                    "tz": {"type": "string"},
                    "is_admin": {"type": "boolean"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "list_users": _operation(
            "list_users", "List Users",
            "List workspace members with cursor pagination via users.list.",
            {
                "limit": {"type": "integer", "title": "Page size", "default": 100, "minimum": 1, "maximum": 200},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
            },
            [],
            {
                "type": "object",
                "properties": {
                    "users": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                },
            },
            retryable=True,
        ),
        "get_channel_history": _operation(
            "get_channel_history", "Get Channel History",
            "Read recent messages from a channel via conversations.history.",
            {
                "channel": {"type": "string", "title": "Channel id"},
                "limit": {"type": "integer", "title": "How many", "default": 50, "minimum": 1, "maximum": 200},
                "oldest": {"type": "string", "title": "Oldest timestamp"},
                "latest": {"type": "string", "title": "Latest timestamp"},
            },
            ["channel"],
            {
                "type": "object",
                "properties": {
                    "messages": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "update_message": _operation(
            "update_message", "Update Message",
            "Edit an existing message via chat.update.",
            {
                "channel": {"type": "string", "title": "Channel id"},
                "timestamp": {"type": "string", "title": "Message timestamp"},
                "text": {"type": "string", "title": "New message text"},
            },
            ["channel", "timestamp", "text"],
            {
                "type": "object",
                "properties": {
                    "ts": {"type": "string"},
                    "channel": {"type": "string"},
                    "updated": {"type": "boolean"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "delete_message": _operation(
            "delete_message", "Delete Message",
            "Delete a message via chat.delete.",
            {
                "channel": {"type": "string", "title": "Channel id"},
                "timestamp": {"type": "string", "title": "Message timestamp"},
            },
            ["channel", "timestamp"],
            {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "deleted": {"type": "boolean"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
    }


def _slack_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "slack": CredentialTypeV1(
            type_key="slack",
            display_name="Slack API Credentials",
            description=(
                "Slack bot connection. Create a Slack app with chat:write, "
                "channels:read, channels:history, users:read, users:read.email, "
                "and reactions:write scopes, then paste the bot token (xoxb...)."
            ),
            secret_fields=["bot_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "bot_token": {"type": "string", "title": "Bot token (xoxb…)"},
                    "team_name": {"type": "string", "title": "Workspace name (display)"},
                },
                "required": ["bot_token"],
            },
            encryption_required=True,
        )
    }


def build_slack_definition() -> ConnectorDefinitionV1:
    """Build the Slack connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=SLACK_CONNECTOR_KEY,
        display_name="Slack API",
        description="Send, read, update, and delete Slack messages; list channels and users via the Web API.",
        category="communication",
        connector_version=SLACK_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_slack_operations(),
        triggers={},
        credential_types=_slack_credential_type(),
        metadata={
            "initial_operations": [
                "send_message", "list_channels", "add_reaction",
                "get_user_by_email", "list_users", "get_channel_history",
                "update_message", "delete_message",
            ],
            "auth": "bot token (xoxb…)",
            "node_type_note": "Legacy webhook-based 'slack' node remains available; this connector is 'slack_api'.",
        },
        icon="slack",
    )
