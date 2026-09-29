"""Typeform connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

TYPEFORM_CONNECTOR_KEY = "typeform"
TYPEFORM_CONNECTOR_VERSION = "1.0.0"
TYPEFORM_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=TYPEFORM_CONNECTOR_KEY,
        connector_version=TYPEFORM_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=TYPEFORM_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="typeform",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["typeform"],
    )


def build_typeform_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=TYPEFORM_CONNECTOR_KEY,
        display_name="Typeform",
        description="Retrieve forms, query responses, and register webhooks with Typeform API v2.",
        category="marketing",
        connector_version=TYPEFORM_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_forms": _operation(
                "list_forms", "List Forms", "List available forms in your Typeform account.",
                {
                    "page": {"type": "integer", "title": "Page", "default": 1},
                    "page_size": {"type": "integer", "title": "Page Size", "default": 50},
                    "search": {"type": "string", "title": "Search Keyword"},
                },
                [],
            ),
            "get_form": _operation(
                "get_form", "Get Form", "Retrieve form definitions, questions, and fields.",
                {
                    "form_id": {"type": "string", "title": "Form ID"},
                },
                ["form_id"],
            ),
            "get_responses": _operation(
                "get_responses", "Get Responses", "Retrieve form submissions and question answers.",
                {
                    "form_id": {"type": "string", "title": "Form ID"},
                    "page_size": {"type": "integer", "title": "Page Size", "default": 25},
                    "since": {"type": "string", "title": "Since (ISO-8601 Timestamp)"},
                    "until": {"type": "string", "title": "Until (ISO-8601 Timestamp)"},
                    "completed": {"type": "boolean", "title": "Completed Only", "default": True},
                },
                ["form_id"],
            ),
            "create_webhook": _operation(
                "create_webhook", "Create Webhook", "Register an automated webhook for form submissions.",
                {
                    "form_id": {"type": "string", "title": "Form ID"},
                    "tag": {"type": "string", "title": "Webhook Tag / Name"},
                    "url": {"type": "string", "title": "Delivery URL"},
                    "secret": {"type": "string", "title": "Signature Secret"},
                },
                ["form_id", "tag", "url"],
                retryable=False, idempotency="idempotent",
            ),
            "delete_webhook": _operation(
                "delete_webhook", "Delete Webhook", "Delete an existing webhook registration.",
                {
                    "form_id": {"type": "string", "title": "Form ID"},
                    "tag": {"type": "string", "title": "Webhook Tag / Name"},
                },
                ["form_id", "tag"],
                retryable=False, idempotency="idempotent",
            ),
        },
        triggers={
            "form_response": ConnectorTriggerV1(
                connector_key=TYPEFORM_CONNECTOR_KEY,
                connector_version=TYPEFORM_CONNECTOR_VERSION,
                trigger_key="form_response",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "form_id": {"type": "string", "title": "Form ID"},
                    },
                    "required": ["form_id"],
                },
                credential_require="typeform",
                node_types=["typeform"],
            )
        },
        credential_types={
            "typeform": CredentialTypeV1(
                type_key="typeform",
                display_name="Typeform Personal Access Token",
                description="Personal Access Token from Typeform Admin account settings.",
                secret_fields=["token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string", "title": "Personal Access Token"},
                    },
                    "required": ["token"],
                },
                encryption_required=True,
            )
        },
    )
