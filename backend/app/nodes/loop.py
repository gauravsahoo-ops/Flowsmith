"""Loop / ForEach node.

Splits a list of input items into individual items for downstream
processing. Each input item that contains a list is expanded so that
downstream nodes receive one element at a time.

Parameters:
  - field: dot-path to a field within each input item (e.g. 'records'),
    or a direct expression (e.g. '{{ $json.records }}'), or drag-and-dropped
    array. If empty, input items themselves are treated as the value to iterate.
  - batch_size: optional maximum number of items to emit (0 = unlimited).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class LoopParams(BaseModel):
    field: Any = Field(
        default="",
        description="Field name (e.g. 'records') or expression (e.g. '{{ $json.records }}')",
    )
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
        if not input_items and not params.field:
            return NodeResult(output_items=[{}])
        output_items: list[dict[str, Any]] = []

        # If params.field evaluated directly to a list (from expression like {{ $json.records }} or {{ $('...').records }})
        if isinstance(params.field, list):
            for element in params.field:
                if isinstance(element, dict):
                    output_items.append(element)
                else:
                    output_items.append({"value": element})
                if params.batch_size > 0 and len(output_items) >= params.batch_size:
                    break
            return NodeResult(
                output_items=output_items,
                output_by_handle={
                    "main": output_items,
                    "done": output_items,
                    "loop": output_items,
                },
            )

        # If params.field is a single dict object
        if isinstance(params.field, dict):
            output_items.append(params.field)
            return NodeResult(
                output_items=output_items,
                output_by_handle={
                    "main": output_items,
                    "done": output_items,
                    "loop": output_items,
                },
            )

        # If params.field is a string containing unresolved {{ ... }} expression
        if isinstance(params.field, str) and "{{" in params.field:
            try:
                from app.engine import expressions
                eval_ctx: dict[str, Any] = {"$json": input_items[0] if input_items else {}}
                resolved = expressions.resolve(params.field, eval_ctx)
                if isinstance(resolved, list):
                    for element in resolved:
                        if isinstance(element, dict):
                            output_items.append(element)
                        else:
                            output_items.append({"value": element})
                        if params.batch_size > 0 and len(output_items) >= params.batch_size:
                            break
                    return NodeResult(
                        output_items=output_items,
                        output_by_handle={
                            "main": output_items,
                            "done": output_items,
                            "loop": output_items,
                        },
                    )
            except Exception:
                pass

        for item in input_items:
            if params.field and isinstance(params.field, str):
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
    cleaned = field.strip()
    for prefix in ("$json.", "json.", "item.json.", "$node.", "item."):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    parts = cleaned.split(".")
    current: Any = item
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


@register
class LoopOverItemsNode(LoopNode):
    node_type = "loop_over_items"
    display_name = "Loop Over Items"
    description = "Split data into batches and iterate over each batch"
    icon = "loop_over_items"
