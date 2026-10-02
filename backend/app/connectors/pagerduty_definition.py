"""PagerDuty connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

PAGERDUTY_CONNECTOR_KEY = "pagerduty"
PAGERDUTY_CONNECTOR_VERSION = "1.0.0"
PAGERDUTY_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=PAGERDUTY_CONNECTOR_KEY,
        connector_version=PAGERDUTY_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=PAGERDUTY_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="pagerduty",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["pagerduty"],
    )


def build_pagerduty_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=PAGERDUTY_CONNECTOR_KEY,
        display_name="PagerDuty",
        description="Manage PagerDuty incidents and notes.",
        category="devops",
        connector_version=PAGERDUTY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_incidents": _operation(
                "list_incidents", "List Incidents", "List incidents.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_incident": _operation(
                "get_incident", "Get Incident", "Fetch one incident by id.",
                {"incident_id": {"type": "string", "title": "Incident id"}}, ["incident_id"],
            ),
            "create_incident": _operation(
                "create_incident", "Trigger Incident", "Create (trigger) an incident.",
                {
                    "title": {"type": "string", "title": "Title"},
                    "service_id": {"type": "string", "title": "Service id"},
                    "urgency": {"type": "string", "title": "Urgency (high/low)"},
                    "description": {"type": "string", "title": "Details"},
                },
                ["title", "service_id"], retryable=False, idempotency="non_idempotent",
            ),
            "update_incident": _operation(
                "update_incident", "Update Incident", "Patch incident fields.",
                {
                    "incident_id": {"type": "string", "title": "Incident id"},
                    "status": {"type": "string", "title": "Status"},
                    "urgency": {"type": "string", "title": "Urgency"},
                },
                ["incident_id"],
            ),
            "resolve_incident": _operation(
                "resolve_incident", "Resolve Incident", "Mark an incident resolved.",
                {"incident_id": {"type": "string", "title": "Incident id"}}, ["incident_id"],
            ),
            "add_note": _operation(
                "add_note", "Add Note", "Add a note to an incident.",
                {
                    "incident_id": {"type": "string", "title": "Incident id"},
                    "content": {"type": "string", "title": "Note content"},
                },
                ["incident_id", "content"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "pagerduty": CredentialTypeV1(
                type_key="pagerduty",
                display_name="PagerDuty",
                description="PagerDuty API token (Configuration > API Access).",
                secret_fields=["api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"api_token": {"type": "string", "title": "API token"}},
                    "required": ["api_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_incidents", "get_incident", "create_incident", "update_incident", "resolve_incident", "add_note"], "auth": "API token"},
        icon="pagerduty",
    )
