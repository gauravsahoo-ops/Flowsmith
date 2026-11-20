"""Apache Kafka connector implementation.

Real produce/consume/topic-list operations backed by ``aiokafka``. There is
no simulated success path: every operation either performs a broker
round-trip or raises a typed ConnectorError. Credentials arrive through
``context["credentials"]["kafka"]`` (or ``connect()`` for direct use).
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
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


class KafkaConnectorParams(BaseModel):
    """Parameters for Apache Kafka connector operations."""

    operation: str = Field(default="produce", description="Operation: produce, consume, list_topics.")
    topic: str = Field(default="", description="Target Kafka topic.")
    message_key: str = Field(default="", description="Optional message partition key.")
    payload: Any = Field(default_factory=dict, description="Message data to publish.")
    headers: Dict[str, Any] = Field(default_factory=dict, description="Message metadata headers.")
    partition: Optional[int] = Field(default=None, description="Explicit partition target.")
    consumer_group: str = Field(default="flowsmith-consumer", description="Consumer group name.")
    max_messages: int = Field(default=10, ge=1, le=500, description="Max messages to fetch.")
    auto_commit: bool = Field(default=True, description="Auto commit consumer offsets.")
    auto_offset_reset: str = Field(
        default="earliest",
        description="Where a new consumer group starts: earliest or latest.",
    )
    timeout_seconds: float = Field(default=10.0, ge=1, le=60)


def _require_aiokafka():
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
        from aiokafka.admin import AIOKafkaAdminClient
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Kafka support needs the 'aiokafka' package (pip install aiokafka).",
            retryable=False,
        ) from exc
    return AIOKafkaProducer, AIOKafkaConsumer, AIOKafkaAdminClient


def _serialize(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    try:
        return json.dumps(payload, default=str).encode("utf-8")
    except Exception as exc:
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Kafka payload is not JSON-serializable: {exc}",
            retryable=False,
        ) from exc


def _deserialize(value: bytes | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value.decode("utf-8"))
    except Exception:
        return value.decode("utf-8", errors="replace")


def _headers_to_dict(headers: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in headers or []:
        result[str(key)] = (
            value.decode("utf-8", errors="replace") if isinstance(value, (bytes, bytearray)) else value
        )
    return result


class KafkaConnector(ConnectorSDK, ConnectorOperations):
    """Apache Kafka connector backed by a real aiokafka client."""

    connector_id = "kafka"
    display_name = "Apache Kafka"
    description = "Publish, consume, and manage messages with Apache Kafka clusters."
    category = ConnectorCategory.API
    version = "1.1.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> list[str]:
        return ["kafka"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        if not str((config or {}).get("bootstrap_servers") or "").strip():
            return False
        self.credentials = dict(config or {})
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> ConnectorHealthCheck:
        started = time.perf_counter()
        try:
            topics = await self._list_topics(self.credentials or {}, timeout=5.0)
            return ConnectorHealthCheck(
                healthy=True,
                message=f"Kafka broker reachable ({len(topics)} topic(s)).",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception as exc:  # noqa: BLE001 - surface broker failure
            return ConnectorHealthCheck(healthy=False, message=f"Kafka connection failed: {exc}")

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
            params = KafkaConnectorParams.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid Kafka payload: {exc}",
                retryable=False,
            ) from exc

        creds = (
            ((context or {}).get("credentials") or {}).get("kafka")
            or self.credentials
            or {}
        )
        op = (raw.get("operation") if isinstance(raw, dict) else None) or operation or params.operation
        op_name = str(op).lower().strip()

        if op_name == "produce":
            return await self._produce(creds, params)
        if op_name == "consume":
            return await self._consume(creds, params)
        if op_name == "list_topics":
            topics = await self._list_topics(creds, timeout=params.timeout_seconds)
            return {"topics": topics, "count": len(topics)}
        raise make_connector_error(
            ConnectorErrorCode.INVALID_OPERATION,
            f"Unsupported Kafka operation '{op_name}'. Supported: produce, consume, list_topics.",
        )

    # Back-compat wrappers for callers of the previous handler names.
    async def op_produce(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = KafkaConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("kafka") or self.credentials or {}
        return await self._produce(creds, parsed)

    async def op_consume(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = KafkaConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("kafka") or self.credentials or {}
        return await self._consume(creds, parsed)

    async def op_list_topics(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = KafkaConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("kafka") or self.credentials or {}
        topics = await self._list_topics(creds, timeout=parsed.timeout_seconds)
        return {"topics": topics, "count": len(topics)}

    # ------------------------------------------------------------------
    # aiokafka client helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _client_kwargs(creds: Dict[str, Any]) -> Dict[str, Any]:
        bootstrap = str((creds or {}).get("bootstrap_servers") or "").strip()
        if not bootstrap:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Kafka credential is missing 'bootstrap_servers'.",
                retryable=False,
            )
        protocol = str((creds or {}).get("security_protocol") or "PLAINTEXT").upper()
        kwargs: Dict[str, Any] = {
            "bootstrap_servers": bootstrap,
            "client_id": str((creds or {}).get("client_id") or "flowsmith"),
            "security_protocol": protocol,
            "request_timeout_ms": 15000,
        }
        if protocol.startswith("SASL"):
            kwargs["sasl_mechanism"] = str((creds or {}).get("sasl_mechanism") or "PLAIN")
            kwargs["sasl_plain_username"] = str((creds or {}).get("sasl_username") or "") or None
            kwargs["sasl_plain_password"] = str((creds or {}).get("sasl_password") or "") or None
        if protocol in ("SSL", "SASL_SSL"):
            pem = str((creds or {}).get("ssl_ca_pem") or "").strip()
            if pem:
                kwargs["ssl_context"] = ssl.create_default_context(cadata=pem)
        return kwargs

    async def _produce(self, creds: Dict[str, Any], params: KafkaConnectorParams) -> Dict[str, Any]:
        if not params.topic.strip():
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Topic is required for Kafka produce operation.",
                retryable=False,
            )
        Producer, _, _ = _require_aiokafka()
        producer = Producer(**self._client_kwargs(creds))
        try:
            await asyncio.wait_for(producer.start(), timeout=params.timeout_seconds)
            meta = await asyncio.wait_for(
                producer.send_and_wait(
                    params.topic,
                    value=_serialize(params.payload),
                    key=params.message_key.encode("utf-8") if params.message_key else None,
                    headers=[(str(k), str(v).encode("utf-8")) for k, v in (params.headers or {}).items()] or None,
                    partition=params.partition,
                ),
                timeout=params.timeout_seconds,
            )
            return {
                "status": "published",
                "topic": meta.topic,
                "partition": meta.partition,
                "offset": meta.offset,
                "timestamp": meta.timestamp,
                "key": params.message_key,
                "headers": params.headers,
            }
        except asyncio.TimeoutError as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Kafka produce timed out after {params.timeout_seconds:.0f}s.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Kafka produce failed: {exc}",
                retryable=True,
            ) from exc
        finally:
            try:
                await producer.stop()
            except Exception:
                logger.debug("Kafka producer stop failed", exc_info=True)

    async def _consume(self, creds: Dict[str, Any], params: KafkaConnectorParams) -> Dict[str, Any]:
        if not params.topic.strip():
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Topic is required for Kafka consume operation.",
                retryable=False,
            )
        _, Consumer, _ = _require_aiokafka()
        kwargs = self._client_kwargs(creds)
        consumer = Consumer(
            params.topic,
            group_id=params.consumer_group,
            auto_offset_reset=params.auto_offset_reset if params.auto_offset_reset in ("earliest", "latest") else "earliest",
            enable_auto_commit=params.auto_commit,
            **kwargs,
        )
        try:
            await asyncio.wait_for(consumer.start(), timeout=params.timeout_seconds)
            batches = await asyncio.wait_for(
                consumer.getmany(
                    timeout_ms=int(params.timeout_seconds * 1000),
                    max_records=params.max_messages,
                ),
                timeout=params.timeout_seconds + 5,
            )
            output = []
            for records in batches.values():
                for record in records:
                    output.append({
                        "topic": record.topic,
                        "partition": record.partition,
                        "offset": record.offset,
                        "key": record.key.decode("utf-8", errors="replace") if record.key else "",
                        "value": _deserialize(record.value),
                        "headers": _headers_to_dict(record.headers),
                        "timestamp": record.timestamp,
                    })
            return {"output": output, "count": len(output)}
        except asyncio.TimeoutError as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Kafka consume timed out after {params.timeout_seconds:.0f}s.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Kafka consume failed: {exc}",
                retryable=True,
            ) from exc
        finally:
            try:
                await consumer.stop()
            except Exception:
                logger.debug("Kafka consumer stop failed", exc_info=True)

    async def _list_topics(self, creds: Dict[str, Any], timeout: float) -> list[str]:
        _, _, Admin = _require_aiokafka()
        admin = Admin(**self._client_kwargs(creds))
        try:
            await asyncio.wait_for(admin.start(), timeout=timeout)
            topics = await asyncio.wait_for(admin.list_topics(), timeout=timeout)
            return sorted(str(topic) for topic in topics)
        except asyncio.TimeoutError as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Kafka topic listing timed out after {timeout:.0f}s.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Kafka topic listing failed: {exc}",
                retryable=True,
            ) from exc
        finally:
            try:
                await admin.close()
            except Exception:
                logger.debug("Kafka admin close failed", exc_info=True)
