"""Discord connector definition (Phase 11 business connectors).

1. send_message - bot-token channel message (2000-char cap enforced)
2. send_webhook - incoming-webhook delivery (URL passed per call)
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

DISCORD_CONNECTOR_KEY = "discord"
DISCORD_CONNECTOR_VERSION = "1.0.0"
DISCORD_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    output_schema: dict,
    *,
    credential_require: str | None = "discord",
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=DISCORD_CONNECTOR_KEY,
        connector_version=DISCORD_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=DISCORD_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require=credential_require,
        retryable=retryable,
        idempotency=idempotency,
        node_types=["discord"],
    )


def _discord_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "send_message": _operation(
            "send_message", "Send Channel Message",
            "Send a message to a text channel via the bot API.",
            {
                "channel_id": {"type": "string", "title": "Channel id"},
                "content": {"type": "string", "title": "Message content"},
            },
            ["channel_id", "content"],
            {
                "type": "object",
                "properties": {"message_id": {"type": "string"}, "sent": {"type": "boolean"}},
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "send_webhook": _operation(
            "send_webhook", "Send Webhook",
            "Deliver a message through an incoming webhook URL (no bot needed).",
            {
                "webhook_url": {"type": "string", "title": "Webhook URL"},
                "content": {"type": "string", "title": "Message content"},
                "username": {"type": "string", "title": "Override username"},
            },
            ["webhook_url", "content"],
            {"type": "object", "properties": {"sent": {"type": "boolean"}}},
            credential_require=None,
            retryable=False,
            idempotency="non_idempotent",
        ),
    }


def _discord_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "discord": CredentialTypeV1(
            type_key="discord",
            display_name="Discord",
            description=(
                "Discord bot token from the developer portal. The bot needs "
                "'Send Messages' permission in the target channels. Webhook "
                "delivery needs no stored token."
            ),
            secret_fields=["bot_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "bot_token": {"type": "string", "title": "Bot token"},
                    "guild_name": {"type": "string", "title": "Server name (display)"},
                },
                "required": ["bot_token"],
            },
            encryption_required=True,
        )
    }


def build_discord_definition() -> ConnectorDefinitionV1:
    """Build the Discord connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=DISCORD_CONNECTOR_KEY,
        display_name="Discord",
        description="Send Discord messages via bot API or incoming webhooks.",
        category="communication",
        connector_version=DISCORD_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_discord_operations(),
        triggers={},
        credential_types=_discord_credential_type(),
        metadata={
            "initial_operations": ["send_message", "send_webhook"],
            "auth": "bot token, or per-call webhook URL",
        },
        icon="🎮",
    )
