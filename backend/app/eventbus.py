"""In-process live event bus (v1 of spec 10's Redis pub/sub).

The background runner publishes execution events as they happen; the
WebSocket endpoint drains them. `deque` operations are thread-safe in
CPython, so publish (worker thread) and drain (API event loop) can run
concurrently. Swapping this for Redis pub/sub in production is a
drop-in change behind the same publish/drain API.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

Event = dict[str, Any]


class EventBus:
    def __init__(self, maxlen: int = 500, max_executions: int = 100) -> None:
        self._events: dict[str, deque[Event]] = defaultdict(lambda: deque(maxlen=maxlen))
        self._seq: dict[str, int] = defaultdict(int)
        self._max_executions = max_executions

    def publish(self, execution_id: str, event: Event) -> None:
        while len(self._events) >= self._max_executions and execution_id not in self._events:
            self._events.pop(next(iter(self._events)), None)
            self._seq.pop(next(iter(self._seq)), None)
        self._seq[execution_id] += 1
        self._events[execution_id].append(
            {"seq": self._seq[execution_id], "execution_id": execution_id, **event}
        )

    def drain(self, execution_id: str, after_seq: int = 0) -> list[Event]:
        return [e for e in self._events.get(execution_id, ()) if e["seq"] > after_seq]

    def clear(self, execution_id: str) -> None:
        self._events.pop(execution_id, None)
        self._seq.pop(execution_id, None)


bus = EventBus()
