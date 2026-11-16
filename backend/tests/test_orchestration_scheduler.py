"""Tests for the extracted ready-set graph scheduler.

The scheduler is exercised with fake graph nodes, results and a fake
``execute_node`` callback so the scheduling semantics are verified in
isolation from node implementations.

``schedule_graph`` uses ``initial_results`` as the live results mapping
(the engine passes a fresh dict seeded from persisted outputs). The harness
owns that mapping so fake nodes can record outputs exactly like ``_run_one``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.orchestration.scheduler import schedule_graph


@dataclass
class FakeNode:
    id: str
    type: str = "fake"
    name: str = ""
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeGraphNode:
    node: FakeNode
    input_node_ids: list[str] = field(default_factory=list)
    output_node_ids: list[str] = field(default_factory=list)
    input_connections: list[tuple[str, str]] = field(default_factory=list)
    back_edges: list[str] = field(default_factory=list)


@dataclass
class FakeResult:
    status: str = "success"
    results: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    node_errors: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: Any = None
    paused: bool = False
    paused_node_id: str | None = None
    pause_info: dict[str, Any] | None = None


class FakeCtx:
    def __init__(self) -> None:
        self._cancelled = False
        self.node_id: str | None = None

    def is_cancelled(self) -> bool:
        return self._cancelled


def make_graph(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    *,
    settings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, FakeGraphNode]:
    settings = settings or {}
    graph = {
        nid: FakeGraphNode(node=FakeNode(nid, settings=dict(settings.get(nid, {}))))
        for nid in node_ids
    }
    for source, target in edges:
        graph[source].output_node_ids.append(target)
        graph[target].input_node_ids.append(source)
        graph[target].input_connections.append((source, "main"))
    return graph


class Harness:
    """Runs schedule_graph with a fake ctx, live result store and events."""

    def __init__(self, max_parallelism: int = 8) -> None:
        self.ctx = FakeCtx()
        self.cancelled = asyncio.Event()
        self.events: list[dict[str, Any]] = []
        self.results: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.max_parallelism = max_parallelism

    def emit(self, name: str, *, node_id: str | None = None, status: str | None = None, **extra: Any) -> None:
        self.events.append({"event": name, "node_id": node_id, "status": status, **extra})

    async def run(self, graph: dict[str, FakeGraphNode], result: FakeResult, execute_node: Any) -> None:
        await schedule_graph(
            graph=graph,
            trigger_items=[{"seed": True}],
            ctx=self.ctx,
            result=result,
            emit=self.emit,
            cancelled=self.cancelled,
            execute_node=execute_node,
            max_parallelism=self.max_parallelism,
            initial_results=self.results,
        )


# ── readiness and merge modes ────────────────────────────────────────────────


async def test_roots_run_once_and_child_starts_after_all_parents():
    graph = make_graph(["a", "b", "child"], [("a", "child"), ("b", "child")])
    result = FakeResult()
    harness = Harness()
    calls: list[str] = []
    completed: set[str] = set()
    seeds: dict[str, Any] = {}

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        calls.append(nid)
        seeds[nid] = seed
        if nid == "child":
            assert completed == {"a", "b"}, "child started before every parent finished"
        completed.add(nid)
        harness.results[nid] = {"main": []}

    await harness.run(graph, result, execute_node)

    assert calls.count("a") == 1
    assert calls.count("b") == 1
    assert calls.count("child") == 1
    assert seeds["a"] == [{"seed": True}]
    assert seeds["child"] is None
    assert result.status == "success"
    assert any(ev["event"] == "execution.completed" for ev in harness.events)


@pytest.mark.parametrize(
    ("merge_mode", "join_waits_for_slow_parent"),
    [("wait_for_all", True), ("wait_for_one", False)],
)
async def test_merge_modes_control_whether_the_join_waits(merge_mode, join_waits_for_slow_parent):
    graph = make_graph(
        ["slow", "fast", "join"],
        [("slow", "join"), ("fast", "join")],
        settings={"join": {"merge_mode": merge_mode}},
    )
    result = FakeResult()
    harness = Harness()
    calls: list[str] = []
    slow_finished = asyncio.Event()
    join_started_before_slow_finished: bool | None = None

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        nonlocal join_started_before_slow_finished
        calls.append(nid)
        if nid == "slow":
            await asyncio.sleep(0.15)
            slow_finished.set()
        elif nid == "join":
            join_started_before_slow_finished = not slow_finished.is_set()
        harness.results[nid] = {"main": []}

    await harness.run(graph, result, execute_node)

    assert join_started_before_slow_finished is (not join_waits_for_slow_parent)
    assert set(calls) == {"slow", "fast", "join"}
    assert all(calls.count(nid) == 1 for nid in calls)
    assert result.status == "success"


async def test_parallelism_cap_limits_concurrent_nodes():
    node_ids = [f"n{i}" for i in range(6)]
    graph = make_graph(node_ids, [])
    result = FakeResult()
    harness = Harness(max_parallelism=2)
    calls: list[str] = []
    running = 0
    max_seen = 0

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        nonlocal running, max_seen
        calls.append(nid)
        running += 1
        max_seen = max(max_seen, running)
        try:
            await asyncio.sleep(0.03)
        finally:
            running -= 1
        harness.results[nid] = {"main": []}

    await harness.run(graph, result, execute_node)

    assert max_seen == 2
    assert sorted(calls) == sorted(node_ids)
    assert result.status == "success"


async def test_seeded_nodes_are_not_executed_and_unblock_children():
    graph = make_graph(["a", "b"], [("a", "b")])
    result = FakeResult()
    harness = Harness()
    harness.results["a"] = {"main": [{"from": "checkpoint"}]}
    calls: list[str] = []

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        calls.append(nid)
        assert seed is None
        harness.results[nid] = {"main": [{"from": "live"}]}

    await harness.run(graph, result, execute_node)

    assert calls == ["b"]
    assert result.results["a"] == {"main": [{"from": "checkpoint"}]}
    assert result.results["b"] == {"main": [{"from": "live"}]}
    assert result.status == "success"


# ── pause, cancel and terminal state ─────────────────────────────────────────


async def test_pause_stops_new_scheduling_but_drains_active_siblings():
    graph = make_graph(["gate", "sibling", "after"], [("gate", "after")])
    result = FakeResult()
    harness = Harness()
    calls: list[str] = []
    sibling_finished = asyncio.Event()

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        calls.append(nid)
        if nid == "gate":
            result.paused = True
            result.paused_node_id = "gate"
            result.pause_info = {"message": "Approve"}
        elif nid == "sibling":
            await asyncio.sleep(0.1)
            sibling_finished.set()
        harness.results[nid] = {"main": []}

    await harness.run(graph, result, execute_node)

    assert sibling_finished.is_set(), "active sibling was not drained"
    assert "after" not in calls
    assert "after" not in result.results
    assert "after" not in result.skipped
    assert result.status == "waiting_approval"
    assert result.results["gate"] == {"main": []}
    assert result.results["sibling"] == {"main": []}
    assert not any(ev["event"] == "execution.completed" for ev in harness.events)


async def test_cancel_cancels_active_nodes_and_waits_bounded():
    graph = make_graph(["fast", "slow", "orphan"], [("slow", "orphan")])
    result = FakeResult()
    harness = Harness()
    calls: list[str] = []
    slow_cancelled = asyncio.Event()

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        calls.append(nid)
        if nid == "fast":
            harness.cancelled.set()
        elif nid == "slow":
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise
        harness.results[nid] = {"main": []}

    started = time.monotonic()
    await harness.run(graph, result, execute_node)
    elapsed = time.monotonic() - started

    assert slow_cancelled.is_set(), "active node was not cancelled"
    assert elapsed < 2.0, "cancellation drain was not bounded"
    assert result.status == "cancelled"
    assert any(ev["event"] == "execution.cancelled" for ev in harness.events)
    assert any(ev["event"] == "node.failed" and ev["node_id"] == "slow" for ev in harness.events)


async def test_unreachable_nodes_are_marked_skipped():
    graph = make_graph(["root", "orphan"], [("root", "orphan")])
    result = FakeResult()
    harness = Harness()
    calls: list[str] = []

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        calls.append(nid)
        harness.cancelled.set()

    await harness.run(graph, result, execute_node)

    assert calls == ["root"]
    assert result.skipped == ["orphan"]
    step = next(s for s in result.trace if s["node_id"] == "orphan")
    assert step["status"] == "skipped"
    assert step["note"] == "Execution cancelled; step was not executed."
    assert result.status == "cancelled"


# ── cycle fallback ──────────────────────────────────────────────────────────


async def test_cycle_fallback_schedules_node_with_fewest_incomplete_parents():
    # a <-> b is a cycle; c and a each wait on two incomplete parents while b
    # waits only on a, so b is the unique cycle-break choice.
    graph = make_graph(
        ["a", "b", "c"],
        [("a", "b"), ("b", "c"), ("c", "a"), ("a", "c"), ("b", "a")],
    )
    result = FakeResult()
    harness = Harness()
    calls: list[str] = []

    async def execute_node(nid: str, seed: list[dict[str, Any]] | None) -> None:
        calls.append(nid)
        harness.results[nid] = {"main": []}

    await harness.run(graph, result, execute_node)

    assert calls, "cycle fallback did not run any node"
    assert calls[0] == "b", f"cycle fallback chose {calls[0]!r}, expected 'b' (fewest incomplete parents)"
    assert sorted(calls) == ["a", "b", "c"]
    assert all(calls.count(nid) == 1 for nid in calls)
    assert result.status == "success"
