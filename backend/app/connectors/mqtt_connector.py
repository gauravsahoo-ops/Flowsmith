"""MQTT connector implementation.

Real MQTT publish/consume over a broker using paho-mqtt. The synchronous
paho client runs in a worker thread so the async engine is never blocked.
Paho is used instead of an asyncio-native client because it works
consistently on Windows and Linux.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict
from urllib.parse import urlparse

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
    timeout_seconds: float = Field(default=3.0, ge=0.5, le=30.0)


class MQTTConnector(ConnectorSDK, ConnectorOperations):
    """MQTT connector backed by a real broker connection."""

    connector_id = "mqtt"
    display_name = "MQTT"
    description = "Publish and receive messages over MQTT IoT brokers."
    category = ConnectorCategory.API
    version = "1.1.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> list[str]:
        return ["mqtt"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        if not str((config or {}).get("broker_url") or "").strip():
            return False
        self.credentials = dict(config or {})
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> ConnectorHealthCheck:
        try:
            await asyncio.to_thread(self._health_sync, self.credentials or {})
            return ConnectorHealthCheck(healthy=True, message="MQTT broker connection verified.")
        except Exception as exc:  # noqa: BLE001 - surface broker failure
            return ConnectorHealthCheck(healthy=False, message=f"MQTT connection failed: {exc}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raw = payload or kwargs.get("params") or {}
        try:
            params = MQTTConnectorParams.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid MQTT payload: {exc}", retryable=False,
            ) from exc

        creds = (
            ((context or {}).get("credentials") or {}).get("mqtt")
            or self.credentials
            or {}
        )
        op = (payload.get("operation") if isinstance(payload, dict) else None) or operation or params.operation
        op_name = str(op).lower().strip()
        if op_name == "publish":
            return await asyncio.to_thread(self._publish_sync, creds, params)
        if op_name == "consume":
            return await asyncio.to_thread(self._consume_sync, creds, params)
        raise make_connector_error(
            ConnectorErrorCode.INVALID_OPERATION,
            f"Unsupported MQTT operation '{op_name}'. Supported: publish, consume.",
        )

    # ------------------------------------------------------------------
    # paho-mqtt (worker thread)
    # ------------------------------------------------------------------

    @staticmethod
    def _broker(creds: Dict[str, Any]) -> tuple[str, int, bool]:
        raw = str((creds or {}).get("broker_url") or "").strip()
        if not raw:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "MQTT credential is missing 'broker_url'.",
                retryable=False,
            )
        if "://" not in raw:
            raw = f"mqtt://{raw}"
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        if not host:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid MQTT broker URL '{raw}'.",
                retryable=False,
            )
        tls = parsed.scheme.lower() in ("mqtts", "ssl", "tls") or bool((creds or {}).get("use_tls"))
        port = int((creds or {}).get("port") or parsed.port or (8883 if tls else 1883))
        return host, port, tls

    @staticmethod
    def _client(creds: Dict[str, Any], *, client_id: str = ""):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "MQTT connector requires 'paho-mqtt' on the server. Install it and restart the worker.",
                retryable=False,
            ) from exc

        host, port, tls = MQTTConnector._broker(creds)
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or str((creds or {}).get("client_id") or ""),
            protocol=mqtt.MQTTv311,
        )
        username = str((creds or {}).get("username") or "")
        password = str((creds or {}).get("password") or "")
        if username:
            client.username_pw_set(username, password or None)
        if tls:
            client.tls_set()
        client.connect(host, port, keepalive=10)
        return client

    def _health_sync(self, creds: Dict[str, Any]) -> None:
        client = self._client(creds)
        client.disconnect()

    def _publish_sync(self, creds: Dict[str, Any], params: MQTTConnectorParams) -> Dict[str, Any]:
        topic = params.topic.strip()
        if not topic:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "Topic is required for MQTT publish operation.", retryable=False,
            )
        body = (
            json.dumps(params.payload, ensure_ascii=False).encode("utf-8")
            if isinstance(params.payload, (dict, list))
            else str(params.payload).encode("utf-8")
        )
        client = self._client(creds)
        try:
            client.loop_start()
            info = client.publish(topic, payload=body, qos=params.qos, retain=params.retain)
            info.wait_for_publish(timeout=5.0)
            if not info.is_published():
                raise make_connector_error(
                    ConnectorErrorCode.PROVIDER_ERROR,
                    "MQTT broker did not acknowledge the publish.",
                    retryable=True,
                )
        finally:
            client.loop_stop()
            client.disconnect()
        return {
            "output": [{
                "status": "published",
                "topic": topic,
                "qos": params.qos,
                "retained": params.retain,
            }]
        }

    def _consume_sync(self, creds: Dict[str, Any], params: MQTTConnectorParams) -> Dict[str, Any]:
        topic = params.topic.strip()
        if not topic:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "Topic is required for MQTT consume operation.", retryable=False,
            )
        received: list[dict[str, Any]] = []

        def _on_message(_client: Any, _userdata: Any, message: Any) -> None:
            raw = bytes(message.payload)
            try:
                payload: Any = json.loads(raw.decode("utf-8"))
            except Exception:  # noqa: BLE001 - non-JSON payload is valid MQTT
                try:
                    payload = raw.decode("utf-8")
                except Exception:  # noqa: BLE001 - binary payload
                    payload = raw.hex()
            received.append({
                "topic": str(message.topic),
                "payload": payload,
                "qos": int(getattr(message, "qos", 0) or 0),
                "retained": bool(getattr(message, "retain", False)),
            })

        client = self._client(creds)
        client.on_message = _on_message
        try:
            client.loop_start()
            client.subscribe(topic, qos=params.qos)
            deadline = time.monotonic() + params.timeout_seconds
            while len(received) < params.max_messages and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            client.loop_stop()
            client.disconnect()
        return {"output": received}
