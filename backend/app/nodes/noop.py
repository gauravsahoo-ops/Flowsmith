"""NoOp node (Flow).

Passes input items through unchanged. Useful as a placeholder, a
visual anchor for wiring, or a no-op branch terminator.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class NoOpParams(BaseModel):
    """NoOp takes no parameters; input passes through untouched."""


@register
class NoOpNode(BaseNode[NoOpParams]):
    node_type = "noop"
    display_name = "NoOp"
    version = 1
    description = "Pass input items through unchanged (does nothing)"
    category = "Flow"
    icon = "noop"
    parameters_schema = NoOpParams
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: NoOpParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        return NodeResult(output_items=list(input_items))
