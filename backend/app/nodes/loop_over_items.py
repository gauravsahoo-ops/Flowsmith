"""Loop Over Items — visual alias for Loop (n8n parity).

Provides the exact node_type string expected from n8n references while
reusing Loop's per-item split behavior. See `loop.py`.
"""

from __future__ import annotations

from typing import Any

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.loop import LoopParams, LoopNode
from app.nodes.registry import register


@register
class LoopOverItemsNode(BaseNode[LoopParams]):
    node_type = "loop_over_items"
    display_name = "Loop Over Items"
    version = 1
    description = "Split data into batches and iterate over each batch"
    category = "Flow"
    icon = "loop_over_items"
    parameters_schema = LoopParams
    input_handles = ["main"]
    output_handles = ["done", "loop"]
    _delegate = LoopNode()

    async def run(
        self,
        ctx: NodeContext,
        params: LoopParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        return await self._delegate.run(ctx, params, input_items)
