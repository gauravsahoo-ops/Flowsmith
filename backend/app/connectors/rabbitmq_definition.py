"""RabbitMQ / AMQP connector definition.

Clean-room versioned ConnectorDefinitionV1 for RabbitMQ message broker.
Supports publishing messages, consuming messages, queue declaration, and exchange routing.
"""

from __future__ import annotations

from typing import Any, Dict
from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

RABBITMQ_CONNECTOR_KEY = "rabbitmq"
RABBITMQ_CONNECTOR_VERSION = "1.0.0"
RABBITMQ_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: Dict[str, Any],
    required: list[str],
    *,
    output_schema: Dict[str, Any],
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=RABBITMQ_CONNECTOR_KEY,
        connector_version=RABBITMQ_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=RABBITMQ_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="rabbitmq",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["rabbitmq"],
    )


def _rabbitmq_operations() -> Dict[str, ConnectorOperationV1]:
    exchange_prop = {
        "type": "string",
        "title": "Exchange",
        "default": "",
        "description": "AMQP exchange name (leave empty for default exchange).",
    }
    routing_key_prop = {
        "type": "string",
        "title": "Routing Key / Queue",
        "default": "",
        "description": "Routing key or queue name to publish message to.",
    }
    payload_prop = {
        "type": "object",
        "title": "Message Payload",
        "default": {},
        "description": "JSON object or message data to publish.",
    }
    queue_prop = {
        "type": "string",
        "title": "Queue Name",
        "default": "",
        "description": "Queue name to consume from or declare.",
    }
    headers_prop = {
        "type": "object",
        "title": "Headers / Properties",
        "default": {},
        "description": "AMQP message headers and delivery properties.",
    }

    msg_out = {
        "type": "object",
        "properties": {
            "output": {
                "type": "array",
                "description": "One entry per delivery (or a status entry when nothing was received).",
                "items": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["published", "declared", "empty"]},
                        "routing_key": {"type": "string"},
                        "queue": {"type": "string"},
                        "payload": {"description": "Decoded message body (JSON when possible, else text)."},
                        "headers": {"type": "object", "description": "AMQP delivery headers."},
                    },
                },
            },
        },
        "required": ["output"],
    }

    return {
        "publish": _operation(
            "publish",
            "Publish Message",
            "Publish a message to an AMQP exchange or queue.",
            {
                "exchange": exchange_prop,
                "routing_key": routing_key_prop,
                "payload": payload_prop,
                "headers": headers_prop,
            },
            required=["routing_key"],
            output_schema=msg_out,
            idempotency="non_idempotent",
            retryable=True,
        ),
        "consume": _operation(
            "consume",
            "Consume Messages",
            "Read available messages from a specified RabbitMQ queue.",
            {
                "queue": queue_prop,
                "max_messages": {
                    "type": "integer",
                    "title": "Max Messages",
                    "default": 10,
                    "description": "Maximum number of messages to consume.",
                },
            },
            required=["queue"],
            output_schema=msg_out,
            idempotency="non_idempotent",
            retryable=False,
        ),
        "declare_queue": _operation(
            "declare_queue",
            "Declare Queue",
            "Declare an AMQP queue if it does not already exist.",
            {
                "queue": queue_prop,
                "durable": {"type": "boolean", "title": "Durable", "default": True},
                "auto_delete": {"type": "boolean", "title": "Auto Delete", "default": False},
            },
            required=["queue"],
            output_schema=msg_out,
            idempotency="idempotent",
            retryable=True,
        ),
    }


def _rabbitmq_credentials() -> Dict[str, CredentialTypeV1]:
    return {
        "rabbitmq": CredentialTypeV1(
            type_key="rabbitmq",
            display_name="RabbitMQ Credentials",
            description="Connection settings for RabbitMQ AMQP broker.",
            secret_fields=["password"],
            validation_schema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "title": "Host", "default": "localhost"},
                    "port": {"type": "integer", "title": "Port", "default": 5672},
                    "vhost": {"type": "string", "title": "Virtual Host", "default": "/"},
                    "username": {"type": "string", "title": "Username", "default": "guest"},
                    "password": {"type": "string", "title": "Password", "format": "password", "default": "guest"},
                    "ssl": {"type": "boolean", "title": "Use SSL/TLS", "default": False},
                },
                "required": ["host", "username", "password"],
            },
        )
    }


def build_rabbitmq_definition() -> ConnectorDefinitionV1:
    """Build the active ConnectorDefinitionV1 for RabbitMQ."""
    return ConnectorDefinitionV1(
        connector_key=RABBITMQ_CONNECTOR_KEY,
        display_name="RabbitMQ",
        description="Publish and consume messages from RabbitMQ and AMQP brokers.",
        category="api",
        connector_version=RABBITMQ_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_rabbitmq_operations(),
        triggers={},
        credential_types=_rabbitmq_credentials(),
        icon="server",
    )
