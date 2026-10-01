"""IF / Condition node with multi-conditions, AND/OR logic, and convertTypes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.condition_base import (
    Condition,
    ConditionRow,
    evaluate_conditions,
    LEGACY_OPERATOR_MAP,
)
from app.nodes.registry import register


class IfConditionParams(BaseModel):
    # Legacy single condition (backward compat)
    condition: Condition | None = Field(default=None)
    # New multi-condition
    conditions: list[ConditionRow] | None = Field(default=None)
    combinator: Literal["AND", "OR"] = "AND"
    convertTypes: bool = Field(default=False, description="Convert types where required")
    # For backward compat with old workflows that had convertTypes as string or missing
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
                # Could be typed sections: {"string": [...], "number": [...], "boolean": [...]}
                typed_list = []
                for k, v in cond_dict.items():
                    if isinstance(v, list):
                        typed_list.extend(v)
                if typed_list:
                    extracted_list = typed_list

            d["conditions"] = extracted_list or []

        # Migrate legacy single condition to conditions list if empty
        if not d.get("conditions"):
            if "condition" in d and isinstance(d["condition"], dict):
                cond = d["condition"]
                op_raw = cond.get("operator")
                if isinstance(op_raw, dict):
                    op_raw = op_raw.get("operation") or op_raw.get("operator") or op_raw.get("type") or "is equal to"
                elif op_raw is None:
                    op_raw = cond.get("operation") or "is equal to"
                op_str = str(op_raw).strip()
                op = LEGACY_OPERATOR_MAP.get(op_str.lower().replace("-", "_"), LEGACY_OPERATOR_MAP.get(op_str, op_str))
                d["conditions"] = [
                    {
                        "id": "legacy",
                        "left": cond.get("left", cond.get("leftValue", "")),
                        "operator": op,
                        "right": cond.get("right", cond.get("rightValue", "")),
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
                    {"id": "default", "left": "{{$json.value}}", "operator": "is equal to", "right": "", "combinator": "AND"}
                ]

        # Normalize conditions: ensure combinator for first is AND, and operators/expressions are normalized
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

                # Handle operator
                op_raw = c_dict.get("operator")
                if isinstance(op_raw, dict):
                    op_raw = op_raw.get("operation") or op_raw.get("operator") or op_raw.get("type") or "is equal to"
                elif op_raw is None:
                    op_raw = c_dict.get("operation") or "is equal to"
                op_str = str(op_raw).strip()
                op = LEGACY_OPERATOR_MAP.get(op_str.lower().replace("-", "_"), LEGACY_OPERATOR_MAP.get(op_str, op_str))

                # Handle left and right values & expressions
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

                # Normalize ={{ expr }} -> {{ expr }}
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

        # Handle convertTypes alias
        if "convertTypes" not in d:
            if "convert_types" in d:
                d["convertTypes"] = bool(d.pop("convert_types"))
            elif "options" in d and isinstance(d["options"], dict) and "convertTypes" in d["options"]:
                d["convertTypes"] = bool(d["options"]["convertTypes"])
        return d

    @model_validator(mode="after")
    def _validate(self) -> "IfConditionParams":
        if not self.conditions:
            self.conditions = [
                ConditionRow(left="{{$json.value}}", operator="is equal to", right="", combinator="AND")
            ]
        for cond in self.conditions:
            if cond.left is None:
                cond.left = ""
            if cond.operator not in [
                "is equal to", "is not equal to",
                "contains", "does not contain",
                "starts with", "does not start with",
                "ends with", "does not end with",
                "matches regex", "does not match regex",
                "is empty", "is not empty",
                "is greater than", "is greater than or equal to",
                "is less than", "is less than or equal to",
                "is true", "is false",
                "is null", "is not null", "exists", "does not exist",
                "is before", "is after", "is before or equal to", "is after or equal to",
                # Legacy
                "equals", "not_equals", "greater_than", "less_than", "starts_with", "exists",
            ]:
                # Map via LEGACY_OPERATOR_MAP or fallback to 'is equal to'
                norm = LEGACY_OPERATOR_MAP.get(str(cond.operator).lower().replace("-", "_"))
                if norm:
                    cond.operator = norm
                else:
                    cond.operator = "is equal to"
        return self


__all__ = ["Condition", "IfConditionParams", "IfConditionNode"]


@register
class IfConditionNode(BaseNode[IfConditionParams]):
    node_type = "if_condition"
    display_name = "If"
    version = 2
    description = "Route items to different branches (true/false)"
    category = "Flow"
    icon = "if"
    parameters_schema = IfConditionParams
    input_handles = ["main"]
    output_handles = ["true", "false"]
    resolves_own_expressions = True

    async def run(
        self,
        ctx: NodeContext,
        params: IfConditionParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.engine import expressions as _expr
        from app.nodes.condition_base import ConditionRow

        # Normalize conditions
        conditions = params.conditions or []
        if not conditions and params.condition:
            # Fallback to legacy single
            conditions = [ConditionRow(
                left=params.condition.left,
                operator=LEGACY_OPERATOR_MAP.get(params.condition.operator, params.condition.operator),
                right=params.condition.right,
                combinator="AND",
            )]

        true_items: list[dict[str, Any]] = []
        false_items: list[dict[str, Any]] = []

        # For each input item, evaluate all conditions
        for item in input_items:
            # Build per-item context for expression resolution
            per_ctx = _expr.build_context(
                [item], {}, ctx.workflow_id, ctx.execution_id,
            )
            # Also add $json
            per_ctx["$json"] = item
            # Resolve each condition's left/right via expressions
            resolved_conds: list[ConditionRow] = []
            for cond in conditions:
                left_val = cond.left
                right_val = cond.right
                # Resolve left and right if they are strings containing {{
                if isinstance(left_val, str) and "{{" in left_val:
                    left_val = _expr.resolve(left_val, per_ctx)
                elif isinstance(left_val, str) and left_val.strip().startswith("$json."):
                    # Bare $json.field reference — resolve from item dict (supports nested paths)
                    field = left_val.strip()[len("$json."):]
                    parts = field.split(".")
                    resolved: Any = item
                    for part in parts:
                        if isinstance(resolved, dict):
                            resolved = resolved.get(part)
                        else:
                            resolved = None
                            break
                    left_val = resolved  # None if field doesn't exist (important for exists/is_null)

                if isinstance(right_val, str) and "{{" in right_val:
                    right_val = _expr.resolve(right_val, per_ctx)
                elif isinstance(right_val, str) and right_val.strip().startswith("$json."):
                    field = right_val.strip()[len("$json."):]
                    parts = field.split(".")
                    resolved_r: Any = item
                    for part in parts:
                        if isinstance(resolved_r, dict):
                            resolved_r = resolved_r.get(part)
                        else:
                            resolved_r = None
                            break
                    right_val = resolved_r

                resolved_conds.append(ConditionRow(
                    id=cond.id,
                    left=left_val,
                    operator=cond.operator,
                    right=right_val,
                    combinator=cond.combinator,
                ))

            # Evaluate
            try:
                is_true = evaluate_conditions(resolved_conds, item, convert_types=params.convertTypes)
            except Exception as e:
                # On evaluation error, treat as false and log
                from app.engine.errors import NodeExecutionError
                raise NodeExecutionError(f"Condition evaluation failed: {e}", code="INVALID_CONDITION", node_id="if_condition", retryable=False) from e

            if is_true:
                true_items.append(item)
            else:
                false_items.append(item)

        return NodeResult(output_by_handle={"true": true_items, "false": false_items})
