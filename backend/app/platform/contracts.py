"""Platform contracts shared across control-plane and execution-plane modules.

These are intentionally lightweight (dataclasses + protocols) so domain modules
can depend on them without importing FastAPI, SQLAlchemy models, or each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_AUTH = "waiting_auth"
    RETRYING = "retrying"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.SUCCESS,
        RunStatus.FAILED,
        RunStatus.TIMEOUT,
        RunStatus.CANCELLED,
    }
)

ACTIVE_STATUSES = frozenset(
    {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.WAITING_AUTH,
        RunStatus.RETRYING,
        RunStatus.CANCELLING,
    }
)


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    FINANCIAL = "financial"
    PII = "pii"


class Idempotency(str, Enum):
    IDEMPOTENT = "idempotent"
    CONDITIONALLY_IDEMPOTENT = "conditionally_idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class ToolResultStatus(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    ERROR = "error"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EventEnvelope:
    """Immutable fact published by a domain module.

    ``event_id`` is the dedupe key; ``idempotency_key`` is the effect key for
    handlers that perform writes. Breaking payload changes require a new
    ``schema_version``.
    """

    event_id: str
    event_type: str
    tenant_id: str
    correlation_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    occurred_at: datetime = field(default_factory=utcnow)
    workspace_id: str | None = None
    run_id: str | None = None
    node_id: str | None = None
    trace_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if not self.event_type.strip():
            raise ValueError("event_type is required")
        if not self.tenant_id.strip():
            raise ValueError("tenant_id is required")
        if not self.correlation_id.strip():
            raise ValueError("correlation_id is required")
        if self.schema_version < 1:
            raise ValueError("schema_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.payload)
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "idempotency_key": self.idempotency_key,
            "payload": payload,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventEnvelope":
        occurred_at = value.get("occurred_at")
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if occurred_at is None:
            occurred_at = utcnow()
        payload = value.get("payload") or {}
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        return cls(
            event_id=str(value["event_id"]),
            event_type=str(value["event_type"]),
            schema_version=int(value.get("schema_version", 1)),
            occurred_at=occurred_at,
            tenant_id=str(value["tenant_id"]),
            workspace_id=value.get("workspace_id"),
            run_id=value.get("run_id"),
            node_id=value.get("node_id"),
            trace_id=value.get("trace_id"),
            correlation_id=str(value["correlation_id"]),
            causation_id=value.get("causation_id"),
            idempotency_key=value.get("idempotency_key"),
            payload=payload,
        )


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    risk_class: RiskClass
    idempotency: Idempotency = Idempotency.CONDITIONALLY_IDEMPOTENT
    timeout_s: float = 30.0
    max_output_bytes: int = 256_000
    source: str = "native"
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name is required")
        if self.timeout_s <= 0:
            raise ValueError("tool timeout_s must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("tool max_output_bytes must be positive")
        if not self.description.strip():
            raise ValueError("tool description is required")


@dataclass(frozen=True)
class ToolInvocation:
    run_id: str
    node_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    idempotency_key: str
    context: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: ToolResultStatus
    output: Any = None
    error_code: str | None = None
    latency_ms: float = 0.0


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason_code: str
    risk_tier: int = 0
    required_approvers: tuple[str, ...] = ()
    quorum: int = 0
    expires_in_s: int = 0
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome is PolicyOutcome.ALLOW


@dataclass(frozen=True)
class Checkpoint:
    run_id: str
    node_id: str
    status: str
    outputs: Mapping[str, Any]
    version: int
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: RunStatus
    version: int = 0
    tenant_id: str | None = None
    workspace_id: str | None = None


@runtime_checkable
class RunStore(Protocol):
    def create(self, snapshot: RunSnapshot) -> RunSnapshot: ...
    def load(self, run_id: str) -> RunSnapshot: ...
    def save_checkpoint(self, checkpoint: Checkpoint) -> None: ...
    def transition(self, run_id: str, target: RunStatus, expected_version: int) -> RunSnapshot: ...


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(self, job: Mapping[str, Any]) -> str: ...
    async def claim(self, worker_id: str) -> Mapping[str, Any] | None: ...
    async def heartbeat(self, job_id: str, worker_id: str) -> None: ...
    async def complete(self, job_id: str, status: str) -> None: ...


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: EventEnvelope) -> None: ...


@runtime_checkable
class ToolGatewayProtocol(Protocol):
    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        capabilities: frozenset[str],
        approval_granted: bool = False,
    ) -> ToolResult: ...


@runtime_checkable
class ApprovalBroker(Protocol):
    async def request(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    async def decide(self, request_id: str, decision: Mapping[str, Any]) -> None: ...
