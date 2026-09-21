"""Resend connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

RESEND_CONNECTOR_KEY = "resend"
RESEND_CONNECTOR_VERSION = "1.0.0"


def build_resend_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=RESEND_CONNECTOR_KEY,
        display_name="Resend",
        description="Send transactional emails, batch campaigns, and manage email domains via Resend.",
        category=ConnectorCategory.API.value,
        connector_version=RESEND_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        credential_types={
            "resend": CredentialTypeV1(
                type_key="resend",
                display_name="Resend API Key",
                description="Resend API key starting with 're_'.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "required": ["api_key"],
                    "properties": {
                        "api_key": {"type": "string", "title": "API Key", "format": "password"},
                    },
                },
                encryption_required=True,
            )
        },
        operations={
            "send_email": ConnectorOperationV1(
                connector_key=RESEND_CONNECTOR_KEY,
                connector_version=RESEND_CONNECTOR_VERSION,
                operation_key="send_email",
                operation_version="1.0.0",
                display_name="Send Email",
                description="Deliver a single transactional email via Resend.",
                input_schema={
                    "type": "object",
                    "required": ["from", "to", "subject"],
                    "properties": {
                        "from": {"type": "string", "title": "From Address (e.g. alerts@domain.com)"},
                        "to": {"type": "string", "title": "To Address"},
                        "subject": {"type": "string", "title": "Subject Line"},
                        "html": {"type": "string", "title": "HTML Body"},
                        "text": {"type": "string", "title": "Plain Text Body"},
                        "reply_to": {"type": "string", "title": "Reply-To Address"},
                    },
                },
                output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
                credential_require="resend",
                retryable=False,
                idempotency="non_idempotent",
                node_types=["resend"],
            ),
            "get_email": ConnectorOperationV1(
                connector_key=RESEND_CONNECTOR_KEY,
                connector_version=RESEND_CONNECTOR_VERSION,
                operation_key="get_email",
                operation_version="1.0.0",
                display_name="Get Email Status",
                description="Retrieve delivery status and metadata for a sent email.",
                input_schema={
                    "type": "object",
                    "required": ["email_id"],
                    "properties": {
                        "email_id": {"type": "string", "title": "Email ID"},
                    },
                },
                output_schema={"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}}},
                credential_require="resend",
                retryable=True,
                idempotency="idempotent",
                node_types=["resend"],
            ),
            "list_domains": ConnectorOperationV1(
                connector_key=RESEND_CONNECTOR_KEY,
                connector_version=RESEND_CONNECTOR_VERSION,
                operation_key="list_domains",
                operation_version="1.0.0",
                display_name="List Domains",
                description="List verified sender domains.",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {"data": {"type": "array"}}},
                credential_require="resend",
                retryable=True,
                idempotency="idempotent",
                node_types=["resend"],
            ),
        },
        triggers={},
    )
