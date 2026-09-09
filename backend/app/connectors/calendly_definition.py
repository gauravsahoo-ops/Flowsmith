"""Calendly connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

CALENDLY_CONNECTOR_KEY = "calendly"
CALENDLY_CONNECTOR_VERSION = "1.0.0"
CALENDLY_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=CALENDLY_CONNECTOR_KEY,
        connector_version=CALENDLY_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=CALENDLY_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="calendly",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["calendly"],
    )


def build_calendly_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CALENDLY_CONNECTOR_KEY,
        display_name="Calendly",
        description="Work with Calendly event types and scheduled events.",
        category="productivity",
        connector_version=CALENDLY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_event_types": _operation(
                "list_event_types", "List Event Types", "List scheduling event types.",
                {"user_uri": {"type": "string", "title": "User URI (optional)"}}, [],
            ),
            "list_events": _operation(
                "list_events", "List Events", "List scheduled events.",
                {
                    "user_uri": {"type": "string", "title": "User URI (optional)"},
                    "count": {"type": "integer", "title": "Count"},
                },
                [],
            ),
            "get_event": _operation(
                "get_event", "Get Event", "Fetch one scheduled event.",
                {"event_uuid": {"type": "string", "title": "Event UUID"}}, ["event_uuid"],
            ),
            "cancel_event": _operation(
                "cancel_event", "Cancel Event", "Cancel a scheduled event.",
                {"event_uuid": {"type": "string", "title": "Event UUID"}}, ["event_uuid"],
                retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "calendly": CredentialTypeV1(
                type_key="calendly",
                display_name="Calendly",
                description="Calendly personal access token (Integrations > API & Webhooks).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"access_token": {"type": "string", "title": "Personal access token"}},
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_event_types", "list_events", "get_event", "cancel_event"], "auth": "PAT Bearer"},
        icon="📅",
    )
