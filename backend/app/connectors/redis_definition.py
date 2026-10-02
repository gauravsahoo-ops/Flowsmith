"""Redis connector definition (Phase 11 business connectors).

1. get     - read a key
2. set     - write a key (optional TTL)
3. delete  - remove a key
4. incr    - atomic counter increment
5. publish - publish to a channel
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

REDIS_CONNECTOR_KEY = "redis"
REDIS_CONNECTOR_VERSION = "1.0.0"
REDIS_OPERATION_VERSION = "1.0.0"


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
        connector_key=REDIS_CONNECTOR_KEY,
        connector_version=REDIS_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=REDIS_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="redis",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["redis"],
    )


def _redis_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "get": _operation(
            "get", "Get", "Read a string key.",
            {"key": {"type": "string", "title": "Key"}},
            ["key"],
            {
                "type": "object",
                "properties": {"found": {"type": "boolean"}, "value": {"type": ["string", "null"]}},
            },
            retryable=True,
        ),
        "set": _operation(
            "set", "Set", "Write a string key (optional expiry).",
            {
                "key": {"type": "string", "title": "Key"},
                "value": {"type": "string", "title": "Value"},
                "ttl_seconds": {"type": "integer", "title": "TTL seconds", "default": 0, "minimum": 0},
            },
            ["key", "value"],
            {"type": "object", "properties": {"set": {"type": "boolean"}}},
            retryable=True,
            idempotency="conditionally_idempotent",
        ),
        "delete": _operation(
            "delete", "Delete", "Remove a key.",
            {"key": {"type": "string", "title": "Key"}},
            ["key"],
            {"type": "object", "properties": {"deleted": {"type": "integer"}}},
            retryable=True,
        ),
        "incr": _operation(
            "incr", "Increment", "Increment an integer counter by an amount.",
            {
                "key": {"type": "string", "title": "Key"},
                "amount": {"type": "integer", "title": "Amount", "default": 1},
            },
            ["key"],
            {"type": "object", "properties": {"value": {"type": "integer"}}},
            retryable=True,
            idempotency="non_idempotent",
        ),
        "publish": _operation(
            "publish", "Publish", "Publish a message on a channel.",
            {
                "channel": {"type": "string", "title": "Channel"},
                "message": {"type": "string", "title": "Message"},
            },
            ["channel", "message"],
            {"type": "object", "properties": {"receivers": {"type": "integer"}}},
            retryable=True,
            idempotency="non_idempotent",
        ),
    }


def _redis_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "redis": CredentialTypeV1(
            type_key="redis",
            display_name="Redis",
            description=(
                "Redis connection URI (redis:// or rediss://). Leave empty to use "
                "the server-wide REDIS_URL."
            ),
            secret_fields=["uri"],
            validation_schema={
                "type": "object",
                "properties": {
                    "uri": {"type": "string", "title": "Connection URI (optional)"},
                    "name": {"type": "string", "title": "Label (display)"},
                },
            },
            encryption_required=True,
        )
    }


def build_redis_definition() -> ConnectorDefinitionV1:
    """Build the Redis connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=REDIS_CONNECTOR_KEY,
        display_name="Redis",
        description="Read/write keys and publish messages in Redis.",
        category="database",
        connector_version=REDIS_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_redis_operations(),
        triggers={},
        credential_types=_redis_credential_type(),
        metadata={
            "initial_operations": ["get", "set", "delete", "incr", "publish"],
            "auth": "connection URI (falls back to REDIS_URL)",
        },
        icon="redis",
    )
