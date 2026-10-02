"""Twilio connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

TWILIO_CONNECTOR_KEY = "twilio"
TWILIO_CONNECTOR_VERSION = "1.0.0"
TWILIO_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=TWILIO_CONNECTOR_KEY,
        connector_version=TWILIO_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=TWILIO_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="twilio",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["twilio"],
    )


def build_twilio_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=TWILIO_CONNECTOR_KEY,
        display_name="Twilio",
        description="Send and inspect Twilio SMS messages.",
        category="communication",
        connector_version=TWILIO_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "send_sms": _operation(
                "send_sms", "Send SMS", "Send an SMS message.",
                {
                    "from_number": {"type": "string", "title": "From number"},
                    "to_number": {"type": "string", "title": "To number"},
                    "body": {"type": "string", "title": "Message body"},
                },
                ["from_number", "to_number", "body"], retryable=False, idempotency="non_idempotent",
            ),
            "list_messages": _operation(
                "list_messages", "List Messages", "List recent messages.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_message": _operation(
                "get_message", "Get Message", "Fetch one message by SID.",
                {"message_sid": {"type": "string", "title": "Message SID"}}, ["message_sid"],
            ),
        },
        triggers={},
        credential_types={
            "twilio": CredentialTypeV1(
                type_key="twilio",
                display_name="Twilio",
                description="Twilio Account SID + Auth Token (Console dashboard).",
                secret_fields=["account_sid", "auth_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "account_sid": {"type": "string", "title": "Account SID"},
                        "auth_token": {"type": "string", "title": "Auth Token"},
                    },
                    "required": ["account_sid", "auth_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["send_sms", "list_messages", "get_message"], "auth": "Basic"},
        icon="twilio",
    )
