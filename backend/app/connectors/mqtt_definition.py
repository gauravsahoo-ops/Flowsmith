"""MQTT connector definition.

Clean-room versioned ConnectorDefinitionV1 for MQTT IoT message protocol.
Supports publishing and consuming messages with configurable QoS and retain flags.
"""

from __future__ import annotations

from typing import Any, Dict
from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

MQTT_CONNECTOR_KEY = "mqtt"
MQTT_CONNECTOR_VERSION = "1.0.0"
MQTT_OPERATION_VERSION = "1.0.0"


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
        connector_key=MQTT_CONNECTOR_KEY,
        connector_version=MQTT_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=MQTT_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="mqtt",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["mqtt"],
    )


def _mqtt_operations() -> Dict[str, ConnectorOperationV1]:
    topic_prop = {
        "type": "string",
        "title": "Topic",
        "default": "",
        "description": "MQTT topic (e.g. sensors/temperature).",
    }
    payload_prop = {
        "type": "object",
        "title": "Message Payload",
        "default": {},
        "description": "JSON object or string payload to publish.",
    }
    qos_prop = {
        "type": "integer",
        "title": "Quality of Service (QoS)",
        "enum": [0, 1, 2],
        "default": 0,
        "description": "MQTT QoS level: 0 (at most once), 1 (at least once), 2 (exactly once).",
    }
    retain_prop = {
        "type": "boolean",
        "title": "Retain Message",
        "default": False,
        "description": "Whether broker should retain this message.",
    }

    pub_out = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["published"]},
            "topic": {"type": "string"},
            "qos": {"type": "integer"},
            "retained": {"type": "boolean"},
        },
        "required": ["status", "topic"],
    }

    sub_out = {
        "type": "object",
        "properties": {
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "payload": {"description": "Message payload."},
                        "qos": {"type": "integer"},
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
            "Publish an MQTT message to a topic.",
            {"topic": topic_prop, "payload": payload_prop, "qos": qos_prop, "retain": retain_prop},
            ["topic"],
            output_schema=pub_out,
            retryable=True,
            idempotency="non_idempotent",
        ),
        "consume": _operation(
            "consume",
            "Subscribe & Receive",
            "Fetch recent messages from an MQTT topic.",
            {"topic": topic_prop, "qos": qos_prop, "max_messages": {"type": "integer", "default": 10}},
            ["topic"],
            output_schema=sub_out,
            retryable=False,
            idempotency="idempotent",
        ),
    }


def _mqtt_credential_types() -> Dict[str, CredentialTypeV1]:
    return {
        "mqtt": CredentialTypeV1(
            type_key="mqtt",
            display_name="MQTT Broker Connection",
            description="Connection parameters and credentials for MQTT broker.",
            secret_fields=["password"],
            validation_schema={
                "type": "object",
                "properties": {
                    "broker_url": {"type": "string", "title": "Broker URL", "description": "e.g. broker.emqx.io or mqtt://host:1883"},
                    "port": {"type": "integer", "title": "Port", "default": 1883},
                    "client_id": {"type": "string", "title": "Client ID", "default": ""},
                    "username": {"type": "string", "title": "Username", "default": ""},
                    "password": {"type": "string", "title": "Password", "default": ""},
                    "use_tls": {"type": "boolean", "title": "Use TLS / SSL", "default": False},
                },
                "required": ["broker_url"],
            },
            encryption_required=True,
        )
    }


def build_mqtt_definition() -> ConnectorDefinitionV1:
    """Construct version 1.0.0 MQTT connector definition."""
    return ConnectorDefinitionV1(
        connector_key=MQTT_CONNECTOR_KEY,
        display_name="MQTT",
        description="Publish and subscribe to IoT messages via MQTT brokers.",
        category="developer",
        connector_version=MQTT_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_mqtt_operations(),
        triggers={},
        credential_types=_mqtt_credential_types(),
        metadata={
            "protocol": "MQTT v3.1.1 / v5.0",
        },
    )
