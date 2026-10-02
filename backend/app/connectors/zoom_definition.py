"""Zoom connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

ZOOM_CONNECTOR_KEY = "zoom"
ZOOM_CONNECTOR_VERSION = "1.0.0"
ZOOM_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=ZOOM_CONNECTOR_KEY,
        connector_version=ZOOM_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ZOOM_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="zoom",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["zoom"],
    )


def build_zoom_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=ZOOM_CONNECTOR_KEY,
        display_name="Zoom",
        description="Work with Zoom users and meetings.",
        category="communication",
        connector_version=ZOOM_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_meetings": _operation(
                "list_meetings", "List Meetings", "List scheduled meetings for a user.",
                {"user_id": {"type": "string", "title": "User id or email (default me)"}}, [],
            ),
            "get_meeting": _operation(
                "get_meeting", "Get Meeting", "Fetch one meeting by id.",
                {"meeting_id": {"type": "string", "title": "Meeting id"}}, ["meeting_id"],
            ),
            "create_meeting": _operation(
                "create_meeting", "Create Meeting", "Schedule a meeting.",
                {
                    "user_id": {"type": "string", "title": "User id or email"},
                    "topic": {"type": "string", "title": "Topic"},
                    "start_time": {"type": "string", "title": "Start ISO time (optional)"},
                    "duration_min": {"type": "integer", "title": "Duration minutes"},
                },
                ["topic"], retryable=False, idempotency="non_idempotent",
            ),
            "delete_meeting": _operation(
                "delete_meeting", "Delete Meeting", "Delete a meeting.",
                {"meeting_id": {"type": "string", "title": "Meeting id"}}, ["meeting_id"],
                retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "zoom": CredentialTypeV1(
                type_key="zoom",
                display_name="Zoom",
                description="Zoom Server-to-Server OAuth access token (refreshed by your token flow; stored encrypted).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"access_token": {"type": "string", "title": "Access token"}},
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_meetings", "get_meeting", "create_meeting", "delete_meeting"], "auth": "Bearer"},
        icon="zoom",
    )
