"""Cross-cutting platform primitives (contracts, events, state machine ports)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.platform.contracts import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    ApprovalBroker,
    Checkpoint,
    EventBus,
    EventEnvelope,
    Idempotency,
    JobQueue,
    PolicyDecision,
    PolicyOutcome,
    RiskClass,
    RunSnapshot,
    RunStatus,
    RunStore,
    ToolDescriptor,
    ToolGatewayProtocol,
    ToolInvocation,
    ToolResult,
    ToolResultStatus,
)

if TYPE_CHECKING:
    from app.platform.outbox_relay import OutboxRelay
    from app.platform.redis_event_bus import RedisEventBus

__all__ = [
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "ApprovalBroker",
    "Checkpoint",
    "EventBus",
    "EventEnvelope",
    "Idempotency",
    "JobQueue",
    "OutboxRelay",
    "PolicyDecision",
    "PolicyOutcome",
    "RedisEventBus",
    "RiskClass",
    "RunSnapshot",
    "RunStatus",
    "RunStore",
    "ToolDescriptor",
    "ToolGatewayProtocol",
    "ToolInvocation",
    "ToolResult",
    "ToolResultStatus",
]


def __getattr__(name: str) -> Any:
    """Lazily expose infrastructure adapters.

    Eager imports would make every ``app.platform.contracts`` consumer load
    the SQLAlchemy model layer and the Redis client module.
    """
    if name == "OutboxRelay":
        from app.platform.outbox_relay import OutboxRelay

        return OutboxRelay
    if name == "RedisEventBus":
        from app.platform.redis_event_bus import RedisEventBus

        return RedisEventBus
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
