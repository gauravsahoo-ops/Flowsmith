"""Human approval node.

Pauses the workflow until a human approves or rejects, then continues.
The pause is durable (spec 25.2): the node marks the execution
``waiting_approval`` in PostgreSQL and records ``pause_state``; the run
ends without touching downstream nodes. The approval inbox (or
``POST /api/executions/{id}/resume``) re-enqueues the execution with the
decision; the engine replays persisted node outputs up to this node and
the node consumes the decision:

- approved → passes its original input items through (metadata records
  who approved and when);
- rejected → fails the execution with ``APPROVAL_REJECTED`` so the run
  history shows a deliberate rejection, not a crash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class HumanApprovalParams(BaseModel):
    message: str = Field(default="Please approve this action", description="Approval message")
    approvers: list[int] = Field(default_factory=list, description="User IDs who can approve")
    timeout_hours: int = Field(default=24, ge=0, description="Hours before auto-reject (0 = no timeout)")


STORAGE_KEY = "_approval_data"


@register
class HumanApprovalNode(BaseNode[HumanApprovalParams]):
    node_type = "human_approval"
    display_name = "Human Approval"
    version = 1
    description = "Pause workflow and wait for human approval."
    category = "Logic"
    icon = "human_approval"
    parameters_schema = HumanApprovalParams

    async def run(
        self,
        ctx: NodeContext,
        params: HumanApprovalParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        decision = await ctx.storage.get(STORAGE_KEY)

        if decision is not None:
            # Resumed run: consume the recorded decision.
            approved = bool(decision.get("approved"))
            if not approved:
                raise NodeExecutionError(
                    f"The action was rejected by user #{decision.get('approved_by', '?')}.",
                    code="APPROVAL_REJECTED",
                    node_id=self.node_type,
                    retryable=False,
                )
            return NodeResult(
                output_items=input_items,
                metadata={
                    "success": True,
                    "approved": True,
                    "approved_by": decision.get("approved_by"),
                    "approved_at": decision.get("approved_at", ""),
                },
            )

        # First run: pause durably. Downstream nodes are not executed;
        # the engine keeps the execution open (status waiting_approval).
        from sqlalchemy import select

        from app.db import get_session
        from app.models import Execution

        db = get_session()
        try:
            execution = db.execute(
                select(Execution).where(Execution.id == ctx.execution_id)
            ).scalar_one_or_none()

            if execution:
                execution.status = "waiting_approval"
                execution.pause_state = {
                    "node_id": ctx.node_id,
                    "message": params.message,
                    "approvers": params.approvers,
                    # timeout_hours=0 means "no timeout" (documented v1 contract)
                    "timeout_hours": params.timeout_hours,
                    "paused_at": datetime.now(UTC).isoformat(),
                }
                execution.node_statuses = {
                    **(execution.node_statuses or {}),
                    ctx.node_id: "waiting_approval",
                }
                db.commit()

                # Emit event for WebSocket streaming
                ctx._emit_event({
                    "event": "node.waiting_approval",
                    "node_id": ctx.node_id,
                    "status": "waiting_approval",
                })
        finally:
            db.close()

        return NodeResult(
            output_items=[],
            metadata={
                "waiting_approval": True,
                "message": params.message,
                "approvers": params.approvers,
                "timeout_hours": params.timeout_hours,
            },
        )
