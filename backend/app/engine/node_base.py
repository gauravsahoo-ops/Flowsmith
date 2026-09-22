"""The node SDK contract (spec 7, 26, 27).

A node is a class that declares metadata + a Pydantic parameters schema
and implements `run()`. The same schema drives validation now and will
drive the API config-panel forms later.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Generic, TypeVar, cast

import httpx
from pydantic import BaseModel

from app.engine.errors import NodeExecutionError

__all__ = [
    "BaseNode",
    "NodeContext",
    "NodeResult",
    "MemoryKVStore",
    "NodeExecutionError",
    "IDEMPOTENT",
    "CONDITIONALLY_IDEMPOTENT",
    "NON_IDEMPOTENT",
]

IDEMPOTENT = "idempotent"
CONDITIONALLY_IDEMPOTENT = "conditionally_idempotent"
NON_IDEMPOTENT = "non-idempotent"
#: Valid values for BaseNode.idempotency (spec 35).
IDEMPOTENCY_LEVELS = frozenset({IDEMPOTENT, CONDITIONALLY_IDEMPOTENT, NON_IDEMPOTENT})

ParamsT = TypeVar("ParamsT", bound=BaseModel)


class MemoryKVStore:
    """Async in-process TTL key/value store for node idempotency caching.

    Nodes read/write it with ``await ctx.storage.get/set``; entries
    expire after their TTL (seconds) or live forever when no TTL is set.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            value, expires = item
            if expires is not None and time.monotonic() > expires:
                self._data.pop(key, None)
                return default
            return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        async with self._lock:
            expires = time.monotonic() + ttl if ttl is not None else None
            self._data[key] = (value, expires)

    def seed(self, key: str, value: Any) -> None:
        """Synchronous pre-loop insert (resume seeding); no lock needed
        because it runs before any task exists."""
        self._data[key] = (value, None)


class NodeResult(BaseModel):
    """Structured output of a node run (spec 27).

    Either `output_items` (for the "main" handle) or `output_by_handle`
    (for multi-output nodes like IF: {"true": [...], "false": [...]}).
    """

    output_items: list[dict[str, Any]] | None = None
    output_by_handle: dict[str, list[dict[str, Any]]] | None = None
    metadata: dict[str, Any] = {}

    def items_for(self, handle: str) -> list[dict[str, Any]]:
        if self.output_by_handle is not None:
            return self.output_by_handle.get(handle, [])
        return self.output_items or []


def filter_client_kwargs(client: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop kwargs the injected HTTP client doesn't support, so nodes can
    pass the full extended set (follow_redirects, max_response_bytes, …)
    while plain httpx.AsyncClient test doubles keep working."""
    import inspect

    request_fn = getattr(client, "request", None)
    if request_fn is None:
        return {}
    try:
        sig = inspect.signature(request_fn)
    except (TypeError, ValueError):
        return kwargs
    if any(pr.kind is inspect.Parameter.VAR_KEYWORD for pr in sig.parameters.values()):
        return kwargs
    named = {
        name for name, pr in sig.parameters.items()
        if pr.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in kwargs.items() if k in named}

class NodeContext:
    """Carries execution-scoped services into a node (spec 8.1, 36)."""

    def __init__(
        self,
        *,
        execution_id: str,
        workflow_id: str,
        node_id: str = "",
        logger: logging.Logger,
        http_client: httpx.AsyncClient,
        storage: MemoryKVStore | None = None,
        emit_event: Callable[..., Any] | None = None,
        credentials: dict[str, Any] | None = None,
        env_vars: dict[str, str] | None = None,
        execution_depth: int = 0,
        cancel_event: asyncio.Event | None = None,
        workspace_id: str | None = None,
        user_id: int | None = None,
    ):
        self.execution_id = execution_id
        self.workflow_id = workflow_id
        self.node_id = node_id
        self.logger = logger
        self.http_client = http_client
        self.storage = storage if storage is not None else MemoryKVStore()
        self._emit_event = emit_event or (lambda *a, **k: None)
        self._cancelled = False
        self.credentials: dict[str, Any] = credentials or {}
        # Workspace environment variables (Phase 31): resolved decrypted
        # values, exposed to expressions as {{ $env.KEY }}.
        self.env_vars: dict[str, str] = env_vars or {}
        # Phase 8: nesting depth for sub-workflow recursion guarding and
        # the shared cancel event so nodes that spawn child executions
        # (sub_workflow) propagate cancellation downward.
        self.execution_depth = execution_depth
        self.cancel_event = cancel_event
        # Phase 18: tenant identity for resource-scoped nodes (RAG
        # collections resolve against the run's workspace/owner).
        self.workspace_id: str | None = workspace_id
        self.user_id: int | None = user_id
        # Phase 8: the executor stores the credential resolver on the
        # context so sub-workflow nodes can propagate it to child runs.
        self._credential_resolver: Callable[[dict[str, str]], dict[str, Any]] | None = None
        # The engine-built expression context for this node (set by the
        # executor just before the node runs). Nodes with
        # resolves_own_expressions extend it per evaluation
        # (e.g. loop_while adds $iterations / fresh $json).
        self.expression_context: dict[str, Any] | None = None

    def is_cancelled(self) -> bool:
        """Cooperative cancellation check (spec 36)."""
        return self._cancelled

    def emit_event(self, name: str, *, node_id: str | None = None,
                   status: str | None = None, **extra: Any) -> None:
        self._emit_event(
            {"event": name, "execution_id": self.execution_id,
             "workflow_id": self.workflow_id, "node_id": node_id,
             "status": status, **extra}
        )


class EmptyParams(BaseModel):
    """Default parameters schema for nodes without parameters."""

    pass


class BaseNode(Generic[ParamsT]):
    """Every node implements this interface (spec 26).

    Subclasses parameterize the params type:

        class HTTPRequestNode(BaseNode[HTTPRequestParams]): ...
    """

    node_type: str = ""
    display_name: str = ""
    version: int = 1
    description: str = ""
    category: str = "Actions"
    icon: str = "🔧"
    parameters_schema: type[BaseModel] = EmptyParams
    credential_types: list[str] = []
    input_handles: list[str] = ["main"]
    output_handles: list[str] = ["main"]
    # Spec 35: whether re-running this node can duplicate external side
    # effects. One of IDEMPOTENCY_LEVELS; surfaced in the node catalog
    # (GET /api/nodes) and shown in the UI. Deterministic local nodes
    # default to "idempotent"; nodes with external or paid side effects
    # (email, LLM calls, writes) must declare otherwise.
    idempotency: str = "idempotent"
    # Phase 8: when True the executor hands the node its RAW parameters
    # and skips the one-shot pre-resolution pass, because the node
    # re-evaluates expressions itself at run time (e.g. per loop
    # iteration, where {{ $iterations }} / evolving $json only exist
    # inside the node).
    resolves_own_expressions: bool = False

    def build_params(self, raw: dict[str, Any]) -> ParamsT:
        """Validate and normalize the raw parameters dict (spec 26.3)."""
        return cast(ParamsT, self.parameters_schema.model_validate(raw))

    async def run(
        self,
        ctx: NodeContext,
        params: ParamsT,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        raise NotImplementedError(f"Node '{self.node_type}' does not implement run().")
