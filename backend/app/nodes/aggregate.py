"""Aggregate node.

Collects multiple input items into a single list. Useful after a loop
to recombine split items back into one item containing the full list.

Parameters:
  - field: optional field name to store the aggregated list under
    (default: "items").
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class AggregateParams(BaseModel):
    field: str = Field(default="items", description="Field name for the aggregated list")


@register
class AggregateNode(BaseNode[AggregateParams]):
    node_type = "aggregate"
    display_name = "Aggregate"
    version = 1
    description = "Collect multiple items into a single list."
    category = "Transform"
    icon = "📦"
    parameters_schema = AggregateParams

    async def run(
        self,
        ctx: NodeContext,
        params: AggregateParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        return NodeResult(output_items=[{params.field: input_items}])
