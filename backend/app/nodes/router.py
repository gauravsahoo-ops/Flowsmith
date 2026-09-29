"""Router node (Phase 7 Logic).

Deterministic multi-destination router, complementary to Switch:
- Switch evaluates per-rule conditions with rename/fallback semantics.
- Router applies an explicit dispatch *strategy* over a static route table:

- ``first_match`` (default): each item goes to the first route whose
  ``contains`` substring matches ``{{ $json }}``-resolved field, else default.
- ``all_matches``: item is fanned out to every matching route.
- ``round_robin``: items are distributed cyclically across routes,
  ignoring match values (state seeded per execution via ctx.storage).

Routes are declared as a simple list of names; output handles are
``route_0..route_N`` plus ``default``. Deterministic, no randomness.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


def _field_value(item: dict[str, Any], field: str) -> str:
    if not field:
        return ""
    cur: Any = item
    for part in field.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return "" if cur is None else str(cur)


class RouterParams(BaseModel):
    strategy: Literal["first_match", "all_matches", "round_robin"] = Field(default="first_match")
    field: str = Field(default="", description="Item field to match (dot path).")
    routes: list[str] = Field(default_factory=lambda: ["route_0", "route_1"], description="Route match values.")
    case_insensitive: bool = Field(default=False)


@register
class RouterNode(BaseNode[RouterParams]):
    node_type = "router"
    display_name = "Router"
    version = 1
    description = "Route items to one or more destinations by strategy."
    category = "Flow"
    icon = "router"
    parameters_schema = RouterParams
    input_handles = ["main"]
    output_handles = ["route_0", "route_1", "default"]

    async def run(self, ctx: NodeContext, params: RouterParams, input_items: list[dict[str, Any]]) -> NodeResult:
        routes = params.routes or []
        buckets: dict[str, list[dict[str, Any]]] = {f"route_{i}": [] for i in range(len(routes))}
        buckets.setdefault("default", [])

        if params.strategy == "round_robin":
            if not routes:
                buckets["default"] = list(input_items)
                return NodeResult(output_by_handle=buckets)
            start = int(await ctx.storage.get(f"router:{ctx.node_id}:rr", 0) or 0)
            for offset, item in enumerate(input_items):
                idx = (start + offset) % len(routes)
                buckets[f"route_{idx}"].append(item)
            await ctx.storage.set(f"router:{ctx.node_id}:rr", (start + len(input_items)) % len(routes))
            return NodeResult(output_by_handle=buckets)

        for item in input_items:
            value = _field_value(item, params.field)
            probe = value.lower() if params.case_insensitive else value
            matched: list[int] = []
            for idx, route in enumerate(routes):
                needle = str(route or "")
                needle = needle.lower() if params.case_insensitive else needle
                if needle and needle in probe:
                    matched.append(idx)
                    if params.strategy == "first_match":
                        break
            if not matched:
                buckets["default"].append(item)
            else:
                for idx in matched:
                    buckets[f"route_{idx}"].append(item)
        return NodeResult(output_by_handle=buckets)
