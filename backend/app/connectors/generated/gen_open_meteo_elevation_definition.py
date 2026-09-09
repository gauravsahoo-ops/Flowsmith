"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Open-Meteo Elevation API
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)


CONNECTOR_KEY = "open_meteo_elevation"
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
        "get_v1_elevation": _operation("get_v1_elevation", "Get terrain elevation for coordinates", "GET /v1/elevation", {"type": "object", "properties": {"latitude": {"type": "string", "title": "latitude"}, "longitude": {"type": "string", "title": "longitude"}, "apikey": {"type": "string", "title": "apikey"}}, "required": ["latitude", "longitude"]}),
    }


def build_open_meteo_elevation_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="Open-Meteo Elevation",
        description="Generated from Open-Meteo Elevation API.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "Open-Meteo Elevation API"},
        icon="🧲",
    )
