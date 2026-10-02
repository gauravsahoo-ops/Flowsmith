"""WhatsApp Cloud API connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

WHATSAPP_CONNECTOR_KEY = "whatsapp"
WHATSAPP_CONNECTOR_VERSION = "1.0.0"
WHATSAPP_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=WHATSAPP_CONNECTOR_KEY,
        connector_version=WHATSAPP_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=WHATSAPP_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="whatsapp",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["whatsapp"],
    )


def build_whatsapp_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=WHATSAPP_CONNECTOR_KEY,
        display_name="WhatsApp",
        description="Send WhatsApp Business Cloud API text and template messages.",
        category="communication",
        connector_version=WHATSAPP_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "send_text": _operation(
                "send_text", "Send Text Message", "Send a free-form text message.",
                {
                    "to": {"type": "string", "title": "Recipient phone (E.164)"},
                    "body": {"type": "string", "title": "Message body"},
                    "preview_url": {"type": "boolean", "title": "Preview URLs"},
                },
                ["to", "body"], retryable=False, idempotency="non_idempotent",
            ),
            "send_template": _operation(
                "send_template", "Send Template Message", "Send an approved message template.",
                {
                    "to": {"type": "string", "title": "Recipient phone (E.164)"},
                    "template": {"type": "string", "title": "Template name"},
                    "language": {"type": "string", "title": "Template locale"},
                },
                ["to", "template"], retryable=False, idempotency="non_idempotent",
            ),
            "get_message": _operation(
                "get_message", "Get Message", "Fetch a sent message by id.",
                {"message_id": {"type": "string", "title": "Message id"}},
                ["message_id"],
            ),
        },
        triggers={},
        credential_types={
            "whatsapp": CredentialTypeV1(
                type_key="whatsapp",
                display_name="WhatsApp",
                description="Meta WhatsApp Business Cloud API token + phone number id.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string", "title": "Permanent access token"},
                        "phone_number_id": {"type": "string", "title": "Phone number ID"},
                    },
                    "required": ["access_token", "phone_number_id"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["send_text", "send_template", "get_message"], "auth": "Bearer token"},
        icon="whatsapp",
    )
