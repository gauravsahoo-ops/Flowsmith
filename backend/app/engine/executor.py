"""The workflow execution engine (spec 8).

execute_workflow() runs a validated workflow in topological order,
passing items between nodes along typed edges, honoring branches,
errors, skips, timeouts and cancellation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

import httpx

from app.connectors import ConnectorError
from app.connectors import get_registry as get_connector_registry
from app.credentials.service import CredentialError
from app.engine import expressions
from app.engine.errors import (
    NodeCancelledError,
    NodeExecutionError,
    NodeTimeoutError,
)
from app.engine.graph import build_graph, topological_sort, validate_graph
from app.engine.node_base import NodeContext, NodeResult
from app.nodes.registry import NODE_REGISTRY
from app.schemas.workflow import Workflow, WorkflowNode

logger = logging.getLogger("engine")

NodeResults = dict[str, dict[str, list[dict[str, Any]]]]

DEFAULT_MAX_PARALLELISM = 8
MAX_RETRY_BACKOFF_S = 60.0
MERGE_MODES = ("wait_for_all", "wait_for_one", "combine")


@dataclass
class ExecutionResult:
    """Outcome of one workflow run (spec 25, 51.1)."""

    status: str = "success"
    results: NodeResults = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    node_errors: dict[str, NodeExecutionError] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: NodeExecutionError | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    # Phase 14: PASS/FAIL/DIFF report when this run was a workflow test.
    test_report: dict[str, Any] | None = None

    @property
    def duration_ms(self) -> float:
        end = self.finished_at or time.monotonic()
        return (end - self.started_at) * 1000


def _cap(value: Any, depth: int = 25, max_items: int = 500, max_str: int = 500) -> Any:
    """Bound trace payloads so huge node I/O can't bloat the row (spec 26).

    Preserves all primitive values (int, float, bool, None, normal strings)
    and allows deep nesting (depth=25) so API output structures are never
    corrupted into "[truncated] (str)" or "[truncated] (int)".
    """
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        return value[:max_str] + "…" if len(value) > max_str else value
    if depth <= 0:
        return f"[truncated] ({type(value).__name__})"
    if isinstance(value, list):
        out = [_cap(v, depth - 1, max_items, max_str) for v in value[:max_items]]
        if len(value) > max_items:
            out.append(f"[{len(value) - max_items} more items truncated]")
        return out
    if isinstance(value, dict):
        out = {k: _cap(v, depth - 1, max_items, max_str) for k, v in list(value.items())[:max_items]}
        if len(value) > max_items:
            out["[truncated]"] = f"{len(value) - max_items} more keys"
        return out
    return value


def _add_step(
    result: ExecutionResult,
    *,
    node_id: str,
    node_type: str,
    status: str,
    started_at: str,
    duration_ms: float,
    inputs: list[dict[str, Any]] | None = None,
    outputs: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    note: str | None = None,
    attempts: int = 1,
    retries: int = 0,
) -> None:
    # Phase 13 (workflow debugger): attempts/retries are structured so the
    # UI can badge them without parsing the note text.
    result.trace.append({
        "node_id": node_id,
        "node_type": node_type,
        "status": status,
        "started_at": started_at,
        "duration_ms": round(duration_ms, 1),
        "inputs": inputs,
        "outputs": outputs,
        "error": error,
        "note": note,
        "attempts": max(1, attempts),
        "retries": max(0, retries),
    })


def _setting_float(settings: dict[str, Any], key: str) -> float | None:
    """Parse a positive float setting; None when absent/invalid."""
    try:
        value = float(settings.get(key) or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _merge_mode(node: WorkflowNode) -> str:
    mode = node.settings.get("merge_mode", "wait_for_all")
    return mode if mode in MERGE_MODES else "wait_for_all"


async def execute_workflow(
    workflow: Workflow,
    trigger_items: list[dict[str, Any]] | None = None,
    *,
    execution_id: str = "exec_test",
    http_client: httpx.AsyncClient | None = None,
    cancel_event: asyncio.Event | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    credential_resolver: Callable[[dict[str, str]], dict[str, Any]] | None = None,
    env_vars: dict[str, str] | None = None,
    initial_results: NodeResults | None = None,
    storage_seed: dict[str, Any] | None = None,
    execution_depth: int = 0,
    workspace_id: str | None = None,
    user_id: int | None = None,
) -> ExecutionResult:
    """Run the workflow and return per-node results (spec 8.5).

    `cancel_event` lets an external caller (e.g. the API) cancel a
    running execution; the engine stops between nodes and marks the
    execution cancelled.

    `event_sink` receives every event *as it happens* (live streaming
    for spec 10), in addition to the collected `result.events`.

    `credential_resolver` decrypts a node's `credentials` map
    (`{type: id}` -> `{type: decrypted_data}`) right before the node
    runs (spec 29.5); without it nodes get an empty credentials dict.

    `env_vars` are workspace environment variables resolved by the
    runtime (Phase 31) and exposed to expressions as `{{ $env.KEY }}`.

    `initial_results` replays persisted outputs of already-completed
    nodes (durable pause/resume, Phase 32): those nodes are not
    re-executed, so resuming an approval never re-runs upstream side
    effects.     `storage_seed` pre-loads the per-run KV store (e.g. the
    recorded approval decision).

    `execution_depth` tracks sub-workflow nesting (Phase 8): nodes that
    spawn child executions increment it so the recursion guard in the
    sub_workflow node can bound nesting.

    Workflow settings honored (spec 8.2/8.3):
    - `timeout_seconds`: kill the whole run and mark it 'timeout'.
    - `max_parallelism`: how many independent branches run at once.
    """
    validate_graph(workflow)
    graph = build_graph(workflow)
    order = topological_sort(graph)
    trigger_items = trigger_items if trigger_items is not None else [{}]

    workflow_timeout = _setting_float(workflow.settings, "timeout_seconds")
    try:
        max_parallelism = int(workflow.settings.get("max_parallelism", DEFAULT_MAX_PARALLELISM) or DEFAULT_MAX_PARALLELISM)
    except (TypeError, ValueError):
        max_parallelism = DEFAULT_MAX_PARALLELISM
    max_parallelism = max(1, min(32, max_parallelism))

    result = ExecutionResult()
    event_queue: list[dict[str, Any]] = []
    cancelled = cancel_event or asyncio.Event()

    def _forward(ev: dict[str, Any]) -> None:
        event_queue.append(ev)
        if event_sink is not None:
            event_sink(ev)

    ctx = NodeContext(
        execution_id=execution_id,
        workflow_id=workflow.id,
        logger=logger,
        http_client=http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0)),
        emit_event=_forward,
        env_vars=env_vars,
        execution_depth=execution_depth,
        cancel_event=cancelled,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    owns_client = http_client is None
    if storage_seed:
        for key, value in storage_seed.items():
            ctx.storage.seed(key, value)

    def emit_all(name: str, *, node_id: str | None = None,
                 status: str | None = None, **extra: Any) -> None:
        ctx.emit_event(name, node_id=node_id, status=status, **extra)

    emit_all("execution.started")

    monitor = asyncio.create_task(_monitor_cancel(ctx, cancelled))
    try:
        run = _run_nodes(
            graph, trigger_items, ctx, result, emit_all, cancelled,
            credential_resolver, max_parallelism, initial_results,
        )
        if workflow_timeout:
            await asyncio.wait_for(run, timeout=workflow_timeout)
        else:
            await asyncio.shield(run)
    except asyncio.TimeoutError:
        cancelled.set()
        ctx._cancelled = True
        result.status = "timeout"
        emit_all("execution.timeout", status="timeout")
    except asyncio.CancelledError:
        cancelled.set()
        ctx._cancelled = True
        result.status = "cancelled"
        emit_all("execution.cancelled", status="cancelled")
    finally:
        monitor.cancel()
        if owns_client:
            try:
                await ctx.http_client.aclose()
            except Exception:
                pass

    result.finished_at = time.monotonic()
    result.events = event_queue
    return result


async def _monitor_cancel(ctx: NodeContext, cancelled: asyncio.Event) -> None:
    """Flip ctx._cancelled the moment the shared cancel event fires, so
    running nodes polling `ctx.is_cancelled()` notice immediately."""
    try:
        await cancelled.wait()
    except asyncio.CancelledError:
        return
    ctx._cancelled = True


async def _run_nodes(
    graph: dict,
    trigger_items: list[dict[str, Any]],
    ctx: NodeContext,
    result: ExecutionResult,
    emit: Callable[..., Any],
    cancelled: asyncio.Event,
    credential_resolver: Callable[[dict[str, str]], dict[str, Any]] | None = None,
    max_parallelism: int = DEFAULT_MAX_PARALLELISM,
    initial_results: NodeResults | None = None,
) -> None:
    """Ready-set scheduler (spec 8.2): independent branches run
    concurrently; each node starts once its parents are done.

    `initial_results` pre-seeds completed nodes (durable resume): they
    are marked scheduled and their children's dependencies are satisfied
    without re-execution."""
    results: NodeResults = dict(initial_results or {})
    sem = asyncio.Semaphore(max_parallelism)
    active: set[asyncio.Task] = set()
    scheduled: set[str] = set(results.keys())
    pending: dict[str, set[str]] = {
        nid: set(gnode.input_node_ids) for nid, gnode in graph.items()
    }

    # Children whose parents are all pre-seeded become ready immediately.
    for nid in list(scheduled):
        gnode = graph.get(nid)
        if gnode is None:
            continue
        for child in gnode.output_node_ids:
            pending[child].discard(nid)

    async def run_one(nid: str) -> None:
        gnode = graph[nid]
        try:
            async with sem:
                seed = trigger_items if not gnode.input_connections else None
                await _run_one(
                    graph, gnode.node, gnode, seed, results, ctx, result, emit, cancelled,
                    credential_resolver,
                )
        except NodeExecutionError as exc:
            # Errors raised before _run_one's own handlers (e.g. credential
            # resolution) must still fail the run, not vanish into the task.
            exc.node_id = gnode.node.id
            _fail(gnode.node, gnode, results, result, exc, emit, graph)
        except CredentialError as exc:
            # Missing/foreign/undecryptable credentials are permanent
            # (never retried) and typed, so callers can distinguish them.
            _fail(
                gnode.node, gnode, results, result,
                NodeExecutionError(
                    exc.message,
                    code=exc.code or "CREDENTIALS_REQUIRED",
                    node_id=gnode.node.id,
                    retryable=False,
                ),
                emit, graph,
            )
        except Exception as exc:  # never let a raw exception escape the task
            _fail(
                gnode.node, gnode, results, result,
                NodeExecutionError(str(exc), code="NODE_ERROR", node_id=nid), emit, graph,
            )
        if nid in result.node_errors:
            return  # _fail already handled this branch's descendants
        if cancelled.is_set() or ctx.is_cancelled():
            return
        for child in gnode.output_node_ids:
            # Skip back-edge scheduling (visual loop connections)
            if child in gnode.back_edges:
                continue
            gchild = graph[child]
            if _merge_mode(gchild.node) == "wait_for_one":
                _schedule(child)
            else:
                pending[child].discard(nid)
                if not pending[child]:
                    _schedule(child)

    def _schedule(nid: str) -> None:
        if nid in scheduled or cancelled.is_set() or ctx.is_cancelled():
            return
        scheduled.add(nid)
        task = asyncio.create_task(run_one(nid))
        active.add(task)
        task.add_done_callback(active.discard)

    for nid in graph:
        if not graph[nid].input_connections:
            _schedule(nid)
        elif not pending[nid]:
            # All parents were pre-seeded (durable resume): ready now.
            _schedule(nid)

    while True:
        while active:
            done, _ = await asyncio.wait(tuple(active), return_when=asyncio.FIRST_COMPLETED)
            active.difference_update(done)

        # Cycle fallback: when all active tasks have drained, any nodes
        # still unscheduled are part of a cycle (every parent is either
        # unscheduled or stuck waiting for a child in the cycle).  We
        # break the cycle by scheduling the node with the fewest
        # remaining incomplete parents.  It receives empty input (its
        # parent hasn't produced output yet) which is the correct
        # cycle-breaking semantics.
        unscheduled = [
            nid for nid in graph
            if nid not in scheduled
            and nid not in result.skipped
            and nid not in result.node_errors
            and not cancelled.is_set()
            and not ctx.is_cancelled()
        ]
        if not unscheduled:
            break
        unscheduled.sort(
            key=lambda nid: sum(1 for p in graph[nid].input_node_ids if p not in results)
        )
        _schedule(unscheduled[0])

    # Nodes that could never become ready (a wait_for_all parent died
    # hard) are recorded as skipped, like the sequential engine did.
    for nid in graph:
        if nid in scheduled or nid in result.skipped or nid in results or nid in result.node_errors:
            continue
        result.skipped.append(nid)
        _add_step(
            result, node_id=nid, node_type=graph[nid].node.type, status="skipped",
            started_at=datetime.now(UTC).isoformat(), duration_ms=0,
            note="Parent node failed; step was not executed.",
        )

    result.results = results
    result.trace.sort(key=lambda s: s["started_at"])  # chronological across parallel branches
    if cancelled.is_set() or ctx.is_cancelled():
        result.status = "cancelled"
        emit("execution.cancelled", status="cancelled")
    elif result.error:
        result.status = "failed"
        emit("execution.failed", status="failed")
    else:
        result.status = "success"
        emit("execution.completed", status="success")


async def _run_via_connector(
    connector: Any,
    node: WorkflowNode,
    gnode: Any,
    results: NodeResults,
    ctx: NodeContext,
    result: ExecutionResult,
    emit: Callable[..., Any],
    input_items: list[dict[str, Any]],
    inputs_capped: list[dict[str, Any]],
    params: Any,
    cancelled: asyncio.Event,
    timeout: float | None,
    max_attempts: int,
    backoff: float,
    retries: int,
    started_wall: str,
    started_mono: float,
) -> None:
    """Execute a node through a registered ConnectorSDK instance.

    The connector's op_execute() receives the resolved parameters as
    its payload and credentials via the context dict.  The result is
    converted to NodeResult format so downstream nodes see the same
    interface regardless of whether a connector or node class ran.
    """
    connector_payload = params.model_dump() if hasattr(params, "model_dump") else dict(params)
    connector_context: dict[str, Any] = {
        "credentials": ctx.credentials,
        "execution_id": ctx.execution_id,
        "workflow_id": ctx.workflow_id,
        "input_items": input_items,
    }

    _current_retries = retries
    while True:
        try:
            op = connector.op_execute("execute", connector_payload, connector_context)
            if timeout:
                op = asyncio.wait_for(op, timeout=timeout)
            raw_result = await op
            break
        except asyncio.TimeoutError:
            assert timeout is not None  # wait_for was only applied when set
            node_error = NodeTimeoutError(node.id, timeout)
            if _current_retries:
                node_error.details = {"retries": _current_retries}
        except NodeCancelledError:
            raise
        except ConnectorError as ce:
            node_error = NodeExecutionError(
                str(ce), code=getattr(ce, "code", "CONNECTOR_ERROR"),
                node_id=node.id, retryable=getattr(ce, "retryable", False),
                details={"retries": _current_retries} if _current_retries else None,
            )
            # Phase 9: preserve the provider's Retry-After so the delay
            # below can honor it instead of the computed backoff.
            if getattr(ce, "retry_after", None) is not None:
                node_error.retry_after = ce.retry_after
        if _current_retries + 1 >= max_attempts or not node_error.retryable:
            raise node_error
        _current_retries += 1
        # Phase 9: when the provider sent Retry-After (Salesforce 429),
        # wait exactly as long as instructed instead of the computed
        # exponential backoff; still capped by MAX_RETRY_BACKOFF_S.
        computed_delay = min(backoff * (2 ** (_current_retries - 1)), MAX_RETRY_BACKOFF_S)
        delay = min(getattr(node_error, "retry_after", None) or computed_delay, MAX_RETRY_BACKOFF_S)
        emit("node.retry", node_id=node.id, status="retry",
             attempt=_current_retries, max_attempts=max_attempts,
             retry_after_s=delay, error={"message": str(node_error), "code": node_error.code})
        await asyncio.sleep(delay)
        if cancelled.is_set() or ctx.is_cancelled():
            raise NodeCancelledError(node.id)

    # Convert connector result to NodeResult format
    output = raw_result.get("output", raw_result) if isinstance(raw_result, dict) else raw_result
    if isinstance(output, dict):
        output_items = [output]
    elif isinstance(output, list):
        output_items = output
    else:
        output_items = [{"result": output}]

    node_result = NodeResult(output_items=output_items)
    results[node.id] = {"main": node_result.output_items or []}
    emit("node.completed", node_id=node.id, status="success")
    _add_step(
        result, node_id=node.id, node_type=node.type, status="success",
        started_at=started_wall,
        duration_ms=(time.monotonic() - started_mono) * 1000,
        inputs=inputs_capped,
        outputs=_cap(results[node.id]),
        note=(f"Via connector '{connector.connector_id}'; succeeded after {_current_retries} retries."
              if _current_retries else f"Via connector '{connector.connector_id}'."),
        attempts=_current_retries + 1,
        retries=_current_retries,
    )


async def _run_one(
    graph: dict,
    node: WorkflowNode,
    gnode: Any,
    seed_items: list[dict[str, Any]] | None,
    results: NodeResults,
    ctx: NodeContext,
    result: ExecutionResult,
    emit: Callable[..., Any],
    cancelled: asyncio.Event,
    credential_resolver: Callable[[dict[str, str]], dict[str, Any]] | None = None,
) -> None:
    # The shared context carries the running node's id so nodes can
    # identify themselves (events, pause state, per-node KV keys).
    ctx.node_id = node.id
    # Phase 23: a connector is a fallback for node types that have no
    # built-in node class (connector-only integrations). A registered
    # node class always wins, so connectors never override built-ins.
    connector_registry = get_connector_registry()
    node_cls = NODE_REGISTRY.get(node.type)
    connector = None if node_cls is not None else connector_registry.primary_for_node_type(node.type)
    if node_cls is None and connector is None:
        error = NodeExecutionError(f"Unknown node type '{node.type}'.", code="UNKNOWN_NODE_TYPE", node_id=node.id)
        _add_step(
            result, node_id=node.id, node_type=node.type, status="error",
            started_at=datetime.now(UTC).isoformat(), duration_ms=0,
            error=error.to_dict(),
        )
        return _fail(node, gnode, results, result, error, emit, graph)

    if any(parent_id in result.node_errors for parent_id in gnode.input_node_ids):
        result.skipped.append(node.id)
        emit("node.completed", node_id=node.id, status="skipped")
        _add_step(
            result, node_id=node.id, node_type=node.type, status="skipped",
            started_at=datetime.now(UTC).isoformat(), duration_ms=0,
            note="Parent node failed; step was not executed.",
        )
        return

    input_items = _gather_input(gnode, results) if gnode.input_connections else (seed_items or [])

    if gnode.input_connections and not input_items:
        result.skipped.append(node.id)
        emit("node.completed", node_id=node.id, status="skipped")
        _add_step(
            result, node_id=node.id, node_type=node.type, status="skipped",
            started_at=datetime.now(UTC).isoformat(), duration_ms=0,
            note="No input items arrived; step was not executed.",
        )
        return

    # Phase 1: Pin Data (Node Mocking) - bypass live execution if pinned
    pinned_data = getattr(node, "pinned_data", None)
    if pinned_data is not None:
        emit("node.started", node_id=node.id, status="running")
        started_wall = datetime.now(UTC).isoformat()
        started_mono = time.monotonic()
        inputs_capped = _cap(input_items)
        if isinstance(pinned_data, list):
            output_items = pinned_data
        elif isinstance(pinned_data, dict):
            if "main" in pinned_data and isinstance(pinned_data["main"], list):
                output_items = pinned_data["main"]
            else:
                output_items = [pinned_data]
        else:
            output_items = [{"result": pinned_data}]

        results[node.id] = {"main": output_items}
        emit("node.completed", node_id=node.id, status="success")
        _add_step(
            result, node_id=node.id, node_type=node.type, status="success",
            started_at=started_wall,
            duration_ms=(time.monotonic() - started_mono) * 1000,
            inputs=inputs_capped,
            outputs=_cap(results[node.id]),
            note="Using pinned mock data (live execution bypassed).",
            attempts=1,
            retries=0,
        )
        return

    emit("node.started", node_id=node.id, status="running")
    started_wall = datetime.now(UTC).isoformat()
    started_mono = time.monotonic()
    inputs_capped = _cap(input_items)


    max_attempts = max(1, int(node.settings.get("retry_max_attempts", 0) or 0) + 1)
    try:
        backoff = max(0.0, float(node.settings.get("retry_backoff_seconds", 2) or 2))
    except (TypeError, ValueError):
        backoff = 2.0
    retries: int = 0
    timeout = float(node.settings.get("timeout_seconds", 0)) or None

    if node.credentials and credential_resolver is not None:
        ctx.credentials = credential_resolver(node.credentials)
    else:
        ctx.credentials = {}
    # Phase 8: store the resolver on the context so sub-workflow nodes
    # can propagate credential resolution to child executions.
    ctx._credential_resolver = credential_resolver
    # Build node name→id mapping for $('Node Name') expressions
    node_name_map: dict[str, str] = {}
    for nid, gnode in graph.items():
        # Priority: explicit name > settings.label > display_name from registry
        node_name = getattr(gnode.node, 'name', '') or ''
        if not node_name:
            settings = getattr(gnode.node, 'settings', {}) or {}
            node_name = settings.get('label', '') or ''
        if not node_name:
            node_cls_ref = NODE_REGISTRY.get(gnode.node.type)
            if node_cls_ref is not None:
                node_name = getattr(node_cls_ref, 'display_name', '') or ''
        if node_name:
            node_name_map[node_name] = nid
            node_name_map[node_name.lower()] = nid
    context = expressions.build_context(
        input_items, results, ctx.workflow_id, ctx.execution_id, ctx.credentials,
        ctx.env_vars, node_name_map,
    )

    # Phase 23: connector routing — a connector registered for a
    # connector-only node type executes via op_execute() instead of a
    # node class. It receives the resolved params as its payload and
    # credentials via the context dict.
    if connector is not None:
        raw_op = (node.parameters or {}).get("operation", "")
        is_bulk = raw_op == "bulk"
        # Batch-aware per-item execution for loop scenarios: when input is a
        # batch of items (e.g., after Loop/Split), run the connector once per
        # item with per-item $json resolution, aggregating outputs. Bulk ops
        # remain single-call (they expect a batch).
        if len(input_items) > 1 and not is_bulk:
            all_outputs: list[dict[str, Any]] = []
            for single_item in input_items:
                per_ctx = dict(context)
                if isinstance(single_item, dict) and "json" in single_item and isinstance(single_item["json"], dict):
                    per_ctx["$json"] = single_item["json"]
                else:
                    per_ctx["$json"] = single_item
                per_params = expressions.resolve(node.parameters, per_ctx)
                if cancelled.is_set() or ctx.is_cancelled():
                    raise NodeCancelledError(node.id)
                connector_payload = per_params if isinstance(per_params, dict) else {}
                connector_context: dict[str, Any] = {
                    "credentials": ctx.credentials,
                    "execution_id": ctx.execution_id,
                    "workflow_id": ctx.workflow_id,
                    "input_items": [single_item],
                }
                # Per-item retry loop (mirrors _run_via_connector)
                _retries = 0
                while True:
                    try:
                        op = connector.op_execute("execute", connector_payload, connector_context)
                        if timeout:
                            op = asyncio.wait_for(op, timeout=timeout)
                        raw_result = await op
                        break
                    except asyncio.TimeoutError:
                        node_error = NodeTimeoutError(node.id, timeout)  # type: ignore[arg-type]
                        if _retries:
                            node_error.details = {"retries": _retries}
                    except NodeCancelledError:
                        raise
                    except ConnectorError as ce:  # type: ignore[name-defined]
                        node_error = NodeExecutionError(
                            str(ce), code=getattr(ce, "code", "CONNECTOR_ERROR"),
                            node_id=node.id, retryable=getattr(ce, "retryable", False),
                            details={"retries": _retries} if _retries else None,
                        )
                        if getattr(ce, "retry_after", None) is not None:
                            node_error.retry_after = ce.retry_after  # type: ignore[attr-defined]
                    if _retries + 1 >= max_attempts or not node_error.retryable:  # type: ignore[name-defined]
                        if node.settings.get("continue_on_error"):
                            all_outputs.append({"$error": node_error.to_dict(), "success": False, "item": single_item})
                            raw_result = None  # type: ignore[assignment]
                            break
                        raise node_error
                    _retries += 1
                    computed_delay = min(backoff * (2 ** (_retries - 1)), MAX_RETRY_BACKOFF_S)
                    delay = min(getattr(node_error, "retry_after", None) or computed_delay, MAX_RETRY_BACKOFF_S)
                    emit("node.retry", node_id=node.id, status="retry",
                         attempt=_retries, max_attempts=max_attempts,
                         retry_after_s=delay, error={"message": str(node_error), "code": node_error.code})
                    await asyncio.sleep(delay)
                    if cancelled.is_set() or ctx.is_cancelled():
                        raise NodeCancelledError(node.id)
                if raw_result is None:
                    continue  # error already recorded as item when continue_on_error
                output = raw_result.get("output", raw_result) if isinstance(raw_result, dict) else raw_result
                if isinstance(output, dict):
                    output_items = [output]
                elif isinstance(output, list):
                    output_items = output
                else:
                    output_items = [{"result": output}]
                # Preserve original item's fields (e.g., email) alongside connector result
                # so downstream IF/Create can still reference {{ $json.email }}
                merged_items = []
                for out in output_items:
                    if isinstance(out, dict) and isinstance(single_item, dict):
                        merged = {**single_item, **out}
                        # If single_item was {"json": {"email": ...}} wrapped, unwrap for downstream
                        if "json" in single_item and isinstance(single_item["json"], dict) and "email" not in merged:
                            merged["email"] = single_item["json"].get("email")
                        merged_items.append(merged)
                    else:
                        merged_items.append(out)
                all_outputs.extend(merged_items)
            results[node.id] = {"main": all_outputs}
            emit("node.completed", node_id=node.id, status="success")
            _add_step(
                result, node_id=node.id, node_type=node.type, status="success",
                started_at=started_wall,
                duration_ms=(time.monotonic() - started_mono) * 1000,
                inputs=inputs_capped,
                outputs=_cap({"main": all_outputs}),
                note=f"Batch connector '{connector.connector_id}' processed {len(input_items)} item(s).",
                attempts=1,
            )
            return
        params = expressions.resolve(node.parameters, context)
        try:
            await _run_via_connector(
                connector, node, gnode, results, ctx, result, emit,
                input_items, inputs_capped, params, cancelled, timeout,
                max_attempts, backoff, retries, started_wall, started_mono,
            )
        except NodeCancelledError:
            cancelled.set()
            emit("node.failed", node_id=node.id, status="cancelled")
            _add_step(
                result, node_id=node.id, node_type=node.type, status="cancelled",
                started_at=started_wall,
                duration_ms=(time.monotonic() - started_mono) * 1000,
                inputs=inputs_capped,
                note="Cancelled before/during connector execution.",
            )
        except NodeExecutionError as exc:
            exc.node_id = node.id
            conn_retries = int((exc.details or {}).get("retries") or 0)
            total_retries = retries + conn_retries
            _fail(
                node, gnode, results, result, exc, emit, graph,
                step_wall_started=started_wall, step_mono_started=started_mono, step_inputs=inputs_capped,
                attempts=max_attempts if total_retries else 1,
                retries=total_retries,
                note=(
                    f"Failed {max_attempts} attempt(s); {total_retries} failed"
                    f" retr{'y' if total_retries == 1 else 'ies'} before this error."
                    if total_retries else None
                ),
            )
        return

    assert node_cls is not None  # connector branch above returned when no node class exists
    # Phase 8: the engine context is exposed to self-resolving nodes so
    # they can extend it per evaluation ($node/$env stay reachable while
    # $json / $iterations evolve inside e.g. a loop).
    ctx.expression_context = context
    node_instance = node_cls()

    # Per-item execution for multi-item inputs:
    # When a Split/Loop fans out items, downstream nodes should process
    # each item individually with its own $json context. Self-resolving
    # nodes (IF, LoopWhile) already handle this internally.
    # Optimization: batch trace steps for 100+ items to avoid O(N) trace overhead.
    if (
        len(input_items) > 1
        and not node_instance.resolves_own_expressions
        and node_instance.output_handles == ["main"]
        and node.type not in ("split", "loop", "loop_over_items", "loop_while", "aggregate", "merge", "pagination", "sub_workflow")
    ):
        all_output_items: list[dict[str, Any]] = []
        batch_threshold = 100
        is_large_batch = len(input_items) > batch_threshold
        batch_outputs: list[dict[str, Any]] = []
        batch_started = time.monotonic()
        batch_errors: list[str] = []

        for idx, single_item in enumerate(input_items):
            per_context = dict(context)
            per_context["$json"] = single_item
            per_raw_params = expressions.resolve(node.parameters, per_context)
            per_params = node_instance.build_params(per_raw_params)
            per_started = time.monotonic()
            try:
                per_result = await _run_attempt(
                    node_cls, ctx, per_params, [single_item], cancelled, timeout, node.id,
                )
                if per_result.output_items:
                    all_output_items.extend(per_result.output_items)
                    if is_large_batch:
                        batch_outputs.extend(per_result.output_items)
                # Emit individual trace steps only for small batches
                if not is_large_batch:
                    per_elapsed = (time.monotonic() - per_started) * 1000
                    _add_step(
                        result, node_id=node.id, node_type=node.type, status="success",
                        started_at=datetime.now(UTC).isoformat(),
                        duration_ms=per_elapsed,
                        inputs=_cap({"main": [single_item]}),
                        outputs=_cap({"main": per_result.output_items or []}),
                        note=f"Per-item {idx + 1}/{len(input_items)}.",
                        attempts=1,
                    )
            except NodeExecutionError:
                raise
            except Exception as exc:
                batch_errors.append(f"Item {idx + 1}: {exc}")
                raise
            if cancelled.is_set() or ctx.is_cancelled():
                raise NodeCancelledError(node.id)

        # Emit a single batched trace step for large batches
        if is_large_batch:
            batch_elapsed = (time.monotonic() - batch_started) * 1000
            error_note = f" ({len(batch_errors)} errors)" if batch_errors else ""
            _add_step(
                result, node_id=node.id, node_type=node.type, status="success",
                started_at=datetime.now(UTC).isoformat(),
                duration_ms=batch_elapsed,
                inputs=_cap({"main": input_items[:5]}),  # Sample first 5
                outputs=_cap({"main": batch_outputs[:5]}),  # Sample first 5
                note=f"Per-item batch: {len(input_items)} items processed in {batch_elapsed:.0f}ms{error_note}.",
                attempts=1,
            )

        results[node.id] = {"main": all_output_items}
        emit("node.completed", node_id=node.id, status="success")
        return

    if node_instance.resolves_own_expressions:
        raw_params = node.parameters
    else:
        raw_params = expressions.resolve(node.parameters, context)
    params = node_instance.build_params(raw_params)

    # Phase 8: idempotency — for nodes declared idempotent, check the
    # KV store before execution and cache the result on success.  The
    # key is a hash of (workflow_id, execution_id, node_id, params)
    # so the same node with different parameters is not confused.
    _idem_key: str | None = None
    if node_instance.idempotency == "idempotent":
        _idem_key = _idempotency_key(ctx.workflow_id, ctx.execution_id, node.id, raw_params)
        cached = await ctx.storage.get(_idem_key)
        if cached is not None:
            results[node.id] = cached
            emit("node.completed", node_id=node.id, status="success", cached=True)
            _add_step(
                result, node_id=node.id, node_type=node.type, status="success",
                started_at=started_wall,
                duration_ms=(time.monotonic() - started_mono) * 1000,
                inputs=inputs_capped,
                outputs=_cap(cached),
                note="Idempotent cache hit; skipped re-execution.",
            )
            return

    try:
        while True:
            try:
                node_result = await _run_attempt(
                    node_cls, ctx, params, input_items, cancelled, timeout, node.id,
                )
                break
            except NodeExecutionError as exc:
                if retries + 1 >= max_attempts or not exc.retryable:
                    raise
                retries += 1
                delay = min(backoff * (2 ** (retries - 1)), MAX_RETRY_BACKOFF_S)
                emit("node.retry", node_id=node.id, status="retry",
                     attempt=retries, max_attempts=max_attempts,
                     retry_after_s=delay, error=exc.to_dict())
                await asyncio.sleep(delay)
                if cancelled.is_set() or ctx.is_cancelled():
                    raise NodeCancelledError(node.id)

        if node_result.output_by_handle is not None:
            results[node.id] = node_result.output_by_handle
        else:
            results[node.id] = {"main": node_result.output_items or []}
        # Phase 8: cache the result for idempotent nodes so subsequent
        # runs with the same parameters skip re-execution.
        if _idem_key is not None:
            await ctx.storage.set(_idem_key, results[node.id])
        emit("node.completed", node_id=node.id, status="success")
        _add_step(
            result, node_id=node.id, node_type=node.type, status="success",
            started_at=started_wall,
            duration_ms=(time.monotonic() - started_mono) * 1000,
            inputs=inputs_capped,
            outputs=_cap(results[node.id]),
            note=(f"Succeeded after {retries} retr{'y' if retries == 1 else 'ies'}."
                  if retries > 0 else None),
            attempts=retries + 1,
            retries=retries,
        )
    except NodeCancelledError:
        cancelled.set()
        emit("node.failed", node_id=node.id, status="cancelled")
        _add_step(
            result, node_id=node.id, node_type=node.type, status="cancelled",
            started_at=started_wall,
            duration_ms=(time.monotonic() - started_mono) * 1000,
            inputs=inputs_capped,
            note="Cancelled before/during execution.",
        )
    except NodeExecutionError as exc:
        exc.node_id = node.id
        _fail(
            node, gnode, results, result, exc, emit, graph,
            step_wall_started=started_wall, step_mono_started=started_mono, step_inputs=inputs_capped,
            attempts=retries + 1, retries=retries,
            note=(
                f"Failed {max_attempts} attempt(s); {retries} failed"
                f" retr{'y' if retries == 1 else 'ies'} before this error."
                if retries > 0 else None
            ),
        )
    except Exception as exc:  # any unexpected failure becomes a typed error
        _fail(
            node, gnode, results, result,
            NodeExecutionError(str(exc), code="NODE_ERROR", node_id=node.id), emit, graph,
            step_wall_started=started_wall, step_mono_started=started_mono, step_inputs=inputs_capped,
            attempts=retries + 1, retries=retries,
            note=(f"Failed {max_attempts} attempt(s); {retries} failed"
                  f" retr{'y' if retries == 1 else 'ies'} before this error."
                  if retries > 0 else None),
        )


async def _run_attempt(
    node_cls: Any, ctx: NodeContext, params: Any, input_items: list[dict],
    cancelled: asyncio.Event, timeout: float | None, node_id: str,
) -> NodeResult:
    if timeout:
        try:
            return await asyncio.wait_for(
                _run_with_cancellation(node_cls(), ctx, params, input_items, cancelled),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise NodeTimeoutError(node_id, timeout)
    return await _run_with_cancellation(node_cls(), ctx, params, input_items, cancelled)


async def _run_with_cancellation(
    node_instance: Any, ctx: NodeContext, params: Any, input_items: list[dict], cancelled: asyncio.Event,
) -> NodeResult:
    if cancelled.is_set() or ctx.is_cancelled():
        raise NodeCancelledError()
    return await node_instance.run(ctx, params, input_items)


def _gather_input(gnode: Any, results: NodeResults) -> list[dict[str, Any]]:
    """Merge items from all parent edges, respecting source handles (spec 8.2 combine)."""
    merged: list[dict[str, Any]] = []
    for parent_id, source_handle in gnode.input_connections:
        by_handle = results.get(parent_id, {})
        merged.extend(by_handle.get(source_handle, []))
    return merged


def _fail(
    node: WorkflowNode,
    gnode: Any,
    results: NodeResults,
    result: ExecutionResult,
    error: NodeExecutionError,
    emit: Callable[..., Any],
    graph: dict,
    *,
    step_wall_started: str | None = None,
    step_mono_started: float | None = None,
    step_inputs: list[dict[str, Any]] | None = None,
    note: str | None = None,
    attempts: int = 1,
    retries: int = 0,
) -> None:
    now = datetime.now(UTC).isoformat()
    started_at = step_wall_started if step_wall_started is not None else now
    duration_ms = (time.monotonic() - step_mono_started) * 1000 if step_mono_started is not None else 0.0
    emit("node.failed", node_id=node.id, status="error", error=error.to_dict())

    if node.settings.get("continue_on_error"):
        # Execution continues; the $error item flows downstream (spec 8.3).
        results[node.id] = {"main": [{"$error": error.to_dict()}]}
        emit("node.completed", node_id=node.id, status="success")
        _add_step(
            result, node_id=node.id, node_type=node.type, status="error",
            started_at=started_at, duration_ms=duration_ms,
            inputs=step_inputs, outputs=_cap(results[node.id]), error=error.to_dict(),
            note=note, attempts=max(1, attempts), retries=max(0, retries),
        )
    else:
        result.node_errors[node.id] = error
        result.error = error
        _add_step(
            result, node_id=node.id, node_type=node.type, status="error",
            started_at=started_at, duration_ms=duration_ms,
            inputs=step_inputs, outputs=_cap(results.get(node.id)), error=error.to_dict(),
            note=note, attempts=max(1, attempts), retries=max(0, retries),
        )
        for child in _descendants(graph, gnode):
            # In parallel mode a descendant may still be fed by another
            # live branch (wait_for_one, or a sibling parent): only
            # pre-skip it when every parent has failed. Already-run
            # nodes are never retro-skipped.
            if child in result.skipped or child in results:
                continue
            parents = graph[child].input_node_ids
            if not parents or any(p not in result.node_errors for p in parents):
                continue
            result.skipped.append(child)
            _add_step(
                result, node_id=child, node_type=graph[child].node.type, status="skipped",
                started_at=now, duration_ms=0,
                note=f"Parent node '{node.id}' failed; step was not executed.",
            )


def _descendants(graph: dict, gnode: Any) -> list[str]:
    """All transitive downstream node ids (marked skipped on failure)."""
    seen: set[str] = set()
    stack = list(gnode.output_node_ids)
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(graph[nid].output_node_ids)
    return list(seen)


def _idempotency_key(workflow_id: str, execution_id: str, node_id: str, params: Any) -> str:
    """Deterministic key for idempotency caching.  The key covers the
    workflow, execution, node identity and resolved parameters so the
    same node with different inputs is not confused."""
    raw = json.dumps(
        {"wf": workflow_id, "exec": execution_id, "node": node_id, "params": params},
        sort_keys=True, default=str,
    )
    return f"idem:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"
