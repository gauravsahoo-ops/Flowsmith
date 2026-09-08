"""Filter node — keeps only items matching condition(s) (Phase 43 / n8n parity).

Keeps only items matching the conditions; non-matching items are dropped
so downstream nodes receive a filtered stream.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.condition_base import (
    Condition,
    ConditionRow,
    evaluate_conditions,
    evaluate as _evaluate,
    LEGACY_OPERATOR_MAP,
)
from app.nodes.registry import register


class FilterParams(BaseModel):
    # Legacy single condition (backward compatibility)
    condition: Condition | None = Field(default=None)
    # Multi-condition support
    conditions: list[ConditionRow] | None = Field(default=None)
    combinator: Literal["AND", "OR"] = "AND"
    convertTypes: bool = Field(default=False, description="Convert types where required")
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "conditions" not in d or d["conditions"] is None:
            if "condition" in d and d["condition"] is not None:
                cond = d["condition"]
                if hasattr(cond, "model_dump"):
                    cond_dict = cond.model_dump()
                elif isinstance(cond, dict):
                    cond_dict = cond
                elif hasattr(cond, "__dict__"):
                    cond_dict = cond.__dict__
                else:
                    cond_dict = {"left": getattr(cond, "left", ""), "operator": getattr(cond, "operator", "is equal to"), "right": getattr(cond, "right", "")}
                
                op_raw = cond_dict.get("operator")
                op_str = str(op_raw) if op_raw is not None else "is equal to"
                op = LEGACY_OPERATOR_MAP.get(op_str, op_str)
                d["conditions"] = [
                    {
                        "id": "legacy",
                        "left": cond_dict.get("left", ""),
                        "operator": op,
                        "right": cond_dict.get("right", ""),
                        "combinator": "AND",
                    }
                ]
            elif "leftValue" in d or "left" in d:
                op_raw = d.get("operator")
                op_str = str(op_raw) if op_raw is not None else "is equal to"
                op = LEGACY_OPERATOR_MAP.get(op_str, op_str)
                d["conditions"] = [
                    {
                        "id": "legacy",
                        "left": d.get("leftValue", d.get("left", "")),
                        "operator": op,
                        "right": d.get("rightValue", d.get("right", "")),
                        "combinator": "AND",
                    }
                ]
            else:
                d["conditions"] = [
                    {"id": "default", "left": "", "operator": "is equal to", "right": "", "combinator": "AND"}
                ]
        if isinstance(d.get("conditions"), list):
            new_conds = []
            for idx, c in enumerate(d["conditions"]):
                if not isinstance(c, dict):
                    continue
                op_raw = c.get("operator")
                op_str = str(op_raw) if op_raw is not None else "is equal to"
                op = LEGACY_OPERATOR_MAP.get(op_str, op_str)
                comb = c.get("combinator", "AND")
                if idx == 0:
                    comb = "AND"
                elif comb not in ("AND", "OR"):
                    comb = "AND"
                new_conds.append({
                    "id": c.get("id") or f"cond_{idx}",
                    "left": c.get("left", ""),
                    "operator": op,
                    "right": c.get("right", ""),
                    "combinator": comb,
                })
            d["conditions"] = new_conds
        if "convertTypes" not in d and "convert_types" in d:
            d["convertTypes"] = bool(d.pop("convert_types"))
        return d


@register
class FilterNode(BaseNode[FilterParams]):
    node_type = "filter"
    display_name = "Filter"
    version = 1
    description = "Keep only items matching a condition"
    category = "Flow"
    icon = "filter"
    parameters_schema = FilterParams
    input_handles = ["main"]
    output_handles = ["main"]
    idempotency_note = "pure transformation"
    resolves_own_expressions = True

    async def run(
        self,
        ctx: NodeContext,
        params: FilterParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            return NodeResult(output_items=[])

        ignore_case = bool(params.options.get("ignoreCase", False))
        always_output = bool(params.options.get("alwaysOutputData", False))

        conditions = params.conditions
        if not conditions and params.condition:
            kept = [item for item in input_items if _evaluate(params.condition, item, convert_types=params.convertTypes)]
        elif conditions:
            kept = [
                item for item in input_items
                if evaluate_conditions(conditions, item, convert_types=params.convertTypes, ignore_case=ignore_case)
            ]
        else:
            kept = list(input_items)

        if not kept and always_output:
            kept = [{}]

        return NodeResult(output_items=kept)
