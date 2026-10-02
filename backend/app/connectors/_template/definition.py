"""TEMPLATE definition — pair with my_connector.py and rename."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

KEY = "my_connector"
VERSION = "1.0.0"


def build_my_connector_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=KEY,
        display_name="My Connector",
        description="TEMPLATE: describe the integration.",
        category="api",
        connector_version=VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "fetch": ConnectorOperationV1(
                connector_key=KEY,
                connector_version=VERSION,
                operation_key="fetch",
                operation_version=VERSION,
                display_name="Fetch",
                description="Fetch a resource by id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "resource_id": {"type": "string", "title": "Resource id"},
                        "timeout_seconds": {"type": "number", "default": 30, "minimum": 1},
                    },
                    "required": ["resource_id"],
                },
                output_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "normalized": {"type": "boolean"}},
                },
                credential_require="my_connector",
                retryable=True,
                idempotency="idempotent",
                node_types=["my_connector"],
            ),
        },
        triggers={},
        credential_types={
            "my_connector": CredentialTypeV1(
                type_key="my_connector",
                display_name="My Connector",
                description="API key credential (add secret_fields for secrets).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API key"},
                    },
                },
                encryption_required=True,
            )
        },
        metadata={"auth": "Bearer api_key"},
        icon="connector",
    )
