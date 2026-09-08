"""Typed errors for the engine (spec 8.3, 27)."""

from __future__ import annotations

from typing import Any


class WorkflowError(Exception):
    """Base class for all engine errors."""

    code = "WORKFLOW_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        self.message = message
        if code:
            self.code = code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class WorkflowValidationError(WorkflowError):
    """The workflow JSON violates the contract (spec 24.3).

    `issues` is a list of dicts:
    {"code", "node_id", "field", "message"}
    """

    code = "INVALID_WORKFLOW"

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        if issues:
            first = issues[0]
            detail = first.get("message") or first.get("code") or ""
            super().__init__(
                f"Workflow validation failed ({len(issues)} issue(s)): {detail}."
            )
        else:
            super().__init__("Workflow validation failed.")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "issues": self.issues}


class NodeExecutionError(WorkflowError):
    """A node failed at runtime (spec 27).

    `retryable` marks errors that may be retried (network/timeout), not
    permanent ones (bad params, bad credentials).
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "NODE_EXECUTION_ERROR",
        node_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        self.node_id = node_id
        self.retryable = retryable
        self.details = details or {}
        # Provider Retry-After hint (Phase 9): seconds to wait before the
        # next attempt; honoured by the engine's backoff instead of its own.
        self.retry_after: float | None = None
        super().__init__(message, code=code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "retryable": self.retryable,
            "details": self.details,
        }


class NodeTimeoutError(NodeExecutionError):
    """A node exceeded its configured timeout."""

    def __init__(self, node_id: str, timeout_seconds: float):
        super().__init__(
            f"Node exceeded its timeout of {timeout_seconds}s.",
            code="NODE_TIMEOUT",
            node_id=node_id,
            retryable=True,
        )


class NodeCancelledError(WorkflowError):
    """The execution was cancelled while a node was running."""

    code = "NODE_CANCELLED"

    def __init__(self, node_id: str | None = None):
        self.node_id = node_id
        super().__init__("Execution was cancelled.", code="NODE_CANCELLED")
