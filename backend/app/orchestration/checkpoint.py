"""Deterministic seed planning for a run's first checkpoint.

A resumed, retried, or debugger-started run must reuse persisted node
outputs instead of repeating upstream side effects. The runtime loads the
execution rows; this module decides — from the job payload and the
persisted outputs — which nodes are replayed and which must run again.

Everything here is pure (no database or control-plane imports) so the seed
contract can be tested directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, cast

from app.engine.graph import descendant_ids

NodeResults = dict[str, dict[str, list[dict[str, Any]]]]
SeedMode = Literal["fresh", "approval", "node_retry", "run_node", "run_to_node"]


@dataclass(frozen=True)
class RunSeed:
    """The initial results/storage a run starts from, plus derived topology."""

    mode: SeedMode
    initial_results: NodeResults | None = None
    storage_seed: dict[str, Any] | None = None
    upstream: set[str] = field(default_factory=set)
    doomed: set[str] = field(default_factory=set)
    decision: dict[str, Any] | None = None
    retry_source_id: str | None = None
    run_source_id: str | None = None


def seed_mode(payload: Mapping[str, Any] | None) -> SeedMode:
    """Pick the seed directive, with strict precedence.

    Approval wins over everything (a resumed pause is authoritative), then
    safe node retry, then run-node, then run-to-node. Absent directives mean
    a fresh run.
    """
    data = payload or {}
    if data.get("_approval_data") is not None:
        return "approval"
    if data.get("_retry_from_node"):
        return "node_retry"
    if data.get("_run_node"):
        return "run_node"
    if data.get("_run_to_node"):
        return "run_to_node"
    return "fresh"


def ancestor_ids(connections: list[dict], target_id: str) -> set[str]:
    """Return all upstream ancestor node IDs of *target_id* (BFS)."""
    parent_map: dict[str, set[str]] = {}
    for conn in connections:
        src = conn.get("source", "")
        tgt = conn.get("target", "")
        parent_map.setdefault(tgt, set()).add(src)

    visited: set[str] = set()
    queue = deque(parent_map.get(target_id, set()))
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        queue.extend(parent_map.get(nid, set()) - visited)
    return visited


def seed_from_approval(
    outputs: Mapping[str, Any] | None,
    decision: dict[str, Any] | None,
) -> RunSeed:
    """Replay every prior output except the paused node itself.

    The paused node must run again to consume the recorded decision.
    """
    paused_node = (decision or {}).get("node_id")
    initial_results: NodeResults | None = None
    if isinstance(outputs, dict):
        initial_results = cast(
            NodeResults,
            {
                nid: by_handle
                for nid, by_handle in outputs.items()
                if nid != paused_node
            },
        )
    return RunSeed(
        mode="approval",
        initial_results=initial_results,
        storage_seed={"_approval_data": decision},
        decision=decision,
    )


def seed_from_node_retry(
    connections: list[dict],
    retry_from_node: str,
    source_outputs: Mapping[str, Any] | None,
) -> RunSeed:
    """Seed upstream outputs, but never the failed node or its descendants."""
    doomed = descendant_ids(connections, retry_from_node) | {retry_from_node}
    initial_results: NodeResults | None = None
    if isinstance(source_outputs, dict):
        initial_results = cast(
            NodeResults,
            {
                nid: by_handle
                for nid, by_handle in source_outputs.items()
                if nid not in doomed
            },
        )
    return RunSeed(
        mode="node_retry",
        initial_results=initial_results,
        doomed=doomed,
    )


def seed_from_run_node(
    workflow_data: Mapping[str, Any] | None,
    connections: list[dict],
    run_node: str,
    source_outputs: Mapping[str, Any] | None,
) -> RunSeed:
    """Seed every other node so only *run_node* executes.

    Upstream nodes replay their real cached outputs when available and fall
    back to a single empty item otherwise (so the target still receives an
    input). Downstream nodes are seeded with an empty array and skipped.
    """
    upstream = ancestor_ids(connections, run_node)
    outputs = source_outputs if isinstance(source_outputs, dict) else {}
    all_nodes = {n.get("id") for n in (workflow_data or {}).get("nodes", [])}

    initial_results: NodeResults = {}
    for nid in all_nodes:
        if nid == run_node:
            continue
        if nid in outputs:
            raw = outputs[nid]
            if isinstance(raw, dict):
                initial_results[nid] = raw
            elif isinstance(raw, list):
                initial_results[nid] = {"main": raw}
            else:
                initial_results[nid] = {"main": [raw]}
        elif nid in upstream:
            initial_results[nid] = {"main": [{}]}
        else:
            initial_results[nid] = {"main": []}

    return RunSeed(
        mode="run_node",
        initial_results=initial_results,
        upstream=upstream,
    )


def seed_from_run_to_node(connections: list[dict], run_to_node: str) -> RunSeed:
    """Seed all downstream nodes as skipped so only the chain up to the target runs."""
    downstream = descendant_ids(connections, run_to_node) - {run_to_node}
    initial_results = cast(
        NodeResults,
        {nid: {"main": []} for nid in downstream},
    )
    return RunSeed(mode="run_to_node", initial_results=initial_results)


def plan_seed(
    payload: Mapping[str, Any] | None,
    *,
    workflow_data: Mapping[str, Any] | None = None,
    outputs: Mapping[str, Any] | None = None,
    retry_outputs: Mapping[str, Any] | None = None,
    run_outputs: Mapping[str, Any] | None = None,
) -> RunSeed:
    """Select and build the seed for *payload*'s directive.

    ``outputs`` are the current execution's persisted outputs (approval
    resume), ``retry_outputs`` come from the retry source execution, and
    ``run_outputs`` from the run-node source execution. Callers keep all
    database access; this function only shapes the values.
    """
    data = payload or {}
    mode = seed_mode(data)
    connections = cast(list[dict], (workflow_data or {}).get("connections") or [])

    if mode == "approval":
        return seed_from_approval(
            outputs,
            cast(dict[str, Any] | None, data.get("_approval_data")),
        )

    if mode == "node_retry":
        seed = seed_from_node_retry(
            connections,
            cast(str, data.get("_retry_from_node")),
            retry_outputs,
        )
        source_id = data.get("_retry_source") or None
        return replace(seed, retry_source_id=cast(str | None, source_id))

    if mode == "run_node":
        seed = seed_from_run_node(
            workflow_data,
            connections,
            cast(str, data.get("_run_node")),
            run_outputs,
        )
        source_id = data.get("_source_execution") or None
        return replace(seed, run_source_id=cast(str | None, source_id))

    if mode == "run_to_node":
        return seed_from_run_to_node(
            connections,
            cast(str, data.get("_run_to_node")),
        )

    return RunSeed(mode="fresh")
