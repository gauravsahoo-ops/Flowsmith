"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Open-Meteo Weather Forecast API
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
)


CONNECTOR_KEY = "open_meteo"
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
        "get_v1_forecast": _operation("get_v1_forecast", "Open-Meteo Weather Forecast API", "GET /v1/forecast", {"type": "object", "properties": {"latitude": {"type": "string", "title": "latitude"}, "longitude": {"type": "string", "title": "longitude"}, "hourly": {"type": "string", "title": "hourly"}, "daily": {"type": "string", "title": "daily"}, "current": {"type": "string", "title": "current"}, "minutely_15": {"type": "string", "title": "minutely_15"}, "elevation": {"type": "string", "title": "elevation"}, "temperature_unit": {"type": "string", "title": "temperature_unit"}, "wind_speed_unit": {"type": "string", "title": "wind_speed_unit"}, "precipitation_unit": {"type": "string", "title": "precipitation_unit"}, "timeformat": {"type": "string", "title": "timeformat"}, "timezone": {"type": "string", "title": "timezone"}, "past_days": {"type": "string", "title": "past_days"}, "forecast_days": {"type": "string", "title": "forecast_days"}, "past_hours": {"type": "string", "title": "past_hours"}, "forecast_hours": {"type": "string", "title": "forecast_hours"}, "start_date": {"type": "string", "title": "start_date"}, "end_date": {"type": "string", "title": "end_date"}, "tilt": {"type": "string", "title": "tilt"}, "azimuth": {"type": "string", "title": "azimuth"}, "cell_selection": {"type": "string", "title": "cell_selection"}, "apikey": {"type": "string", "title": "apikey"}, "models": {"type": "string", "title": "models"}}, "required": ["latitude", "longitude"]}),
    }


def build_open_meteo_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="Open-Meteo",
        description="Generated from Open-Meteo Weather Forecast API.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "Open-Meteo Weather Forecast API"},
        icon="🧲",
    )
