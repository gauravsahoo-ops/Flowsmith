"""Switch node.

Routes incoming items to outputs based on defined rules or an expression.
Supports multiple routing rules, rename output, fallback output,
ignore case, send to all matching outputs, and type conversion.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from app.engine import expressions as _expr
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.condition_base import evaluate_condition, LEGACY_OPERATOR_MAP
from app.nodes.registry import register


def _resolve_switch_val(val: Any, item: dict[str, Any]) -> Any:
    """Resolve a field value that may contain {{ $json.field }}, bare $json.field, or expressions."""
    if not isinstance(val, str):
        return val

    s = val.strip()
    if s.startswith("={"):
        s = s[1:].strip()

    # Handle {{ $json.path }}
    if s.startswith("{{") and s.endswith("}}"):
        inner = s[2:-2].strip()
        if inner.startswith("$json."):
            parts = inner[6:].split(".")
            cur: Any = item
            for p in parts:
                cur = cur.get(p) if isinstance(cur, dict) else None
            return cur

    # Handle bare $json.path
    if s.startswith("$json."):
        parts = s[6:].split(".")
        cur: Any = item
        for p in parts:
            cur = cur.get(p) if isinstance(cur, dict) else None
        return cur

    # General expression engine
    if "{{" in s:
        resolved = _expr.resolve(s, {"$json": item})
        if not (isinstance(resolved, str) and "{{" in resolved):
            return resolved

    return val


class SwitchRule(BaseModel):
    id: str | None = None
    value1: Any = Field(default="", description="First value or expression to compare")
    left: Any = None  # legacy fallback
    operator: str = Field(default="is equal to", description="Comparison operator")
    value2: Any = Field(default="", description="Second value or expression to compare")
    right: Any = None  # legacy fallback
    rename_output: bool = Field(default=False, description="Whether to customize the output name")
    output_name: str = Field(default="", description="Custom output name")
    output: str = Field(default="", description="Route handle key")


class SwitchParams(BaseModel):
    mode: Literal["rules", "expression"] = Field(
        default="rules",
        description="Mode: 'rules' or 'expression'",
    )
    expression: str = Field(
        default="",
        description="Expression returning the output index (e.g. {{ $json.status === 'active' ? 0 : 1 }})",
    )
    rules: list[SwitchRule] = Field(
        default_factory=list,
        description="Evaluated top-down against items.",
    )
    convert_types: bool = Field(
        default=False,
        description="Whether to perform type coercion during comparisons.",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional options: fallbackOutput, ignoreCase, sendToAllMatching.",
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
        ignore_case = bool(params.options.get("ignoreCase", params.options.get("ignore_case", False)))
        send_to_all = bool(params.options.get("sendToAllMatching", params.options.get("send_to_all_matching", False)))
        fallback_enabled = bool(params.options.get("fallbackOutput", params.options.get("fallback_output", False)))
        convert_types = params.convert_types

        # Initialize output buckets
        buckets: dict[str, list[dict[str, Any]]] = {}

        # 1. Expression Mode
        if params.mode == "expression" and params.expression:
            for item in input_items:
                res = _expr.resolve(params.expression, {"$json": item})
                # Check integer index
                try:
                    idx = int(res)
                    handle = f"route_{idx}"
                except (ValueError, TypeError):
                    handle = str(res) if res is not None else "default"
                buckets.setdefault(handle, []).append(item)
            return NodeResult(output_by_handle=buckets)

        # 2. Rules Mode
        rules = params.rules if params.rules is not None else [
            SwitchRule(value1="", operator="is equal to", value2="", output="route_0")
        ]

        # Pre-seed buckets for all configured rules
        for idx, r in enumerate(rules):
            h = r.output_name.strip() if (r.rename_output and r.output_name) else (r.output if r.output else f"route_{idx}")
            buckets.setdefault(h, [])
        if fallback_enabled:
            buckets.setdefault("fallback", [])
        buckets.setdefault("default", [])

        for item in input_items:
            routed = False
            for idx, rule in enumerate(rules):
                raw_v1 = rule.value1 if rule.value1 != "" else (rule.left if rule.left is not None else "")
                raw_v2 = rule.value2 if rule.value2 != "" else (rule.right if rule.right is not None else "")

                v1_resolved = _resolve_switch_val(raw_v1, item)
                v2_resolved = _resolve_switch_val(raw_v2, item)

                op = LEGACY_OPERATOR_MAP.get(rule.operator, rule.operator)
                match = evaluate_condition(
                    v1_resolved,
                    op,
                    v2_resolved,
                    convert_types=convert_types,
                    ignore_case=ignore_case,
                )

                if match:
                    h = rule.output_name.strip() if (rule.rename_output and rule.output_name) else (rule.output if rule.output else f"route_{idx}")
                    buckets.setdefault(h, []).append(item)
                    routed = True
                    if not send_to_all:
                        break

            if not routed:
                if fallback_enabled:
                    buckets.setdefault("fallback", []).append(item)
                else:
                    buckets.setdefault("default", []).append(item)

        return NodeResult(output_by_handle=buckets)
