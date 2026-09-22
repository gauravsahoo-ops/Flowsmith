"""Shared API helpers: response envelope (spec 9), pagination, workflow validation."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query, status

from app.config import get_settings
from app.engine.errors import WorkflowValidationError
from app.engine.graph import build_graph, topological_sort, validate_graph
from app.schemas.workflow import Workflow

TERMINAL_STATUSES = frozenset({"success", "failed", "cancelled", "timeout"})


def ok(data: Any = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything returns {"data": ..., "meta": ...} (spec 9)."""
    body: dict[str, Any] = {"data": data}
    if meta is not None:
        body["meta"] = meta
    return body


def page_params(
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1),
) -> tuple[int, int]:
    size = min(pageSize, get_settings().page_size_max)
    return page, size


def validate_workflow_payload(payload: dict) -> Workflow:
    """Parse + graph-validate a workflow JSON body; 422 with a readable detail.

    Draft semantics (Phase 24): the API validates the graph structure
    (types, handles, connections, cycles, settings) but not each node's
    parameters, so an unconfigured node never blocks saving a workflow
    from the UI. Parameter correctness is enforced by the engine at run
    time, where it surfaces as a node error.
    """
    import logging
    _log = logging.getLogger("app.validate")
    try:
        # Trim workflow name before validation
        if "name" in payload and isinstance(payload["name"], str):
            payload = {**payload, "name": payload["name"].strip()}
        workflow = Workflow.model_validate(payload)
        validate_graph(workflow, validate_params=False)
        topological_sort(build_graph(workflow))
    except (ValueError, WorkflowValidationError) as exc:
        _log.error("Validation failed: %s | payload keys=%s node_types=%s",
                   exc, list(payload.keys()),
                   [n.get("type") for n in payload.get("nodes", [])])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return workflow
