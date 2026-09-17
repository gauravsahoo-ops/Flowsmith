"""Freshdesk connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

FRESHDESK_CONNECTOR_KEY = "freshdesk"
FRESHDESK_CONNECTOR_VERSION = "1.0.0"
FRESHDESK_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=FRESHDESK_CONNECTOR_KEY,
        connector_version=FRESHDESK_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=FRESHDESK_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="freshdesk",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["freshdesk"],
    )


def build_freshdesk_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=FRESHDESK_CONNECTOR_KEY,
        display_name="Freshdesk",
        description="Manage Freshdesk support tickets and notes.",
        category="support",
        connector_version=FRESHDESK_CONNECTOR_VERSION,
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
                    "description": {"type": "string", "title": "Description"},
                    "email": {"type": "string", "title": "Requester email"},
                    "priority": {"type": "integer", "title": "Priority (1-4)"},
                },
                ["subject", "description", "email"], retryable=False, idempotency="non_idempotent",
            ),
            "update_ticket": _operation(
                "update_ticket", "Update Ticket", "Patch status/priority.",
                {
                    "ticket_id": {"type": "string", "title": "Ticket id"},
                    "status": {"type": "integer", "title": "Status code"},
                    "priority": {"type": "integer", "title": "Priority (1-4)"},
                },
                ["ticket_id"],
            ),
            "add_note": _operation(
                "add_note", "Add Note", "Reply on a ticket.",
                {
                    "ticket_id": {"type": "string", "title": "Ticket id"},
                    "body": {"type": "string", "title": "Reply body"},
                },
                ["ticket_id", "body"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "freshdesk": CredentialTypeV1(
                type_key="freshdesk",
                display_name="Freshdesk",
                description="Freshdesk email + API key + domain.",
                secret_fields=["api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "title": "Agent email"},
                        "api_token": {"type": "string", "title": "API key"},
                        "domain": {"type": "string", "title": "Domain (acme in acme.freshdesk.com)"},
                    },
                    "required": ["email", "api_token", "domain"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_tickets", "get_ticket", "create_ticket", "update_ticket", "add_note"], "auth": "Email + API key (Basic)"},
        icon="🎧",
    )
