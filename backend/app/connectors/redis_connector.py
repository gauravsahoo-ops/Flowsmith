"""Redis connector implementing the ConnectorSDK interface.

Thin mapper over RedisProviderClient (redis-py asyncio); credentials
arrive via context["credentials"]["redis"], falling back to REDIS_URL.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.redis_provider import RedisProviderClient


class RedisConnectorParams(BaseModel):
    operation: str = Field(default="get", description="get | set | delete | incr | publish.")
    key: str = ""
    value: str = ""
    channel: str = ""
    message: str = ""
    ttl_seconds: int = Field(default=0, ge=0, le=2_147_483_647, description="0 = no expiry.")
    amount: int = 1
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class RedisConnector(ConnectorSDK):
    connector_id = "redis"
    display_name = "Redis"
    description = "Read/write keys and publish messages in Redis."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = RedisProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["redis"]

    async def connect(self, config: dict[str, Any]) -> bool:
        # Empty uri is allowed (server REDIS_URL fallback).
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = RedisConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Redis payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("redis") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "get":
                return await self._provider.get(creds, str(raw.get("key") or params.key))
            if op == "set":
                ttl_raw = raw.get("ttl_seconds")
                try:
                    ttl = int(ttl_raw) if ttl_raw is not None else params.ttl_seconds
                except (TypeError, ValueError) as exc:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "ttl_seconds must be an integer.", retryable=False,
                    ) from exc
                return await self._provider.set(
                    creds, str(raw.get("key") or params.key),
                    str(raw.get("value") or params.value), ttl_seconds=ttl,
                )
            if op == "delete":
                return await self._provider.delete(creds, str(raw.get("key") or params.key))
            if op == "incr":
                amount_raw = raw.get("amount", params.amount)
                try:
                    amount = int(amount_raw)
                except (TypeError, ValueError) as exc:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "amount must be an integer.", retryable=False,
                    ) from exc
                return await self._provider.incr(
                    creds, str(raw.get("key") or params.key), amount=amount,
                )
            if op == "publish":
                return await self._provider.publish(
                    creds, str(raw.get("channel") or params.channel),
                    str(raw.get("message") or params.message),
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Redis operation '{operation}'.", retryable=False,
        )

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}
