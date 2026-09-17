"""The workflow JSON contract. Single source of truth (spec section 6, 24).

Both the engine and the future API/frontend must speak this shape.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NodePosition(BaseModel):
    x: float = 0
    y: float = 0


class WorkflowNode(BaseModel):
    """One step in a workflow (spec 6.1).

    `parameters` are passed to the node; `settings` hold engine-level
    options such as `continue_on_error` and `timeout_seconds`.
    `credentials` maps credential type -> credential id (n8n-style
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
    name: str = Field(default="", description="Display name for n8n-style $('Name') expressions.")
    pinned_data: Any = Field(default=None, description="Pinned mock output data (bypasses execution).")


class Connection(BaseModel):
    """A directed edge between two nodes (spec 6.2)."""

    source: str
    sourceHandle: str = "main"
    target: str
    targetHandle: str = "main"


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
