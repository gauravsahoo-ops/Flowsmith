"""IF / Condition node — n8n-like with multi-conditions, AND/OR, convertTypes."""

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
        # Migrate legacy single condition to conditions list
        if "conditions" not in d or d["conditions"] is None:
            if "condition" in d and isinstance(d["condition"], dict):
                cond = d["condition"]
                # Normalize operator via legacy map
                op_raw = cond.get("operator")
                op_str = str(op_raw) if op_raw is not None else "is equal to"
                op = LEGACY_OPERATOR_MAP.get(op_str, op_str)
                # Create single condition row
                d["conditions"] = [
                    {
                        "id": "legacy",
                        "left": cond.get("left", ""),
                        "operator": op,
                        "right": cond.get("right", ""),
                        "combinator": "AND",
                    }
                ]
                # Keep condition for backward compat but not required
            elif "leftValue" in d or "left" in d:
                # Very old format
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
                # Default single empty condition - use a valid placeholder that won't fail validation
                d["conditions"] = [
                    {"id": "default", "left": "{{$json.value}}", "operator": "is equal to", "right": "", "combinator": "AND"}
                ]
        # Normalize conditions: ensure combinator for first is AND, and operators are mapped
        if isinstance(d.get("conditions"), list):
            new_conds = []
            for idx, c in enumerate(d["conditions"]):
                if not isinstance(c, dict):
                    continue
                # Map legacy operator
                op_raw = c.get("operator")
                op_str = str(op_raw) if op_raw is not None else "is equal to"
                op = LEGACY_OPERATOR_MAP.get(op_str, op_str)
                # Ensure combinator
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
            raise ValueError("At least one condition is required.")
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
                raise ValueError(f"Unsupported operator '{cond.operator}'.")
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
            from app.nodes.condition_base import evaluate_conditions
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
