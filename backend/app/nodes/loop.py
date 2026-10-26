"""Loop / ForEach node.

Splits a list of input items into individual items for downstream
processing. Each input item that contains a list is expanded so that
downstream nodes receive one element at a time.

Parameters:
  - field: dot-path to a field within each input item (e.g. 'records'),
    or a direct expression (e.g. '{{ $json.records }}'), or drag-and-dropped
    array. If empty, input items themselves are treated as the value to iterate.
  - batch_size: optional grouping size for execution metadata; every item is
    still emitted, so the loop never silently drops the tail of a list.
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
    batch_size: int = Field(
        default=0,
        ge=0,
        description="Grouping size for execution metadata; all input items are emitted (0 = no grouping)",
    )


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

        def result_for(items: list[dict[str, Any]]) -> NodeResult:
            batches = (
                [
                    len(items[index:index + params.batch_size])
                    for index in range(0, len(items), params.batch_size)
                ]
                if params.batch_size > 0
                else []
            )
            if batches:
                logger = getattr(ctx, "logger", None)
                if logger is not None:
                    logger.info(
                        "Loop Over Items processed %d item(s) in %d batch(es) of %d",
                        len(items), len(batches), params.batch_size,
                    )
            return NodeResult(
                output_items=items,
                output_by_handle={"main": items, "done": items, "loop": items},
                metadata={
                    "batch_size": params.batch_size,
                    "batches": batches,
                    "processed": len(items),
                },
            )

        # If params.field evaluated directly to a list (from expression like {{ $json.records }} or {{ $('...').records }})
        if isinstance(params.field, list):
            for element in params.field:
                output_items.append(element if isinstance(element, dict) else {"value": element})
            return result_for(output_items)

        # If params.field is a single dict object
        if isinstance(params.field, dict):
            return result_for([params.field])

        # If params.field is a string containing unresolved {{ ... }} expression
        if isinstance(params.field, str) and "{{" in params.field:
            try:
                from app.engine import expressions
                eval_ctx: dict[str, Any] = {"$json": input_items[0] if input_items else {}}
                resolved = expressions.resolve(params.field, eval_ctx)
                if isinstance(resolved, list):
                    for element in resolved:
                        output_items.append(element if isinstance(element, dict) else {"value": element})
                    return result_for(output_items)
            except Exception:
                pass

        for item in input_items:
            if params.field and isinstance(params.field, str):
                target = _resolve_field(item, params.field)
            else:
                target = item

            if isinstance(target, list):
                for element in target:
                    output_items.append(element if isinstance(element, dict) else {"value": element})
            elif isinstance(target, dict):
                output_items.append(target)
            elif target is not None:
                output_items.append({"value": target})

        return result_for(output_items)


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
