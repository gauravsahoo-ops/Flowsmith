"""The workflow JSON contract. Single source of truth (spec section 6, 24).

Both the engine and the future API/frontend must speak this shape.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class NodePosition(BaseModel):
    x: float = 0
    y: float = 0

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, (list, tuple)) and len(data) >= 2:
            try:
                return {"x": float(data[0]), "y": float(data[1])}
            except (ValueError, TypeError):
                return {"x": 0.0, "y": 0.0}
        if isinstance(data, dict):
            x = data.get("x", data.get("left", 0))
            y = data.get("y", data.get("top", 0))
            try:
                return {"x": float(x), "y": float(y)}
            except (ValueError, TypeError):
                return {"x": 0.0, "y": 0.0}
        return data


class WorkflowNode(BaseModel):
    """One step in a workflow (spec 6.1).

    `parameters` are passed to the node; `settings` hold engine-level
    options such as `continue_on_error` and `timeout_seconds`.
    `credentials` maps credential type -> credential id (named
    references, spec 12).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    version: int = 1
    position: NodePosition = Field(default_factory=NodePosition)
    parameters: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
    name: str = Field(default="", description="Display name for $('Name') expressions.")
    pinned_data: Any = Field(default=None, description="Pinned mock output data (bypasses execution).")

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # Unwrap nested data.node if client passes React Flow node shape
        if isinstance(d.get("data"), dict) and isinstance(d["data"].get("node"), dict):
            inner = dict(d["data"]["node"])
            d = {**inner, **d}

        # Normalize ID
        nid = d.get("id") or d.get("node_id") or d.get("nodeId") or d.get("key")
        if not nid:
            ntype = str(d.get("type") or "node")
            nid = f"{ntype}_{uuid.uuid4().hex[:6]}"
        d["id"] = str(nid)

        # Normalize Type
        ntype = d.get("type") or d.get("node_type") or d.get("nodeType") or d.get("kind")
        if ntype:
            d["type"] = str(ntype)

        # Normalize Name
        if not d.get("name"):
            d["name"] = str(d.get("type", "")).replace("_", " ").title() or str(d["id"])

        if d.get("parameters") is None or not isinstance(d.get("parameters"), dict):
            d["parameters"] = {}
        if d.get("settings") is None or not isinstance(d.get("settings"), dict):
            d["settings"] = {}
        if d.get("credentials") is None or not isinstance(d.get("credentials"), dict):
            d["credentials"] = {}
        return d


class Connection(BaseModel):
    """A directed edge between two nodes (spec 6.2)."""

    source: str
    sourceHandle: str = "main"
    target: str
    targetHandle: str = "main"

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # Source aliases
        src = d.get("source") or d.get("source_id") or d.get("from_node") or d.get("from") or d.get("src")
        if src is not None:
            d["source"] = str(src)

        # Target aliases
        tgt = d.get("target") or d.get("target_id") or d.get("to_node") or d.get("to") or d.get("dst")
        if tgt is not None:
            d["target"] = str(tgt)

        # Handle aliases & dialect normalization
        s_handle = (
            d.get("sourceHandle")
            or d.get("source_handle")
            or d.get("fromHandle")
            or d.get("from_handle")
            or d.get("source_output")
            or d.get("output")
            or "main"
        )
        if isinstance(s_handle, str):
            s_low = s_handle.strip().lower()
            if s_low in ("true", "1", "yes"):
                s_handle = "true"
            elif s_low in ("false", "0", "no"):
                s_handle = "false"
            elif s_low.startswith("route_") or s_low in ("main", "loop", "done", "default", "fallback"):
                s_handle = s_low
        d["sourceHandle"] = str(s_handle) if s_handle is not None else "main"

        t_handle = (
            d.get("targetHandle")
            or d.get("target_handle")
            or d.get("toHandle")
            or d.get("to_handle")
            or d.get("input")
            or "main"
        )
        d["targetHandle"] = str(t_handle) if t_handle is not None else "main"
        return d


WORKFLOW_STATUSES = ("draft", "active", "inactive", "archived")


class Workflow(BaseModel):
    """The full graph document (spec 6.3, 24.1)."""

    id: str
    name: str = Field(min_length=0, max_length=255, default="")
    version: int = 1
    status: str = "draft"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if not d.get("id"):
            d["id"] = f"wf_{uuid.uuid4().hex[:8]}"
        if not d.get("name"):
            d["name"] = "Workflow"

        # Normalize nodes if dict
        raw_nodes = d.get("nodes")
        if isinstance(raw_nodes, dict):
            d["nodes"] = list(raw_nodes.values())
        elif raw_nodes is None:
            d["nodes"] = []

        # Normalize connections if dict (e.g., n8n connections structure or keyed map)
        raw_conns = d.get("connections")
        if isinstance(raw_conns, dict):
            normalized_conns = []
            for src_node, outputs in raw_conns.items():
                if isinstance(outputs, dict):
                    for handle_type, routes in outputs.items():
                        if isinstance(routes, list):
                            for route in routes:
                                if isinstance(route, list):
                                    for target_obj in route:
                                        if isinstance(target_obj, dict) and "node" in target_obj:
                                            normalized_conns.append({
                                                "source": src_node,
                                                "target": target_obj["node"],
                                                "sourceHandle": handle_type,
                                                "targetHandle": target_obj.get("type", "main"),
                                            })
                                elif isinstance(route, dict) and "node" in route:
                                    normalized_conns.append({
                                        "source": src_node,
                                        "target": route["node"],
                                        "sourceHandle": handle_type,
                                        "targetHandle": route.get("type", "main"),
                                    })
                elif isinstance(outputs, list):
                    for route in outputs:
                        if isinstance(route, dict) and ("node" in route or "target" in route):
                            normalized_conns.append({
                                "source": src_node,
                                "target": route.get("node") or route.get("target"),
                                "sourceHandle": route.get("sourceHandle", "main"),
                                "targetHandle": route.get("targetHandle", "main"),
                            })
            d["connections"] = normalized_conns
        elif raw_conns is None:
            d["connections"] = []

        return d
