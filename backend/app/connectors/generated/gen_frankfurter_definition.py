"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Frankfurter API
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
)


CONNECTOR_KEY = "frankfurter"
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
        "get_currencies": _operation("get_currencies", "Get available currencies", "GET /currencies", {"type": "object", "properties": {}, "required": []}),
        "get_date": _operation("get_date", "Get rates for a past date", "GET /{date}", {"type": "object", "properties": {"date": {"type": "string", "title": "date"}}, "required": ["date"]}),
        "get_latest": _operation("get_latest", "Get the latest rates", "GET /latest", {"type": "object", "properties": {}, "required": []}),
        "get_start_date": _operation("get_start_date", "Get rates for a time period", "GET /{start_date}..", {"type": "object", "properties": {"start_date": {"type": "string", "title": "start_date"}}, "required": ["start_date"]}),
        "get_start_date_end_date": _operation("get_start_date_end_date", "Get rates for a time period", "GET /{start_date}..{end_date}", {"type": "object", "properties": {"start_date": {"type": "string", "title": "start_date"}, "end_date": {"type": "string", "title": "end_date"}}, "required": ["start_date", "end_date"]}),
    }


def build_frankfurter_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="Frankfurter FX",
        description="Generated from Frankfurter API.",
        category="finance",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "Frankfurter API"},
        icon="🧲",
    )
