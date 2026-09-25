"""Set Variable node — updates workflow execution context and persists workspace environment variables.

Supports:
- Scope: "workspace" (persisted to workspace Environment in DB and exposed to {{ $env.KEY }})
         or "workflow" (stored in execution context and input items for downstream nodes)
- Dynamic expressions (e.g. {{ $json.access_token }}, {{ $now }})
- Secure encryption for secret variables
"""

from __future__ import annotations

import logging
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.engine import expressions

logger = logging.getLogger(__name__)


class VariableAssignment(BaseModel):
    key: str = Field(min_length=1, description="Variable name (e.g. AUTH_TOKEN, LAST_SYNC_ID)")
    value: Any = Field(default="", description="Value or expression (e.g. {{ $json.token }})")
    scope: Literal["workspace", "workflow"] = Field(default="workspace", description="Storage scope")
    is_secret: bool = Field(default=False, description="Whether to encrypt and mask as secret in workspace")


class SetVariableParams(BaseModel):
    variables: list[VariableAssignment] = Field(default_factory=list, description="Variables to assign")
    # Convenience single-pair fields for UI compatibility
    key: str | None = None
    value: Any = None
    scope: Literal["workspace", "workflow"] = "workspace"
    is_secret: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # If single key/value provided but variables list is empty, convert to list
        vars_list = list(d.get("variables") or [])
        if d.get("key") and str(d["key"]).strip():
            k = str(d["key"]).strip()
            # If not already in variables list, prepend
            if not any(v.get("key") == k if isinstance(v, dict) else getattr(v, "key", None) == k for v in vars_list):
                vars_list.append({
                    "key": k,
                    "value": d.get("value", ""),
                    "scope": d.get("scope", "workspace"),
                    "is_secret": bool(d.get("is_secret", False)),
                })
        d["variables"] = vars_list
        return d


@register
class SetVariableNode(BaseNode):
    node_type = "set_variable"
    parameters_schema = SetVariableParams
    params_class = SetVariableParams

    async def run(
        self,
        ctx: NodeContext,
        params: SetVariableParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            input_items = [{}]

        assigned: dict[str, Any] = {}
        first_item = input_items[0] if input_items else {}

        # Expression evaluation context
        expr_ctx = dict(ctx.expression_context) if ctx.expression_context else {}
        expr_ctx["$json"] = first_item
        if "$env" not in expr_ctx or not isinstance(expr_ctx["$env"], dict):
            expr_ctx["$env"] = {}

        for assignment in params.variables:
            k = str(assignment.key).strip()
            if not k:
                continue

            raw_val = assignment.value
            # Resolve dynamic expressions (e.g. {{ $json.access_token }})
            if isinstance(raw_val, str) and "{{" in raw_val:
                resolved_val = expressions.resolve(raw_val, expr_ctx)
            else:
                resolved_val = raw_val

            assigned[k] = resolved_val

            # Update runtime execution expression context
            expr_ctx["$env"][k] = resolved_val
            if ctx.expression_context is not None:
                if "$env" not in ctx.expression_context:
                    ctx.expression_context["$env"] = {}
                ctx.expression_context["$env"][k] = resolved_val

            # If workspace scope: persist to database Environment table
            if assignment.scope == "workspace" and getattr(ctx, "workspace_id", None):
                try:
                    from app.db import get_session
                    from app.models.environment import Environment
                    from app.security.crypto import encrypt_text
                    from sqlalchemy import select

                    stored = encrypt_text(str(resolved_val)).decode()
                    with get_session() as db:
                        existing = db.execute(
                            select(Environment).where(
                                Environment.workspace_id == ctx.workspace_id,
                                Environment.key == k,
                            )
                        ).scalar_one_or_none()
                        if existing:
                            existing.value = stored
                            existing.is_secret = assignment.is_secret
                        else:
                            env = Environment(
                                workspace_id=ctx.workspace_id,
                                key=k,
                                value=stored,
                                is_secret=assignment.is_secret,
                            )
                            db.add(env)
                        db.commit()
                        logger.info("SetVariableNode persisted %s to workspace %s", k, ctx.workspace_id)
                except Exception as ex:
                    logger.warning("SetVariableNode failed to persist %s to DB: %s", k, ex)

        # Output items: return input items enriched with the new variables
        output_items = []
        for item in input_items:
            enriched = dict(item)
            # Add variables to item metadata
            enriched["_variables"] = assigned
            for k, v in assigned.items():
                if k not in enriched:
                    enriched[k] = v
            output_items.append(enriched)

        return NodeResult(output_items=output_items)
