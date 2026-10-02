"""Gmail connector definition (Phase 41): single send operation."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

KEY = "gmail"
VERSION = "1.0.0"


def build_gmail_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=KEY,
        display_name="Gmail",
        description="Send email through Gmail via the send-only OAuth scope.",
        category="communication",
        connector_version=VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "send": ConnectorOperationV1(
                connector_key=KEY,
                connector_version=VERSION,
                operation_key="send",
                operation_version=VERSION,
                display_name="Send Email",
                description="Send an email from the connected Gmail account.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "title": "To", "description": "Comma-separated recipients"},
                        "cc": {"type": "string", "title": "Cc"},
                        "bcc": {"type": "string", "title": "Bcc"},
                        "subject": {"type": "string", "title": "Subject"},
                        "body_text": {"type": "string", "title": "Body"},
                        "html": {"type": "boolean", "title": "HTML body", "default": False},
                        "timeout_seconds": {"type": "number", "default": 30, "minimum": 1},
                    },
                    "required": ["to"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "thread_id": {"type": "string"},
                        "sent": {"type": "boolean"},
                    },
                },
                credential_require="gmail",
                retryable=False,  # sends are not retried automatically
                idempotency="non_idempotent",
                node_types=["gmail"],
            ),
        },
        triggers={},
        credential_types={
            "gmail": CredentialTypeV1(
                type_key="gmail",
                display_name="Gmail",
                description=(
                    "Gmail send-only connection via 'Connect Gmail' — refresh token stored "
                    "encrypted; access tokens minted server-side on demand."
                ),
                secret_fields=["refresh_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "user": {"type": "string", "title": "Authorizing account (display)"},
                        "refresh_token": {"type": "string", "title": "Refresh Token"},
                        "oauth": {"type": "boolean", "title": "OAuth-connected", "default": False},
                    },
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["send"], "auth": "OAuth2 offline access, gmail.send scope"},
        icon="gmail",
    )
