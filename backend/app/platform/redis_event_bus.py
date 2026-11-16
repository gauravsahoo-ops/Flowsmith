"""Redis Streams event bus adapter for the transactional outbox.

The relay publishes immutable :class:`EventEnvelope` facts to a Redis Stream
with ``XADD``. Delivery is at-least-once; consumers dedupe by ``event_id``.
Redis is transport only - Postgres remains the system of record.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from app.platform.contracts import EventEnvelope
from app.security.redis_client import get_shared_redis

logger = logging.getLogger("platform.redis_event_bus")

DEFAULT_STREAM_NAME = "flowsmith.events"
DEFAULT_MAX_STREAM_LEN = 100_000


class RedisEventBus:
    """Publish event envelopes to a Redis Stream via ``XADD``.

    ``client`` is injectable for tests; production uses the shared client
    from :func:`app.security.redis_client.get_shared_redis`.
    """

    def __init__(
        self,
        stream_name: str = DEFAULT_STREAM_NAME,
        *,
        max_len: int = DEFAULT_MAX_STREAM_LEN,
        client: Any | None = None,
    ) -> None:
        if not stream_name.strip():
            raise ValueError("stream_name is required")
        if max_len <= 0:
            raise ValueError("max_len must be positive")
        self._stream_name = stream_name
        self._max_len = max_len
        self._client = client

    @property
    def stream_name(self) -> str:
        return self._stream_name

    @property
    def max_len(self) -> int:
        return self._max_len

    def _require_client(self) -> Any:
        client = self._client if self._client is not None else get_shared_redis()
        if client is None:
            raise RuntimeError(
                "Redis is unavailable: configure REDIS_URL (and REDIS_PASSWORD "
                "if required) or disable the outbox relay."
            )
        return client

    async def publish(self, event: EventEnvelope) -> None:
        """Append ``event`` to the stream as one JSON ``data`` field."""
        try:
            data = json.dumps(
                event.to_dict(),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Event {event.event_id!r} cannot be serialized as JSON: {exc}"
            ) from exc

        client = self._require_client()
        try:
            # The shared client is synchronous; keep it off the event loop.
            result = await asyncio.to_thread(
                client.xadd,
                self._stream_name,
                {"data": data},
                maxlen=self._max_len,
                approximate=True,
            )
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            raise RuntimeError(
                f"Failed to publish event {event.event_id!r} to Redis stream "
                f"{self._stream_name!r}: {exc}"
            ) from exc
        logger.debug(
            "published event %s to stream %s", event.event_id, self._stream_name
        )
