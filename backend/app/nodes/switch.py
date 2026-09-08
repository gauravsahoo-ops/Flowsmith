"""Switch node (Phase 43).

Routes each incoming item to the first matching rule's output handle.
Up to 3 named routes plus a fallback "default" handle (mirrors the
static-handle pattern used by IF/Condition).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.condition_base import Condition, evaluate as _evaluate
from app.nodes.registry import register


class SwitchRule(BaseModel):
    left: Any = Field(description="Field path to test, e.g. $json.type")
    operator: Literal[
        "equals", "not_equals", "contains", "greater_than",
        "less_than", "starts_with", "exists",
    ] = "equals"
    right: Any = None
    output: Literal["route_0", "route_1", "route_2"] = "route_0"


class SwitchParams(BaseModel):
    rules: list[SwitchRule] = Field(
        default_factory=list,
        description="Evaluated top-down; the first matching route wins.",
    )


@register
class SwitchNode(BaseNode[SwitchParams]):
    node_type = "switch"
    display_name = "Switch"
    version = 1
    description = "Route items depending on defined expression or rules"
    category = "Flow"
    icon = "switch"
    parameters_schema = SwitchParams
    input_handles = ["main"]
    output_handles = ["route_0", "route_1", "route_2", "default"]

    async def run(
        self,
        ctx: NodeContext,
        params: SwitchParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        buckets: dict[str, list[dict[str, Any]]] = {h: [] for h in self.output_handles}
        for item in input_items:
            routed = False
            for idx, rule in enumerate(params.rules[:3]):
                cond = Condition(left=rule.left, operator=rule.operator, right=rule.right)
                if _evaluate(cond, item):
                    buckets[rule.output].append(item)
                    routed = True
                    break
            if not routed:
                buckets["default"].append(item)
        return NodeResult(output_by_handle=buckets)
