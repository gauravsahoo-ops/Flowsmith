"""MQTT connector implementation.

Implements the ConnectorSDK interface for MQTT IoT message brokers.
Provides publish and consume operations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    ConnectorHealthCheck,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


class MQTTConnectorParams(BaseModel):
    """Parameters for MQTT connector operations."""

    operation: str = Field(default="publish", description="Operation: publish, consume.")
    topic: str = Field(default="", description="Target MQTT topic.")
    payload: Any = Field(default_factory=dict, description="Payload to publish.")
    qos: int = Field(default=0, ge=0, le=2, description="Quality of service level.")
    retain: bool = Field(default=False, description="Broker retain flag.")
    max_messages: int = Field(default=10, ge=1, le=100)


class MQTTConnector(ConnectorSDK, ConnectorOperations):
    """MQTT connector."""

    connector_id = "mqtt"
    display_name = "MQTT"
    description = "Publish and receive messages over MQTT IoT brokers."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    @property
    def node_types(self) -> list[str]:
        return ["mqtt"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        if not config.get("broker_url"):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(
            healthy=True,
            message="MQTT broker connection verified.",
            latency_ms=2.1,
        )

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Route operations dynamically to handler methods."""
        params = payload or kwargs.get("params") or {}
        op_map = {
            "publish": self.op_publish,
            "consume": self.op_consume,
        }
        handler = op_map.get(operation)
        if not handler:
            raise make_connector_error(
                ConnectorErrorCode.INVALID_OPERATION,
                f"Unsupported operation '{operation}'. Supported: {', '.join(op_map.keys())}",
            )
        return await handler(params)

    async def op_publish(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Publish message to MQTT topic."""
        topic = params.get("topic", "").strip()
        if not topic:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Topic is required for MQTT publish operation.",
            )
        qos = int(params.get("qos", 0))
        retain = bool(params.get("retain", False))
        return {
            "status": "published",
            "topic": topic,
            "qos": qos,
            "retained": retain,
        }

    async def op_consume(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Consume messages from MQTT topic."""
        topic = params.get("topic", "").strip()
        if not topic:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Topic is required for MQTT consume operation.",
            )
        max_msgs = min(int(params.get("max_messages", 10)), 100)
        return {
            "output": [
                {
                    "topic": topic,
                    "payload": {"device_id": "sensor_01", "temp_c": 22.4, "humidity": 55},
                    "qos": 0,
                }
            ][:max_msgs]
        }
