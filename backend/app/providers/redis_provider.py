"""Redis provider client (Phase 11 business connectors).

redis-py's asyncio API against a credential URI (or the server-wide
``REDIS_URL`` when the credential leaves it empty). One short-lived
connection per call — connector operations must never share pool state
across tenants.

The ``redis`` package is a core dependency already (queue backend), so
no optional-import dance is needed here.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from app.config import get_settings
from app.connectors import ConnectorErrorCode, make_connector_error


def _require_uri(creds: dict) -> str:
    uri = str((creds or {}).get("uri") or "").strip()
    if not uri:
        uri = get_settings().redis_url.strip()
    if not uri:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Redis connector needs a 'redis' credential with a redis:// URI (or REDIS_URL on the server).",
            retryable=False,
        )
    if not uri.lower().startswith(("redis://", "rediss://", "unix://")):
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "A Redis credential URI must start with redis:// or rediss://.",
            retryable=False,
        )
    return uri


def _translate(exc: Exception, operation: str) -> None:
    if isinstance(exc, (RedisConnectionError, RedisTimeoutError)):
        raise make_connector_error(
            ConnectorErrorCode.UNAVAILABLE, f"Redis {operation} failed: {exc}", retryable=True,
        ) from exc
    raise make_connector_error(
        ConnectorErrorCode.BAD_REQUEST, f"Redis {operation} failed: {exc}", retryable=False,
    ) from exc


class RedisProviderClient:
    """Low-level Redis operations (get/set/delete/incr/publish)."""

    async def _run(self, creds: dict, operation: str, fn) -> Any:
        try:
            client = aioredis.from_url(_require_uri(creds), decode_responses=True)
            try:
                return await fn(client)
            finally:
                await client.aclose()
        except RedisError as exc:
            _translate(exc, operation)

    async def get(self, creds: dict, key: str) -> dict[str, Any]:
        key_clean = self._key(key)

        async def op(client):
            value = await client.get(key_clean)
            return {"found": value is not None, "key": key_clean, "value": value}

        result = await self._run(creds, "get", op)
        return result

    async def set(self, creds: dict, key: str, value: str,
                  ttl_seconds: int = 0) -> dict[str, Any]:
        key_clean = self._key(key)
        ttl = max(int(ttl_seconds or 0), 0)

        async def op(client):
            await client.set(key_clean, str(value), ex=ttl or None)
            return {"key": key_clean, "set": True, "ttl": ttl or None}

        return await self._run(creds, "set", op)

    async def delete(self, creds: dict, key: str) -> dict[str, Any]:
        key_clean = self._key(key)

        async def op(client):
            deleted = await client.delete(key_clean)
            return {"key": key_clean, "deleted": int(deleted)}

        return await self._run(creds, "delete", op)

    async def incr(self, creds: dict, key: str, amount: int = 1) -> dict[str, Any]:
        key_clean = self._key(key)
        try:
            step = int(amount or 1)
        except (TypeError, ValueError) as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "amount must be an integer.", retryable=False) from exc

        async def op(client):
            value = await client.incrby(key_clean, step)
            return {"key": key_clean, "value": int(value)}

        return await self._run(creds, "incr", op)

    async def publish(self, creds: dict, channel: str, message: str) -> dict[str, Any]:
        channel_clean = self._key(channel)
        text = str(message or "")
        if not text:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "publish requires a message.", retryable=False)

        async def op(client):
            receivers = await client.publish(channel_clean, text)
            return {"channel": channel_clean, "receivers": int(receivers)}

        return await self._run(creds, "publish", op)

    @staticmethod
    def _key(value: str) -> str:
        key = str(value or "").strip()
        if not key or "\x00" in key or len(key) > 512:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "A non-empty key/channel (max 512 chars) is required.",
                retryable=False,
            )
        return key
