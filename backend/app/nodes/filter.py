"""Filter node — keeps only items matching condition(s).

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

        # Unpack nested dict conditions (e.g., n8n dialect or wrapper dicts)
        if isinstance(d.get("conditions"), dict):
            cond_dict = d["conditions"]
            if "combinator" in cond_dict and isinstance(cond_dict["combinator"], str):
                inner_comb = cond_dict["combinator"].strip().upper()
                if inner_comb in ("AND", "OR"):
                    d["combinator"] = inner_comb
            elif "all" in cond_dict:
                d["combinator"] = "AND"
            elif "any" in cond_dict:
                d["combinator"] = "OR"

            extracted_list = None
            if "conditions" in cond_dict and isinstance(cond_dict["conditions"], list):
                extracted_list = cond_dict["conditions"]
            elif "rules" in cond_dict and isinstance(cond_dict["rules"], list):
                extracted_list = cond_dict["rules"]
            elif "all" in cond_dict and isinstance(cond_dict["all"], list):
                extracted_list = cond_dict["all"]
            elif "any" in cond_dict and isinstance(cond_dict["any"], list):
                extracted_list = cond_dict["any"]
            elif "values" in cond_dict and isinstance(cond_dict["values"], list):
                extracted_list = cond_dict["values"]
            else:
                typed_list = []
                for k, v in cond_dict.items():
                    if isinstance(v, list):
                        typed_list.extend(v)
                if typed_list:
                    extracted_list = typed_list

            d["conditions"] = extracted_list or []

        if not d.get("conditions"):
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
                if isinstance(op_raw, dict):
                    op_raw = op_raw.get("operation") or op_raw.get("operator") or op_raw.get("type") or "is equal to"
                elif op_raw is None:
                    op_raw = cond_dict.get("operation") or "is equal to"
                op_str = str(op_raw).strip()
                op = LEGACY_OPERATOR_MAP.get(op_str.lower().replace("-", "_"), LEGACY_OPERATOR_MAP.get(op_str, op_str))
                d["conditions"] = [
                    {
                        "id": "legacy",
                        "left": cond_dict.get("left", cond_dict.get("leftValue", "")),
                        "operator": op,
                        "right": cond_dict.get("right", cond_dict.get("rightValue", "")),
                        "combinator": "AND",
                    }
                ]
            elif "leftValue" in d or "left" in d:
                op_raw = d.get("operator")
                if isinstance(op_raw, dict):
                    op_raw = op_raw.get("operation") or op_raw.get("operator") or op_raw.get("type") or "is equal to"
                elif op_raw is None:
                    op_raw = d.get("operation") or "is equal to"
                op_str = str(op_raw).strip()
                op = LEGACY_OPERATOR_MAP.get(op_str.lower().replace("-", "_"), LEGACY_OPERATOR_MAP.get(op_str, op_str))
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
                c_dict: dict[str, Any]
                if isinstance(c, dict):
                    c_dict = dict(c)
                elif hasattr(c, "model_dump"):
                    c_dict = getattr(c, "model_dump")()
                elif hasattr(c, "__dict__"):
                    c_dict = dict(getattr(c, "__dict__"))
                else:
                    continue

                op_raw = c_dict.get("operator")
                if isinstance(op_raw, dict):
                    op_raw = op_raw.get("operation") or op_raw.get("operator") or op_raw.get("type") or "is equal to"
                elif op_raw is None:
                    op_raw = c_dict.get("operation") or "is equal to"
                op_str = str(op_raw).strip()
                op = LEGACY_OPERATOR_MAP.get(op_str.lower().replace("-", "_"), LEGACY_OPERATOR_MAP.get(op_str, op_str))

                left_val = c_dict.get("left")
                if left_val is None or left_val == "":
                    for k in ("leftValue", "value1", "left_value", "lhs", "variable"):
                        if k in c_dict and c_dict[k] is not None:
                            left_val = c_dict[k]
                            break
                if left_val is None:
                    left_val = ""

                right_val = c_dict.get("right")
                if right_val is None or right_val == "":
                    for k in ("rightValue", "value2", "right_value", "rhs", "value"):
                        if k in c_dict and c_dict[k] is not None:
                            right_val = c_dict[k]
                            break
                if right_val is None:
                    right_val = ""

                if isinstance(left_val, str) and left_val.strip().startswith("={") and left_val.strip().endswith("}"):
                    left_val = left_val.strip()[1:]
                if isinstance(right_val, str) and right_val.strip().startswith("={") and right_val.strip().endswith("}"):
                    right_val = right_val.strip()[1:]

                comb = c_dict.get("combinator", "AND")
                if idx == 0:
                    comb = "AND"
                elif str(comb).upper() not in ("AND", "OR"):
                    comb = "AND"
                else:
                    comb = str(comb).upper()

                new_conds.append({
                    "id": c_dict.get("id") or f"cond_{idx}",
                    "left": left_val,
                    "operator": op,
                    "right": right_val,
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
