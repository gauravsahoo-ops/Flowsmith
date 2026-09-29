"""Twilio SendGrid connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

SENDGRID_CONNECTOR_KEY = "sendgrid"
SENDGRID_CONNECTOR_VERSION = "1.0.0"
SENDGRID_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=SENDGRID_CONNECTOR_KEY,
        connector_version=SENDGRID_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SENDGRID_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="sendgrid",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["sendgrid"],
    )


def build_sendgrid_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=SENDGRID_CONNECTOR_KEY,
        display_name="Twilio SendGrid",
        description="Deliver high-volume transactional and marketing emails, manage subscriber contacts, and query delivery stats with SendGrid.",
        category="marketing",
        connector_version=SENDGRID_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "send_mail": _operation(
                "send_mail", "Send Email", "Send transactional email with plain text or HTML body.",
                {
                    "to_email": {"type": "string", "title": "Recipient Email"},
                    "from_email": {"type": "string", "title": "Sender Email"},
                    "subject": {"type": "string", "title": "Subject Line"},
                    "content": {"type": "string", "title": "Email Body Content"},
                    "is_html": {"type": "boolean", "title": "Body is HTML", "default": False},
                },
                ["to_email", "from_email", "subject", "content"],
                retryable=False, idempotency="non_idempotent",
            ),
            "list_contacts": _operation(
                "list_contacts", "List Marketing Contacts", "List subscribers and contacts in SendGrid marketing campaigns.",
                {
                    "page_size": {"type": "integer", "title": "Page Size", "default": 50},
                    "page_token": {"type": "string", "title": "Page Token"},
                },
                [],
            ),
            "add_contact": _operation(
                "add_contact", "Add or Update Contact", "Add a new recipient to marketing contact lists.",
                {
                    "email": {"type": "string", "title": "Contact Email"},
                    "first_name": {"type": "string", "title": "First Name"},
                    "last_name": {"type": "string", "title": "Last Name"},
                },
                ["email"],
                retryable=True, idempotency="idempotent",
            ),
            "get_stats": _operation(
                "get_stats", "Get Delivery Stats", "Query delivery statistics, opens, clicks, and bounce rates.",
                {
                    "start_date": {"type": "string", "title": "Start Date (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "title": "End Date (YYYY-MM-DD)"},
                },
                ["start_date"],
            ),
        },
        triggers={
            "event_webhook": ConnectorTriggerV1(
                connector_key=SENDGRID_CONNECTOR_KEY,
                connector_version=SENDGRID_CONNECTOR_VERSION,
                trigger_key="event_webhook",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "items": {"type": "string"}, "title": "Event Types (delivered, opened, clicked, bounced)"},
                    },
                },
                credential_require="sendgrid",
                node_types=["sendgrid"],
            )
        },
        credential_types={
            "sendgrid": CredentialTypeV1(
                type_key="sendgrid",
                display_name="SendGrid API Key",
                description="Twilio SendGrid API Key (SG....).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API Key (SG....)"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
    )
