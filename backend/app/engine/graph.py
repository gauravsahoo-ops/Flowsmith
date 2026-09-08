"""Graph construction, validation and topological sorting (spec 8.1-8.2, 24.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.schemas.workflow import Connection, Workflow, WorkflowNode
from app.engine.errors import WorkflowValidationError
from app.nodes.registry import NODE_REGISTRY

MERGE_MODES = ("wait_for_all", "wait_for_one", "combine")

_NODE_SETTING_CHECKS: dict[str, Callable[[Any], bool]] = {
    "merge_mode": lambda v: v in MERGE_MODES,
    "retry_max_attempts": lambda v: isinstance(v, int) and 0 <= v <= 10,
    "retry_backoff_seconds": lambda v: isinstance(v, (int, float)) and v >= 0,
    "timeout_seconds": lambda v: isinstance(v, (int, float)) and v > 0,
    "continue_on_error": lambda v: isinstance(v, bool),
}

_WORKFLOW_SETTING_CHECKS: dict[str, Callable[[Any], bool]] = {
    "timeout_seconds": lambda v: isinstance(v, (int, float)) and v > 0,
    "max_parallelism": lambda v: isinstance(v, int) and 1 <= v <= 32,
}


@dataclass
class GraphNode:
    node: WorkflowNode
    input_node_ids: list[str] = field(default_factory=list)
    output_node_ids: list[str] = field(default_factory=list)
    input_connections: list[tuple[str, str]] = field(default_factory=list)  # (source_id, source_handle)
    back_edges: list[str] = field(default_factory=list)  # source_node_ids that are visual loop back-edges


Graph = dict[str, GraphNode]


def build_graph(workflow: Workflow) -> Graph:
    """Convert nodes + connections into an adjacency structure.

    Cycles are now allowed in the graph topology. The executor runs
    each node at most once per pass; if a cycle is present, the node
    is scheduled in topological order (the cycle edges are just extra
    incoming edges for ordering purposes). Visual-loop back-edge
    detection is preserved for legacy callers but the set is always
    empty.
    """
    graph: Graph = {}
    for node in workflow.nodes:
        graph[node.id] = GraphNode(node=node)
    for conn in workflow.connections:
        if conn.source in graph:
            graph[conn.source].output_node_ids.append(conn.target)
        if conn.target in graph:
            graph[conn.target].input_node_ids.append(conn.source)
            graph[conn.target].input_connections.append((conn.source, conn.sourceHandle))

    return graph


def validate_graph(workflow: Workflow, graph: Graph | None = None, validate_params: bool = True) -> None:
    """Structural validation. Raises WorkflowValidationError with issues.

    Rules (spec 24.3): unique node ids, known node types, every
    connection references existing nodes, handles are valid for the
    node types. Cycles and duplicate edges are permitted in the graph
    topology; the executor handles them at runtime.

    `validate_params` (default True) additionally validates each node's
    parameters against its schema. The API saves drafts with
    ``validate_params=False`` so an unconfigured node never blocks
    saving; the engine re-validates with full parameter checks at run
    time (executor.py), where failures surface as node errors.
    """
    issues: list[dict] = []

    if not workflow.nodes:
        # Allow empty workflows — user may clear canvas to add notes/comments
        # No structural issues for empty graph
        return

    node_ids: set[str] = set()
    for node in workflow.nodes:
        if node.id in node_ids:
            issues.append({"code": "DUPLICATE_NODE_ID", "node_id": node.id,
                           "field": "id", "message": f"Duplicate node id '{node.id}'."})
        node_ids.add(node.id)

        for key, check in _NODE_SETTING_CHECKS.items():
            if key in node.settings and not check(node.settings[key]):
                issues.append({"code": "INVALID_SETTING", "node_id": node.id,
                               "field": f"settings.{key}",
                               "message": f"Invalid value for settings.{key}: {node.settings[key]!r}."})

        node_cls = NODE_REGISTRY.get(node.type)
        if node_cls is None:
            # Phase 23: accept node types handled by a registered connector
            from app.connectors import ensure_builtin_connectors, get_registry as _get_connector_registry

            ensure_builtin_connectors()
            _connector_registry = _get_connector_registry()
            if _connector_registry.primary_for_node_type(node.type) is not None:
                continue
            issues.append({"code": "UNKNOWN_NODE_TYPE", "node_id": node.id,
                           "field": "type", "message": f"Unknown node type '{node.type}'."})
            continue

        if validate_params:
            try:
                node_cls().build_params(node.parameters)
            except Exception as exc:
                issues.append({"code": "INVALID_PARAMETER", "node_id": node.id,
                               "field": "parameters", "message": str(exc)})

    for key, check in _WORKFLOW_SETTING_CHECKS.items():
        if key in workflow.settings and not check(workflow.settings[key]):
            issues.append({"code": "INVALID_SETTING", "node_id": None,
                           "field": f"settings.{key}",
                           "message": f"Invalid value for settings.{key}: {workflow.settings[key]!r}."})

    for conn in workflow.connections:
        if conn.source not in node_ids:
            issues.append({"code": "INVALID_CONNECTION", "node_id": conn.source,
                           "field": "source", "message": f"Connection references unknown source node '{conn.source}'."})
        elif conn.sourceHandle != "main":
            src_type = _node_type(workflow, conn.source)
            if src_type in ("loop", "loop_over_items") and conn.sourceHandle in ("done", "loop", "main"):
                pass
            else:
                node_cls = NODE_REGISTRY.get(src_type)
                if node_cls is not None and conn.sourceHandle not in node_cls().output_handles:
                    issues.append({"code": "INVALID_OUTPUT_HANDLE", "node_id": conn.source,
                                   "field": "sourceHandle",
                                   "message": f"Node '{conn.source}' has no output handle '{conn.sourceHandle}'."})
        if conn.target not in node_ids:
            issues.append({"code": "INVALID_CONNECTION", "node_id": conn.target,
                           "field": "target", "message": f"Connection references unknown target node '{conn.target}'."})
        elif conn.targetHandle != "main":
            node_cls = NODE_REGISTRY.get(_node_type(workflow, conn.target))
            if node_cls is not None and conn.targetHandle not in node_cls().input_handles:
                issues.append({"code": "INVALID_INPUT_HANDLE", "node_id": conn.target,
                               "field": "targetHandle",
                               "message": f"Node '{conn.target}' has no input handle '{conn.targetHandle}'."})

    if issues:
        raise WorkflowValidationError(issues)


def _node_type(workflow: Workflow, node_id: str) -> str:
    for node in workflow.nodes:
        if node.id == node_id:
            return node.type
    return ""


def topological_sort(graph: Graph) -> list[str]:
    """Kahn's algorithm — cycle tolerant.

    Produces a valid execution order: every node appears after all of
    its incoming edges' sources (treating the graph as a DAG). Cycles
    are handled by appending remaining nodes (that couldn't be ordered
    because they're in a strongly connected component) at the end in
    a stable order. Each node still runs exactly once per execution —
    the engine doesn't loop; cycle semantics (if/while) belong to
    dedicated loop nodes (loop_over_items, loop_while), not the graph.

    Previously this rejected "true cycles" with a hard error. We now
    allow any graph topology so users can freely draw loops back to
    earlier nodes and the engine will still produce a correct linear
    execution order.
    """
    # Build forward adjacency
    forward_graph: dict[str, set[str]] = {nid: set() for nid in graph}
    for nid, gnode in graph.items():
        for child in gnode.output_node_ids:
            forward_graph[nid].add(child)

    in_degree: dict[str, int] = {nid: 0 for nid in graph}
    for nid in graph:
        in_degree[nid] = len(graph[nid].input_node_ids)

    ready: list[str] = sorted(
        [nid for nid, deg in in_degree.items() if deg == 0]
    )
    order: list[str] = []

    while ready:
        current = ready.pop(0)
        order.append(current)
        for child in sorted(forward_graph.get(current, set())):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                ready.append(child)
                ready.sort()

    # Cycle fallback: any nodes still with in_degree > 0 are in a
    # strongly connected component (cycle). Append them in a stable
    # order so the run still produces a complete linear execution.
    if len(order) != len(graph):
        remaining = sorted(
            nid for nid, deg in in_degree.items() if deg > 0
        )
        order.extend(remaining)

    return order


def descendant_ids(connections: list, node_id: str, back_edges: set[tuple[str, str]] | None = None) -> set:
    """Transitive downstream node ids of *node_id* (Phase 13).

    Used by safe node retry: everything downstream must re-run on fresh
    data, so none of it may be seeded from the previous execution.
    Accepts plain Connection objects or dicts with source/target keys.

    Back-edges (visual loop connections) are skipped to prevent
    infinite traversal.
    """
    adjacency: dict = {}
    for c in connections or []:
        source = getattr(c, "source", None)
        target = getattr(c, "target", None)
        if source is None and isinstance(c, dict):
            source, target = c.get("source"), c.get("target")
        if not source or not target:
            continue
        # Skip back-edges
        if back_edges and (source, target) in back_edges:
            continue
        adjacency.setdefault(source, []).append(target)

    seen: set = set()
    stack = list(adjacency.get(node_id, []))
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(adjacency.get(nid, []))
    return seen
