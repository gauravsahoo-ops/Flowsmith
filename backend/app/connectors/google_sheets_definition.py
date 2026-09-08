"""Google Sheets connector definition (Phase 39): read/append/update."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

KEY = "google_sheets"
VERSION = "1.0.0"


def _operation(key, display, description, props, required, output, *, retryable=False, idempotency="idempotent"):
    return ConnectorOperationV1(
        connector_key=KEY, connector_version=VERSION,
        operation_key=key, operation_version=VERSION,
        display_name=display, description=description,
        input_schema={"type": "object", "properties": props, "required": required},
        output_schema=output,
        credential_require="google_sheets",
        retryable=retryable, idempotency=idempotency,
        node_types=["google_sheets"],
    )


_SSID = {"type": "string", "title": "Spreadsheet id", "description": "From the sheet URL: /d/<id>/edit"}
_RANGE = {"type": "string", "title": "Range (A1)", "default": "Sheet1!A1:Z100"}
_VALUES_ROW = {"type": "array", "title": "Row values", "items": {}}
_VALUES_ROWS = {"type": "array", "title": "Rows", "items": {"type": "array"}}


def build_google_sheets_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=KEY,
        display_name="Google Sheets",
        description="Read, append and update rows in Google Sheets via the v4 values API.",
        category="api",
        connector_version=VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "read": _operation(
                "read", "Read Rows", "Read values from an A1 range.",
                {"spreadsheet_id": _SSID, "range": _RANGE, "timeout_seconds": {"type": "number", "default": 30}},
                ["spreadsheet_id"],
                {"type": "object", "properties": {"rows": {"type": "array"}, "count": {"type": "integer"}}},
                retryable=True,
            ),
            "append": _operation(
                "append", "Append Row", "Append one row after the last data row.",
                {"spreadsheet_id": _SSID, "range": _RANGE, "values": _VALUES_ROW,
                 "timeout_seconds": {"type": "number", "default": 30}},
                ["spreadsheet_id", "values"],
                {"type": "object", "properties": {"appended": {"type": "boolean"}, "updated_cells": {"type": "integer"}}},
                idempotency="non_idempotent",
            ),
            "update": _operation(
                "update", "Update Range", "Overwrite a range with rows.",
                {"spreadsheet_id": _SSID, "range": _RANGE, "values": _VALUES_ROWS,
                 "timeout_seconds": {"type": "number", "default": 30}},
                ["spreadsheet_id", "values"],
                {"type": "object", "properties": {"success": {"type": "boolean"}, "updated_cells": {"type": "integer"}}},
                retryable=True,
            ),
        },
        triggers={},
        credential_types={
            "google_sheets": CredentialTypeV1(
                type_key="google_sheets",
                display_name="Google Sheets",
                description=(
                    "Google Sheets connection via 'Connect Google Sheets': refresh token stored "
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
        metadata={"initial_operations": ["read", "append", "update"], "auth": "OAuth2 offline access"},
        icon="📗",
    )
