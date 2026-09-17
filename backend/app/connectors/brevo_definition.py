"""Brevo connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

BREVO_CONNECTOR_KEY = "brevo"
BREVO_CONNECTOR_VERSION = "1.0.0"
BREVO_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=BREVO_CONNECTOR_KEY,
        connector_version=BREVO_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=BREVO_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="brevo",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["brevo"],
    )


def build_brevo_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=BREVO_CONNECTOR_KEY,
        display_name="Brevo",
        description="Send Brevo transactional email and manage contacts.",
        category="marketing",
        connector_version=BREVO_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "send_email": _operation(
                "send_email", "Send Email", "Send a transactional email.",
                {
                    "sender": {"type": "string", "title": "Sender email"},
                    "to": {"type": "string", "title": "Recipient email"},
                    "subject": {"type": "string", "title": "Subject"},
                    "html": {"type": "string", "title": "HTML content"},
                    "text": {"type": "string", "title": "Text content"},
                },
                ["sender", "to", "subject"], retryable=False, idempotency="non_idempotent",
            ),
            "list_contacts": _operation(
                "list_contacts", "List Contacts", "List contacts.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_contact": _operation(
                "get_contact", "Get Contact", "Fetch one contact by email.",
                {"email": {"type": "string", "title": "Email address"}}, ["email"],
            ),
            "create_contact": _operation(
                "create_contact", "Create Contact", "Add a contact.",
                {"email": {"type": "string", "title": "Email address"}},
                ["email"], retryable=False, idempotency="non_idempotent",
            ),
            "update_contact": _operation(
                "update_contact", "Update Contact", "Update contact attributes.",
                {
                    "email": {"type": "string", "title": "Email address"},
                    "subscribed": {"type": "boolean", "title": "Subscribed"},
                },
                ["email"],
            ),
        },
        triggers={},
        credential_types={
            "brevo": CredentialTypeV1(
                type_key="brevo",
                display_name="Brevo",
                description="Brevo API key (SMTP & API > API Keys).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API key"},
                        "datacenter": {"type": "string", "title": "Datacenter override (optional)"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["send_email", "list_contacts", "get_contact", "create_contact", "update_contact"], "auth": "API key header"},
        icon="📧",
    )
