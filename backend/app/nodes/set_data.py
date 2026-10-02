"""Set / Edit Data node (spec 7, node #5).

Merges fixed fields into each incoming item, or creates a single item
when there is no input. Field values may contain `{{ }}` expressions --
the executor resolves them before run() is called.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class SetDataParams(BaseModel):
    mode: Literal["merge", "replace"] = "merge"
    fields: dict[str, Any] = Field(default_factory=dict)


@register
class SetDataNode(BaseNode[SetDataParams]):
    node_type = "set_data"
    display_name = "Set / Edit Data"
    version = 1
    description = "Set or replace fields on the data passing through."
    category = "Transform"
    icon = "set_data"
    parameters_schema = SetDataParams

    async def run(
        self,
        ctx: NodeContext,
        params: SetDataParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            return NodeResult(output_items=[dict(params.fields)])

        output_items = []
        for item in input_items:
            if params.mode == "replace":
                merged = dict(params.fields)
            else:
                merged = {**item, **params.fields}
            output_items.append(merged)
        return NodeResult(output_items=output_items)
