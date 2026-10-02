"""Item lists node.

Small list utilities over the incoming items: sort, limit, dedupe,
reverse, and pluck a field. Pure local transform, no side effects.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class ItemListsParams(BaseModel):
    operation: Literal["sort", "limit", "dedupe", "reverse", "pluck"] = Field(default="sort")
    field: str = Field(default="", description="Dot-path field, e.g. json.name (empty = whole item).")
    descending: bool = Field(default=False)
    limit: int = Field(default=10, ge=1, le=5000)
    offset: int = Field(default=0, ge=0, le=100000)


def _pick(item: Any, field: str) -> Any:
    if not field:
        return item
    cur: Any = item
    for part in field.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


@register
class ItemListsNode(BaseNode[ItemListsParams]):
    node_type = "item_lists"
    display_name = "Item Lists"
    version = 1
    description = "Sort, limit, dedupe, reverse, or pluck item fields."
    category = "Transform"
    icon = "item_lists"
    parameters_schema = ItemListsParams

    async def run(
        self,
        ctx: NodeContext,
        params: ItemListsParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        items = list(input_items or [])
        if params.operation == "reverse":
            return NodeResult(output_items=list(reversed(items)))
        if params.operation == "limit":
            return NodeResult(output_items=items[params.offset : params.offset + params.limit])
        if params.operation == "pluck":
            return NodeResult(output_items=[{"value": _pick(it, params.field)} for it in items])
        if params.operation == "dedupe":
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for it in items:
                key = repr(_pick(it, params.field))
                if key not in seen:
                    seen.add(key)
                    out.append(it)
            return NodeResult(output_items=out)
        # sort (stable, None-safe)
        def _key(it: dict[str, Any]) -> tuple[int, str]:
            v = _pick(it, params.field)
            return (1, repr(v)) if v is None else (0, repr(v))

        return NodeResult(output_items=sorted(items, key=_key, reverse=params.descending))
