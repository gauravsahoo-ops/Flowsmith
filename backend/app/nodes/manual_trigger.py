"""Manual trigger node (spec 7, node #1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class ManualTriggerParams(BaseModel):
    pass


@register
class ManualTriggerNode(BaseNode[ManualTriggerParams]):
    node_type = "manual_trigger"
    display_name = "Manual Trigger"
    version = 1
    description = "Runs the workflow when you press Run in the UI."
    category = "Triggers"
    icon = "▶️"
    parameters_schema = ManualTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: ManualTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        items = input_items if input_items else [{"success": True}]
        return NodeResult(output_items=items)
