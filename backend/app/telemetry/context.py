"""Execution context variables for asynchronous telemetry propagation."""

from __future__ import annotations

from contextvars import ContextVar

current_execution_id: ContextVar[str | None] = ContextVar("current_execution_id", default=None)
current_workspace_id: ContextVar[str | None] = ContextVar("current_workspace_id", default=None)
current_node_id: ContextVar[str | None] = ContextVar("current_node_id", default=None)
current_organization_id: ContextVar[int | None] = ContextVar("current_organization_id", default=None)
