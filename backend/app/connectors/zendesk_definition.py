"""Zendesk connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

ZENDESK_CONNECTOR_KEY = "zendesk"
ZENDESK_CONNECTOR_VERSION = "1.0.0"
ZENDESK_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=ZENDESK_CONNECTOR_KEY,
        connector_version=ZENDESK_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ZENDESK_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="zendesk",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["zendesk"],
    )


def build_zendesk_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=ZENDESK_CONNECTOR_KEY,
        display_name="Zendesk",
        description="Manage Zendesk support tickets and comments.",
        category="support",
        connector_version=ZENDESK_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_tickets": _operation(
                "list_tickets", "List Tickets", "List support tickets.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_ticket": _operation(
                "get_ticket", "Get Ticket", "Fetch one ticket by id.",
                {"ticket_id": {"type": "string", "title": "Ticket id"}}, ["ticket_id"],
            ),
            "create_ticket": _operation(
                "create_ticket", "Create Ticket", "Open a new ticket.",
                {
                    "subject": {"type": "string", "title": "Subject"},
                    "comment": {"type": "string", "title": "First comment"},
                    "priority": {"type": "string", "title": "Priority"},
                },
                ["subject", "comment"], retryable=False, idempotency="non_idempotent",
            ),
            "update_ticket": _operation(
                "update_ticket", "Update Ticket", "Patch status/priority/tags.",
                {
                    "ticket_id": {"type": "string", "title": "Ticket id"},
                    "status": {"type": "string", "title": "Status"},
                    "priority": {"type": "string", "title": "Priority"},
                },
                ["ticket_id"],
            ),
            "add_comment": _operation(
                "add_comment", "Add Comment", "Reply on a ticket.",
                {
                    "ticket_id": {"type": "string", "title": "Ticket id"},
                    "body": {"type": "string", "title": "Reply body"},
                },
                ["ticket_id", "body"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "zendesk": CredentialTypeV1(
                type_key="zendesk",
                display_name="Zendesk",
                description="Zendesk email + API token + subdomain.",
                secret_fields=["api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "title": "Agent email"},
                        "api_token": {"type": "string", "title": "API token"},
                        "subdomain": {"type": "string", "title": "Subdomain (acme in acme.zendesk.com)"},
                    },
                    "required": ["email", "api_token", "subdomain"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_tickets", "get_ticket", "create_ticket", "update_ticket", "add_comment"], "auth": "Email + API token (Basic)"},
        icon="zendesk",
    )
