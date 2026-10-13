"""Apache Kafka connector definition.

Clean-room versioned ConnectorDefinitionV1 for Apache Kafka distributed streaming.
Supports publishing messages, consuming messages, and topic inspection.
"""

from __future__ import annotations

from typing import Any, Dict
from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

KAFKA_CONNECTOR_KEY = "kafka"
KAFKA_CONNECTOR_VERSION = "1.0.0"
KAFKA_OPERATION_VERSION = "1.0.0"


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
        connector_key=KAFKA_CONNECTOR_KEY,
        connector_version=KAFKA_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=KAFKA_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="kafka",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["kafka"],
    )


def _kafka_operations() -> Dict[str, ConnectorOperationV1]:
    topic_prop = {
        "type": "string",
        "title": "Topic",
        "default": "",
        "description": "Kafka topic name.",
    }
    key_prop = {
        "type": "string",
        "title": "Message Key",
        "default": "",
        "description": "Partitioning key for message routing.",
    }
    payload_prop = {
        "type": "object",
        "title": "Message Payload",
        "default": {},
        "description": "JSON object or message data to publish.",
    }
    headers_prop = {
        "type": "object",
        "title": "Headers",
        "default": {},
        "description": "Message metadata headers.",
    }
    group_prop = {
        "type": "string",
        "title": "Consumer Group",
        "default": "flowsmith-consumer",
        "description": "Kafka consumer group identifier.",
    }

    produce_out = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["published"]},
            "topic": {"type": "string"},
            "partition": {"type": "integer"},
            "offset": {"type": "integer"},
            "key": {"type": "string"},
            "timestamp": {"type": "number"},
        },
        "required": ["status", "topic"],
    }

    consume_out = {
        "type": "object",
        "properties": {
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "partition": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "key": {"type": "string"},
                        "value": {"description": "Decoded message payload."},
                        "headers": {"type": "object"},
                    },
                },
            },
        },
        "required": ["output"],
    }

    topics_out = {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["topics"],
    }

    return {
        "produce": _operation(
            "produce",
            "Produce Message",
            "Publish a message to an Apache Kafka topic.",
            {
                "topic": topic_prop,
                "message_key": key_prop,
                "payload": payload_prop,
                "headers": headers_prop,
                "partition": {"type": "integer", "title": "Partition", "description": "Explicit partition number."},
            },
            ["topic"],
            output_schema=produce_out,
            retryable=True,
            idempotency="non_idempotent",
        ),
        "consume": _operation(
            "consume",
            "Consume Messages",
            "Fetch pending messages from a Kafka topic.",
            {
                "topic": topic_prop,
                "consumer_group": group_prop,
                "max_messages": {"type": "integer", "title": "Max Messages", "default": 10, "minimum": 1, "maximum": 500},
                "auto_commit": {"type": "boolean", "title": "Auto Commit", "default": True},
            },
            ["topic"],
            output_schema=consume_out,
            retryable=False,
            idempotency="idempotent",
        ),
        "list_topics": _operation(
            "list_topics",
            "List Topics",
            "Retrieve available topics in the Kafka cluster.",
            {},
            [],
            output_schema=topics_out,
            retryable=True,
            idempotency="idempotent",
        ),
    }


def _kafka_credential_types() -> Dict[str, CredentialTypeV1]:
    return {
        "kafka": CredentialTypeV1(
            type_key="kafka",
            display_name="Apache Kafka Cluster Connection",
            description="Connection parameters and security credentials for Apache Kafka cluster.",
            secret_fields=["sasl_password", "ssl_ca_pem", "api_key", "secret"],
            validation_schema={
                "type": "object",
                "properties": {
                    "bootstrap_servers": {
                        "type": "string",
                        "title": "Bootstrap Servers",
                        "description": "Comma-separated list of host:port broker endpoints.",
                    },
                    "client_id": {"type": "string", "title": "Client ID", "default": "flowsmith"},
                    "security_protocol": {
                        "type": "string",
                        "title": "Security Protocol",
                        "enum": ["PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"],
                        "default": "PLAINTEXT",
                    },
                    "sasl_mechanism": {
                        "type": "string",
                        "title": "SASL Mechanism",
                        "enum": ["PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"],
                        "default": "PLAIN",
                    },
                    "sasl_username": {"type": "string", "title": "SASL Username", "default": ""},
                    "sasl_password": {"type": "string", "title": "SASL Password", "default": ""},
                },
                "required": ["bootstrap_servers"],
            },
            encryption_required=True,
        )
    }


def build_kafka_definition() -> ConnectorDefinitionV1:
    """Construct version 1.0.0 Apache Kafka connector definition."""
    return ConnectorDefinitionV1(
        connector_key=KAFKA_CONNECTOR_KEY,
        display_name="Apache Kafka",
        description="Stream, publish, and consume messages with Apache Kafka clusters.",
        category="developer",
        connector_version=KAFKA_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_kafka_operations(),
        triggers={},
        credential_types=_kafka_credential_types(),
        metadata={
            "vendor": "Apache Software Foundation",
            "protocol": "Kafka Binary Protocol",
        },
    )
