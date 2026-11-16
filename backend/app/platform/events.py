"""Event names, envelope construction, and an in-memory bus for tests."""

from __future__ import annotations

import inspect
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any

from app.platform.contracts import EventEnvelope, utcnow

EVENT_SCHEMA_VERSION = 1

RUN_QUEUED = "run.queued"
RUN_STARTED = "run.started"
RUN_PAUSED = "run.paused"
RUN_RESUMED = "run.resumed"
RUN_CANCELLING = "run.cancelling"
RUN_COMPLETED = "run.completed"
RUN_RECOVERED = "run.recovered"

NODE_STARTED = "node.started"
NODE_COMPLETED = "node.completed"
NODE_FAILED = "node.failed"
NODE_SKIPPED = "node.skipped"

AGENT_ITERATION_STARTED = "agent.iteration.started"
AGENT_ITERATION_COMPLETED = "agent.iteration.completed"
AGENT_TOOL_REQUESTED = "agent.tool.requested"
AGENT_TOOL_COMPLETED = "agent.tool.completed"
AGENT_COMPLETED = "agent.completed"
AGENT_FAILED = "agent.failed"

APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
APPROVAL_EXPIRED = "approval.expired"

TOOL_INVOKED = "tool.invoked"
TOOL_COMPLETED = "tool.completed"
TOOL_FAILED = "tool.failed"

AUDIT_EVENT = "audit.event"
CONNECTOR_HEALTH_CHANGED = "connector.health_changed"

ALL_EVENT_TYPES = frozenset(
    {
        RUN_QUEUED,
        RUN_STARTED,
        RUN_PAUSED,
        RUN_RESUMED,
        RUN_CANCELLING,
        RUN_COMPLETED,
        RUN_RECOVERED,
        NODE_STARTED,
        NODE_COMPLETED,
        NODE_FAILED,
        NODE_SKIPPED,
        AGENT_ITERATION_STARTED,
        AGENT_ITERATION_COMPLETED,
        AGENT_TOOL_REQUESTED,
        AGENT_TOOL_COMPLETED,
        AGENT_COMPLETED,
        AGENT_FAILED,
        APPROVAL_REQUESTED,
        APPROVAL_DECIDED,
        APPROVAL_EXPIRED,
        TOOL_INVOKED,
        TOOL_COMPLETED,
        TOOL_FAILED,
        AUDIT_EVENT,
        CONNECTOR_HEALTH_CHANGED,
    }
)


def new_event(
    event_type: str,
    *,
    tenant_id: str,
    correlation_id: str | None = None,
    workspace_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    trace_id: str | None = None,
    causation_id: str | None = None,
    idempotency_key: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> EventEnvelope:
    if event_type not in ALL_EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type!r}")
    return EventEnvelope(
        event_id=f"evt_{uuid.uuid4().hex}",
        event_type=event_type,
        schema_version=EVENT_SCHEMA_VERSION,
        occurred_at=utcnow(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        correlation_id=correlation_id or f"corr_{uuid.uuid4().hex}",
        causation_id=causation_id,
        idempotency_key=idempotency_key,
        payload=payload or {},
    )


def idempotency_key(
    run_id: str,
    node_id: str,
    operation: str,
    *,
    attempt: int = 0,
) -> str:
    """Stable effect key for a run/node/operation.

    Retries reuse the same key; distinct operations must not.
    """
    if not run_id or not node_id or not operation:
        raise ValueError("run_id, node_id, and operation are required")
    return f"{run_id}:{node_id}:{operation}:{int(attempt)}"


class InMemoryEventBus:
    """Small test/dev bus implementing the EventBus protocol."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[EventEnvelope], Any]]] = defaultdict(list)
        self._history: list[EventEnvelope] = []

    def subscribe(self, event_type: str, handler: Callable[[EventEnvelope], Any]) -> None:
        if event_type not in ALL_EVENT_TYPES and event_type != "*":
            raise ValueError(f"Unknown event type: {event_type!r}")
        self._handlers[event_type].append(handler)

    async def publish(self, event: EventEnvelope) -> None:
        self._history.append(event)
        handlers = [*self._handlers.get(event.event_type, ()), *self._handlers.get("*", ())]
        for handler in handlers:
            result = handler(event)
            if inspect.isawaitable(result):
                await result

    def history(self) -> tuple[EventEnvelope, ...]:
        return tuple(self._history)
