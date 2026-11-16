"""Human approval node.

Pauses the workflow until a human approves or rejects, then continues.
The pause is durable (spec 25.2): the node marks the execution
``waiting_approval`` in PostgreSQL and records ``pause_state``; the run
ends without touching downstream nodes. It also mirrors the pause into a
durable ``ApprovalRequest`` (risk tier 2) for the approval inbox, while the
execution row remains the authority for resuming the run. The approval
inbox (or ``POST /api/executions/{id}/resume``) re-enqueues the execution with
the decision; the engine replays persisted node outputs up to this node and
the node consumes the decision:

- approved → passes its original input items through (metadata records
  who approved and when);
- rejected → fails the execution with ``APPROVAL_REJECTED`` so the run
  history shows a deliberate rejection, not a crash.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

logger = logging.getLogger("nodes.human_approval")


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
        if (
            isinstance(decision, dict)
            and decision.get("node_id") is not None
            and decision.get("node_id") != ctx.node_id
        ):
            # A decision recorded for another approval node (for example an
            # upstream gate in a resumed run) must not be consumed here.
            decision = None

        if isinstance(decision, dict):
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
                # Durable nested approvals: the checkpoint stays on this
                # run's row, but the root ApprovalRequest belongs to the
                # top-level execution that owns the resume authority.
                owner = ctx.approval_owner if isinstance(ctx.approval_owner, dict) else {}

                def _owner(key: str, fallback: Any) -> Any:
                    return owner[key] if key in owner else fallback

                approval_run_id = owner.get("run_id") or ctx.execution_id
                approval_node_id = owner.get("node_id") or ctx.node_id

                execution.status = "waiting_approval"
                execution.pause_state = {
                    "node_id": ctx.node_id,
                    "type": "human_approval",
                    "message": params.message,
                    "approvers": params.approvers,
                    # timeout_hours=0 means "no timeout" (documented v1 contract)
                    "timeout_hours": params.timeout_hours,
                    "risk_tier": 2,
                    "paused_at": datetime.now(UTC).isoformat(),
                }
                execution.node_statuses = {
                    **(execution.node_statuses or {}),
                    ctx.node_id: "waiting_approval",
                }
                db.commit()

                # Mirror the pause into a durable approval record. The
                # execution row remains the resume authority, so a failure
                # here must never lose the pause or block the run.
                try:
                    from app.approvals import service as approvals
                    from app.models import ApprovalRequest

                    pending = db.execute(
                        select(ApprovalRequest).where(
                            ApprovalRequest.run_id == approval_run_id,
                            ApprovalRequest.node_id == approval_node_id,
                            ApprovalRequest.status == "pending",
                        )
                    ).scalars().first()
                    if pending is None:
                        request = approvals.create_request(
                            db,
                            run_id=approval_run_id,
                            node_id=approval_node_id,
                            workflow_id=_owner("workflow_id", execution.workflow_id),
                            organization_id=_owner(
                                "organization_id", execution.organization_id
                            ),
                            workspace_id=_owner("workspace_id", execution.workspace_id),
                            reason=params.message,
                            summary="Workflow approval gate",
                            requested_by=_owner("requested_by", execution.user_id),
                            approvers=params.approvers,
                            quorum=1,
                            # Preserve the v1 node contract: the workflow
                            # owner may also be the approver.
                            separation_of_duties=False,
                            ttl_seconds=(
                                params.timeout_hours * 3600
                                if params.timeout_hours > 0
                                else 30 * 86400
                            ),
                            risk_tier=2,
                        )
                    else:
                        request = pending
                    # Bind the resume to this exact pause. Without it, a
                    # later pause at the same node could be resumed by an
                    # older decision.
                    pause_state = dict(execution.pause_state or {})
                    pause_state["approval_id"] = request.id
                    execution.pause_state = pause_state
                    db.commit()
                except Exception:
                    logger.warning(
                        "Could not create durable approval request for execution %s node %s",
                        ctx.execution_id,
                        ctx.node_id,
                        exc_info=True,
                    )
                    db.rollback()

                # Emit event for WebSocket streaming (ctx.emit_event adds
                # execution_id so parent status maps can filter child events).
                ctx.emit_event(
                    "node.waiting_approval",
                    node_id=ctx.node_id,
                    status="waiting_approval",
                )
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
