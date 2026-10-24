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


def _gmail_operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    output_schema: dict,
    *,
    retryable: bool = True,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=KEY,
        connector_version=VERSION,
        operation_key=key,
        operation_version=VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="gmail",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["gmail"],
    )


def build_gmail_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=KEY,
        display_name="Gmail",
        description="Send, search, and read Gmail messages through the Gmail API.",
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
            "list_messages": _gmail_operation(
                "list_messages",
                "List Messages",
                "Search/list Gmail message ids. Requires the gmail.readonly scope.",
                {
                    "query": {"type": "string", "title": "Gmail query", "description": "e.g. from:alerts@example.com is:unread"},
                    "max_results": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                    "page_token": {"type": "string", "title": "Page token"},
                },
                [],
                {
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array", "items": {"type": "object"}},
                        "count": {"type": "integer"},
                        "next_page_token": {"type": "string"},
                    },
                },
            ),
            "get_message": _gmail_operation(
                "get_message",
                "Get Message",
                "Fetch one Gmail message's metadata or full payload. Requires gmail.readonly.",
                {
                    "message_id": {"type": "string", "title": "Message id"},
                    "format": {
                        "type": "string",
                        "title": "Format",
                        "enum": ["metadata", "full", "raw", "minimal"],
                        "default": "metadata",
                    },
                },
                ["message_id"],
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "thread_id": {"type": "string"},
                        "snippet": {"type": "string"},
                        "label_ids": {"type": "array", "items": {"type": "string"}},
                        "payload": {"type": "object"},
                    },
                },
            ),
            "get_profile": _gmail_operation(
                "get_profile",
                "Get Profile",
                "Return the connected mailbox profile. Requires gmail.readonly.",
                {},
                [],
                {
                    "type": "object",
                    "properties": {
                        "email_address": {"type": "string"},
                        "messages_total": {"type": "integer"},
                        "threads_total": {"type": "integer"},
                    },
                },
            ),
            "list_labels": _gmail_operation(
                "list_labels",
                "List Labels",
                "List Gmail labels. Requires gmail.readonly.",
                {},
                [],
                {
                    "type": "object",
                    "properties": {
                        "labels": {"type": "array", "items": {"type": "object"}},
                        "count": {"type": "integer"},
                    },
                },
            ),
        },
        triggers={},
        credential_types={
            "gmail": CredentialTypeV1(
                type_key="gmail",
                display_name="Gmail",
                description=(
                    "Gmail connection via 'Connect Gmail' — refresh token stored encrypted; "
                    "access tokens minted server-side on demand. Read operations require "
                    "the gmail.readonly scope; reconnect after enabling it."
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
        metadata={
            "initial_operations": ["send", "list_messages", "get_message", "get_profile", "list_labels"],
            "auth": "OAuth2 offline access; gmail.send for send, gmail.readonly for read operations",
        },
        icon="gmail",
    )
