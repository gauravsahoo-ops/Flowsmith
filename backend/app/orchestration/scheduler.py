"""Ready-set graph scheduler extracted from the execution engine (spec 8.2).

The scheduler owns *when* a node runs: readiness (parents finished), merge
modes (``wait_for_all`` / ``wait_for_one``), the parallelism semaphore, pause
gating, bounded cancellation, the cycle fallback and the final status/event
decision. It does not know how a node executes: the engine injects an
``execute_node`` callback that runs the node with tracing and converts errors
into ``_fail`` records.

``initial_results`` doubles as the live results store. The engine passes a
fresh mapping seeded with persisted outputs; the scheduler marks those ids as
scheduled (so they are never re-executed), clears them from their children's
pending sets and records every new node output in the same mapping. The
public ``ExecutionResult.results`` field is only assigned on the pause and
final paths, matching the previous behavior exactly.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from app.engine.executor import ExecutionResult
    from app.engine.node_base import NodeContext
    from app.schemas.workflow import WorkflowNode

DEFAULT_MAX_PARALLELISM = 8

MERGE_MODES = ("wait_for_all", "wait_for_one", "combine")

NodeResults = dict[str, dict[str, list[dict[str, Any]]]]


def _merge_mode(node: WorkflowNode) -> str:
    mode = node.settings.get("merge_mode", "wait_for_all")
    return mode if mode in MERGE_MODES else "wait_for_all"


def _add_trace_step(result: Any, **kwargs: Any) -> None:
    """Append a trace row via the engine's canonical step builder.

    Imported lazily: ``app.engine.executor`` imports this module, so a
    module-level import would be circular. The builder is deliberately shared
    so its ``_cap``/telemetry behavior (and test patch targets) stay in one
    place.
    """
    from app.engine.executor import _add_step

    _add_step(result, **kwargs)


def _pending_map(graph: dict[str, Any], seeded: set[str]) -> dict[str, set[str]]:
    """Parents each node still waits for, with seeded parents cleared."""
    pending: dict[str, set[str]] = {
        nid: set(gnode.input_node_ids) for nid, gnode in graph.items()
    }

    # Children whose parents are all pre-seeded become ready immediately.
    for nid in seeded:
        gnode = graph.get(nid)
        if gnode is None:
            continue
        for child in gnode.output_node_ids:
            pending[child].discard(nid)
    return pending


def _cycle_candidate(
    graph: dict[str, Any],
    scheduled: set[str],
    results: NodeResults,
    result: ExecutionResult,
    cancelled: asyncio.Event,
    ctx: NodeContext,
) -> str | None:
    """Node with the fewest incomplete parents, or None when all are done.

    When every active task has drained and nodes remain unscheduled they are
    part of a cycle. Breaking it by running the node with the fewest remaining
    incomplete parents gives that node empty input (its parent has not
    produced output yet), which is the intended cycle-breaking semantics.
    """
    if cancelled.is_set() or ctx.is_cancelled():
        return None
    unscheduled = [
        nid for nid in graph
        if nid not in scheduled
        and nid not in result.skipped
        and nid not in result.node_errors
    ]
    if not unscheduled:
        return None
    unscheduled.sort(
        key=lambda nid: sum(1 for p in graph[nid].input_node_ids if p not in results)
    )
    return unscheduled[0]


def _mark_unreachable_skipped(
    graph: dict[str, Any],
    scheduled: set[str],
    results: NodeResults,
    result: ExecutionResult,
    cancelled: asyncio.Event,
    ctx: NodeContext,
) -> None:
    """Record nodes that could never become ready as skipped."""
    for nid in graph:
        if nid in scheduled or nid in result.skipped or nid in results or nid in result.node_errors:
            continue
        result.skipped.append(nid)
        _add_trace_step(
            result,
            node_id=nid,
            node_type=graph[nid].node.type,
            status="skipped",
            started_at=datetime.now(UTC).isoformat(),
            duration_ms=0,
            note=(
                "Execution cancelled; step was not executed."
                if (cancelled.is_set() or ctx.is_cancelled())
                else "Parent node failed; step was not executed."
            ),
        )


async def _drain_active(active: set[asyncio.Task[None]]) -> None:
    """Cancel active node tasks and wait a bounded time for them to unwind."""
    for task in list(active):
        if not task.done():
            task.cancel()
    if active:
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait(tuple(active), timeout=2.0)


async def schedule_graph(
    *,
    graph: dict[str, Any],
    trigger_items: list[dict[str, Any]],
    ctx: NodeContext,
    result: ExecutionResult,
    emit: Callable[..., Any],
    cancelled: asyncio.Event,
    execute_node: Callable[[str, list[dict[str, Any]] | None], Awaitable[None]],
    max_parallelism: int = DEFAULT_MAX_PARALLELISM,
    initial_results: NodeResults | None = None,
) -> None:
    """Run the graph's ready-set scheduler.

    Independent branches run concurrently; a node starts once its parents are
    done. ``execute_node`` is injected by the engine and receives
    ``(node_id, seed_items)`` where ``seed_items`` is the trigger payload for
    root nodes and ``None`` for connected nodes.

    ``initial_results`` is the live results mapping (see module docstring):
    its keys are treated as already-scheduled nodes, and executed nodes write
    their outputs into it.
    """
    results: NodeResults = initial_results if initial_results is not None else {}
    sem = asyncio.Semaphore(max_parallelism)
    active: set[asyncio.Task[None]] = set()
    scheduled: set[str] = set(results)
    pending = _pending_map(graph, scheduled)

    async def _run_node(nid: str) -> None:
        gnode = graph[nid]
        seed = trigger_items if not gnode.input_connections else None
        try:
            async with sem:
                await execute_node(nid, seed)
        except asyncio.CancelledError:
            # The injected callback owns cancellation conversion while a node
            # runs; reaching here means the task was cancelled while waiting
            # for a parallelism slot. Mirror the callback's cancelled-node
            # record so the branch is not silently lost.
            cancelled.set()
            ctx._cancelled = True
            emit("node.failed", node_id=gnode.node.id, status="cancelled")
            _add_trace_step(
                result, node_id=gnode.node.id, node_type=gnode.node.type, status="cancelled",
                started_at=datetime.now(UTC).isoformat(), duration_ms=0,
                note="Cancelled during execution.",
            )
            return

        if result.paused:
            # A paused node stops the run: never schedule its descendants
            # (they resume from persisted outputs, not from an empty branch).
            return
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
        if (
            result.paused
            or nid in scheduled
            or cancelled.is_set()
            or ctx.is_cancelled()
        ):
            return
        scheduled.add(nid)
        task = asyncio.create_task(_run_node(nid))
        active.add(task)
        task.add_done_callback(active.discard)

    for nid in graph:
        if not graph[nid].input_connections:
            _schedule(nid)
        elif not pending[nid]:
            # All parents were pre-seeded (durable resume): ready now.
            _schedule(nid)

    try:
        while True:
            if cancelled.is_set() or ctx.is_cancelled():
                break
            while active:
                done, _ = await asyncio.wait(tuple(active), return_when=asyncio.FIRST_COMPLETED)
                active.difference_update(done)
                if cancelled.is_set() or ctx.is_cancelled():
                    break

            if cancelled.is_set() or ctx.is_cancelled():
                break
            # A pause stops new scheduling but lets already-running sibling
            # branches finish so their side effects and outputs are recorded.
            if result.paused:
                break

            candidate = _cycle_candidate(graph, scheduled, results, result, cancelled, ctx)
            if candidate is None:
                break
            _schedule(candidate)
    finally:
        if cancelled.is_set() or ctx.is_cancelled():
            await _drain_active(active)

    if result.paused:
        # Preserve the checkpoint. Unscheduled descendants are intentionally
        # neither executed nor marked skipped: the resume run replays the
        # paused node and continues from there.
        result.results = results
        result.status = "waiting_approval"
        result.trace.sort(key=lambda s: s["started_at"])
        return

    _mark_unreachable_skipped(graph, scheduled, results, result, cancelled, ctx)

    result.results = results
    result.trace.sort(key=lambda s: s["started_at"])  # chronological across parallel branches
    if result.status != "timeout" and (cancelled.is_set() or ctx.is_cancelled()):
        result.status = "cancelled"
        emit("execution.cancelled", status="cancelled")
    elif result.error:
        result.status = "failed"
        emit("execution.failed", status="failed")
    else:
        result.status = "success"
        emit("execution.completed", status="success")
