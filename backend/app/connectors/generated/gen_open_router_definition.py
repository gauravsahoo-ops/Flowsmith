"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: OpenRouter
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)


CONNECTOR_KEY = "open_router"
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
        credential_require="open_router",
        retryable=retryable,
        idempotency=idempotency,
        node_types=[CONNECTOR_KEY],
    )


def _operations():
    return {
        "chatcompletion": _operation("chatcompletion", "Chat completion", "POST /chat/completions", {"type": "object", "properties": {"body": {"type": "object", "title": "Request body"}}, "required": []}),
        "keyinfo": _operation("keyinfo", "Key info and credits", "GET /auth/key", {"type": "object", "properties": {}, "required": []}),
        "listmodels": _operation("listmodels", "List available models", "GET /models", {"type": "object", "properties": {}, "required": []}),
    }


def build_open_router_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="OpenRouter",
        description="Generated from OpenRouter.",
        category="ai",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={
            "open_router": CredentialTypeV1(
                type_key="open_router",
                display_name="OpenRouter",
                description="Credentials for OpenRouter (imported).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"access_token": {"type": "string", "title": "Access token"}},
                    "required": ["access_token"],
                },
                encryption_required=True,
            ),
        },
        metadata={"source": "openapi-import", "api_title": "OpenRouter"},
        icon="🧲",
    )
