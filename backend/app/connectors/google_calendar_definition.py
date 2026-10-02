"""Google Calendar connector definition (Phase 37).

Versioned ConnectorDefinitionV1; events CRUD over Calendar v3:

1. list_events - List Events (time-window)
2. get_event   - Get Event
3. create_event- Create Event
4. update_event- Update Event
5. delete_event- Delete Event

Every operation requires the 'google_calendar' credential type.
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

GOOGLE_CONNECTOR_KEY = "google_calendar"
GOOGLE_CONNECTOR_VERSION = "1.0.0"
GOOGLE_OPERATION_VERSION = "1.0.0"

_TIMEOUT_PROP = {
    "type": "number",
    "title": "Timeout (seconds)",
    "default": 30,
    "minimum": 1,
}

_CALENDAR_ID = {
    "type": "string",
    "title": "Calendar id",
    "default": "primary",
    "description": "'primary' or a specific calendar id.",
}
_EVENT_ID = {"type": "string", "title": "Event id"}
_EVENT = {
    "type": "object",
    "title": "Event",
    "description": 'Calendar v3 event resource, e.g. {"summary": "Sync", "start": {...}, "end": {...}}.',
}


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    output_schema: dict,
    *,
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=GOOGLE_CONNECTOR_KEY,
        connector_version=GOOGLE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=GOOGLE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="google_calendar",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["google_calendar"],
    )


def _google_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "list_events": _operation(
            "list_events", "List Events", "List events in a time window (ordered by start).",
            {
                "calendar_id": _CALENDAR_ID,
                "time_min": {"type": "string", "title": "From (RFC3339, optional)"},
                "time_max": {"type": "string", "title": "Until (RFC3339, optional)"},
                "max_results": {"type": "integer", "title": "Max results", "default": 25, "minimum": 1, "maximum": 250},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            [],
            {"type": "object", "properties": {"events": {"type": "array"}, "count": {"type": "integer"}}},
            retryable=True,
        ),
        "get_event": _operation(
            "get_event", "Get Event", "Fetch a single event by id.",
            {"calendar_id": _CALENDAR_ID, "event_id": _EVENT_ID, "timeout_seconds": _TIMEOUT_PROP},
            ["event_id"],
            {"type": "object", "properties": {"event": {"type": "object"}}},
            retryable=True,
        ),
        "create_event": _operation(
            "create_event", "Create Event", "Create an event and return its id.",
            {"calendar_id": _CALENDAR_ID, "event": _EVENT, "timeout_seconds": _TIMEOUT_PROP},
            ["event"],
            {"type": "object", "properties": {"id": {"type": "string"}, "success": {"type": "boolean"}}},
            idempotency="non_idempotent",
        ),
        "update_event": _operation(
            "update_event", "Update Event", "Patch fields of an existing event.",
            {"calendar_id": _CALENDAR_ID, "event_id": _EVENT_ID, "event": _EVENT, "timeout_seconds": _TIMEOUT_PROP},
            ["event_id", "event"],
            {"type": "object", "properties": {"id": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=True,
        ),
        "delete_event": _operation(
            "delete_event", "Delete Event", "Delete an event by id.",
            {"calendar_id": _CALENDAR_ID, "event_id": _EVENT_ID, "timeout_seconds": _TIMEOUT_PROP},
            ["event_id"],
            {"type": "object", "properties": {"id": {"type": "string"}, "deleted": {"type": "boolean"}}},
            retryable=True,
        ),
    }


def _google_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "google_calendar": CredentialTypeV1(
            type_key="google_calendar",
            display_name="Google Calendar",
            description=(
                "Google Calendar connection via 'Connect Google Calendar': the end user "
                "authorizes with their own Google account and the refresh token is stored "
                "encrypted; access tokens are minted server-side on demand."
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
    }


def build_google_calendar_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=GOOGLE_CONNECTOR_KEY,
        display_name="Google Calendar",
        description="Google Calendar connector: list, get, create, update and delete events via Calendar API v3.",
        category="productivity",
        connector_version=GOOGLE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_google_operations(),
        triggers={},
        credential_types=_google_credential_type(),
        metadata={
            "initial_operations": ["list_events", "get_event", "create_event", "update_event", "delete_event"],
            "auth": "OAuth2 authorization-code (Connect Google Calendar), offline access",
        },
        icon="google_calendar",
    )
