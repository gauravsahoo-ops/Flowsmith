"""Loop / ForEach node.

Splits a list of input items into individual items for downstream
processing. Each input item that contains a list is expanded so that
downstream nodes receive one element at a time.

Parameters:
  - field: optional dot-path to a field within each input item that
    contains the list to iterate over. If omitted, each input item
    itself is treated as the value to iterate.
  - batch_size: optional maximum number of items to emit (0 = unlimited).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class LoopParams(BaseModel):
    field: str = Field(default="", description="Dot-path to list field (empty = use entire item)")
    batch_size: int = Field(default=0, ge=0, description="Max items to emit (0 = unlimited)")


@register
class LoopNode(BaseNode[LoopParams]):
    node_type = "loop"
    display_name = "Loop / ForEach"
    version = 1
    description = "Split a list into individual items for downstream processing."
    category = "Flow"
    icon = "loop_over_items"
    parameters_schema = LoopParams
    input_handles = ["main"]
    output_handles = ["done", "loop"]

    async def run(
        self,
        ctx: NodeContext,
        params: LoopParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        output_items: list[dict[str, Any]] = []

        for item in input_items:
            if params.field:
                target = _resolve_field(item, params.field)
            else:
                target = item

            if isinstance(target, list):
                for element in target:
                    if isinstance(element, dict):
                        output_items.append(element)
                    else:
                        output_items.append({"value": element})
            elif isinstance(target, dict):
                output_items.append(target)
            elif target is not None:
                output_items.append({"value": target})

            if params.batch_size > 0 and len(output_items) >= params.batch_size:
                output_items = output_items[: params.batch_size]
                break

        return NodeResult(
            output_items=output_items,
            output_by_handle={
                "main": output_items,
                "done": output_items,
                "loop": output_items,
            },
        )


def _resolve_field(item: dict[str, Any], field: str) -> Any:
    """Resolve a dot-separated field path against a dict."""
    parts = field.split(".")
    current: Any = item
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
