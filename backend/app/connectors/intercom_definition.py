"""Intercom customer messaging connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

INTERCOM_CONNECTOR_KEY = "intercom"
INTERCOM_CONNECTOR_VERSION = "1.0.0"
INTERCOM_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=INTERCOM_CONNECTOR_KEY,
        connector_version=INTERCOM_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=INTERCOM_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="intercom",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["intercom"],
    )


def build_intercom_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=INTERCOM_CONNECTOR_KEY,
        display_name="Intercom",
        description="Engage customers, manage support conversations, and synchronize contact data with Intercom.",
        category="customer_support",
        connector_version=INTERCOM_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_conversations": _operation(
                "list_conversations", "List Conversations", "List customer support conversations with pagination.",
                {
                    "per_page": {"type": "integer", "title": "Per Page", "default": 25},
                    "starting_after": {"type": "string", "title": "Starting After Cursor"},
                },
                [],
            ),
            "get_conversation": _operation(
                "get_conversation", "Get Conversation", "Retrieve full thread and message details for a conversation.",
                {
                    "conversation_id": {"type": "string", "title": "Conversation ID"},
                },
                ["conversation_id"],
            ),
            "reply_conversation": _operation(
                "reply_conversation", "Reply to Conversation", "Send a reply or internal note to a customer conversation.",
                {
                    "conversation_id": {"type": "string", "title": "Conversation ID"},
                    "body_text": {"type": "string", "title": "Message Body / Reply"},
                    "message_type": {"type": "string", "title": "Message Type (comment or note)", "default": "comment"},
                },
                ["conversation_id", "body_text"],
                retryable=False, idempotency="non_idempotent",
            ),
            "list_contacts": _operation(
                "list_contacts", "List Contacts", "Enumerate customer profiles and lead records.",
                {
                    "per_page": {"type": "integer", "title": "Per Page", "default": 50},
                    "starting_after": {"type": "string", "title": "Starting After Cursor"},
                },
                [],
            ),
            "create_contact": _operation(
                "create_contact", "Create or Update Contact", "Create a new lead or user contact record.",
                {
                    "email": {"type": "string", "title": "Email Address"},
                    "name": {"type": "string", "title": "Full Name"},
                    "role": {"type": "string", "title": "Role (user or lead)", "default": "user"},
                },
                [],
                retryable=True, idempotency="idempotent",
            ),
            "search_contacts": _operation(
                "search_contacts", "Search Contacts", "Find contacts using Intercom query filters.",
                {
                    "field": {"type": "string", "title": "Search Field (e.g. email, name)", "default": "email"},
                    "operator": {"type": "string", "title": "Operator (=, ~, >)", "default": "="},
                    "value": {"type": "string", "title": "Match Value"},
                },
                ["value"],
            ),
        },
        triggers={
            "conversation_webhook": ConnectorTriggerV1(
                connector_key=INTERCOM_CONNECTOR_KEY,
                connector_version=INTERCOM_CONNECTOR_VERSION,
                trigger_key="conversation_webhook",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "topics": {"type": "array", "items": {"type": "string"}, "title": "Subscribed Topics"},
                    },
                },
                credential_require="intercom",
                node_types=["intercom"],
            )
        },
        credential_types={
            "intercom": CredentialTypeV1(
                type_key="intercom",
                display_name="Intercom Access Token",
                description="Intercom Access Token from Developer Hub.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string", "title": "Access Token"},
                    },
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
    )
