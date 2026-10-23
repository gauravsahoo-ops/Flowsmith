"""RabbitMQ connector implementation.

Implements the ConnectorSDK interface for RabbitMQ / AMQP message brokers.
Provides publish, consume, and queue declaration operations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
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


class RabbitMQConnectorParams(BaseModel):
    """Parameters for RabbitMQ connector operations."""

    operation: str = Field(default="publish", description="Operation: publish, consume, declare_queue.")
    exchange: str = Field(default="", description="Exchange name.")
    routing_key: str = Field(default="", description="Routing key or target queue.")
    payload: Any = Field(default_factory=dict, description="Message data to publish.")
    headers: Dict[str, Any] = Field(default_factory=dict, description="AMQP headers.")
    queue: str = Field(default="", description="Queue name for consume or declaration.")
    max_messages: int = Field(default=10, ge=1, le=1000)
    durable: bool = Field(default=True)
    auto_delete: bool = Field(default=False)


class RabbitMQConnector(ConnectorSDK, ConnectorOperations):
    """RabbitMQ / AMQP message broker connector."""

    connector_id = "rabbitmq"
    display_name = "RabbitMQ"
    description = "Publish and consume messages from RabbitMQ / AMQP."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    @property
    def node_types(self) -> list[str]:
        return ["rabbitmq"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        if not ("host" in config and "username" in config):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(healthy=True, message="RabbitMQ connector operational.")

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a RabbitMQ operation."""
        try:
            params = RabbitMQConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid RabbitMQ parameters: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("rabbitmq") or {}

        raw_op = payload.get("operation") or operation
        if not raw_op or raw_op == "execute":
            raw_op = payload.get("operation") or params.operation or "publish"
        op_name = raw_op.lower().strip()

        if op_name not in ("publish", "consume", "declare_queue"):
            raise make_connector_error(
                ConnectorErrorCode.INVALID_OPERATION,
                f"Unknown RabbitMQ operation '{op_name}'.",
                retryable=False,
            )

        host = (creds.get("host") or "").strip()
        if not host:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "RabbitMQ credential has no 'host'. Configure an AMQP broker endpoint "
                "(e.g. rabbit.example.com:5672) before running this operation.",
                retryable=False,
            )

        # Real AMQP round-trip. There is no simulated branch: a publish that never
        # reached the broker must raise rather than report 'published'.
        try:
            import aio_pika  # type: ignore
        except ImportError as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                "The 'aio-pika' driver is not installed on this FlowSmith instance, so the "
                "RabbitMQ operation cannot be executed. Install it (pip install aio-pika) "
                "or switch the node to a supported messaging connector.",
                retryable=False,
            ) from exc

        try:
            amqp_url = (
                f"amqp://{creds.get('username', 'guest')}:{creds.get('password', 'guest')}@"
                f"{host}:{creds.get('port', 5672)}/{creds.get('vhost', '').lstrip('/')}"
            )
            connection = await aio_pika.connect_robust(amqp_url)
            async with connection:
                channel = await connection.channel()
                if op_name == "publish":
                    exchange = await channel.get_exchange(params.exchange) if params.exchange else channel.default_exchange
                    body = json.dumps(params.payload).encode() if isinstance(params.payload, (dict, list)) else str(params.payload).encode()
                    msg = aio_pika.Message(body=body, headers=params.headers)
                    await exchange.publish(msg, routing_key=params.routing_key)
                    return {"output": [{"status": "published", "routing_key": params.routing_key}]}

                elif op_name == "declare_queue":
                    q = await channel.declare_queue(params.queue, durable=params.durable, auto_delete=params.auto_delete)
                    return {"output": [{"status": "declared", "queue": q.name}]}

                elif op_name == "consume":
                    q = await channel.get_queue(params.queue)
                    items = []
                    for _ in range(params.max_messages):
                        msg = await q.get(fail=False)
                        if not msg:
                            break
                        async with msg.process():
                            try:
                                data = json.loads(msg.body.decode())
                            except Exception:
                                data = msg.body.decode()
                            items.append({"payload": data, "headers": dict(msg.headers or {})})
                    return {"output": items or [{"status": "empty", "queue": params.queue}]}

        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"RabbitMQ error: {exc}",
                retryable=True,
            ) from exc

        # Defensive: the allowed-operation check above should make this
        # unreachable, but the declared return type must hold on every path.
        raise make_connector_error(
            ConnectorErrorCode.INVALID_OPERATION,
            f"Unhandled RabbitMQ operation '{op_name}'.",
            retryable=False,
        )
