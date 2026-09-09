"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Open-Meteo Flood Forecast API
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)


CONNECTOR_KEY = "open_meteo_flood"
CONNECTOR_VERSION = "1.0.0"
OPERATION_VERSION = "1.0.0"


def _operation(key, display_name, description, input_schema, *, retryable=True, idempotency='idempotent'):
    return ConnectorOperationV1(
        connector_key=CONNECTOR_KEY,
        connector_version=CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema=input_schema,
        output_schema={"type": "object", "properties": {}},
        credential_require=None,
        retryable=retryable,
        idempotency=idempotency,
        node_types=[CONNECTOR_KEY],
    )


def _operations():
    return {
        "get_v1_flood": _operation("get_v1_flood", "Daily river discharge forecast", "GET /v1/flood", {"type": "object", "properties": {"latitude": {"type": "string", "title": "latitude"}, "longitude": {"type": "string", "title": "longitude"}, "daily": {"type": "string", "title": "daily"}, "timeformat": {"type": "string", "title": "timeformat"}, "timezone": {"type": "string", "title": "timezone"}, "past_days": {"type": "string", "title": "past_days"}, "forecast_days": {"type": "string", "title": "forecast_days"}, "start_date": {"type": "string", "title": "start_date"}, "end_date": {"type": "string", "title": "end_date"}, "ensemble": {"type": "string", "title": "ensemble"}, "cell_selection": {"type": "string", "title": "cell_selection"}, "models": {"type": "string", "title": "models"}, "apikey": {"type": "string", "title": "apikey"}}, "required": ["latitude", "longitude"]}),
    }


def build_open_meteo_flood_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="Open-Meteo flood",
        description="Generated from Open-Meteo Flood Forecast API.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "Open-Meteo Flood Forecast API"},
        icon="🧲",
    )
