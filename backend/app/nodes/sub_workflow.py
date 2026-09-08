"""Sub-workflow node.

Executes another workflow as a sub-workflow, passing input items as
the trigger data. Returns the sub-workflow's output items.

Parameters:
  - workflow_id: the ID of the workflow to execute
  - data: optional additional data to pass to the sub-workflow

Phase 8 hardening:
- Recursion guard: nesting deeper than MAX_SUBWORKFLOW_DEPTH fails with
  a typed SUBWORKFLOW_DEPTH_EXCEEDED error instead of recursing until
  the stack dies (the graph stays acyclic; this bounds parent->child
  chains, including accidental A -> B -> A cycles across workflows).
- Cancellation propagates down: cancelling the parent run cancels the
  child execution between nodes.
- A child that ends failed/cancelled/timeout fails this node with a
  typed error (unless continue_on_error is set upstream), so partial
  failures are never reported as success.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

#: Maximum sub-workflow nesting depth (parent counts as depth 0).
MAX_SUBWORKFLOW_DEPTH = 5


class SubWorkflowParams(BaseModel):
    workflow_id: str = Field(description="ID of the workflow to execute")
    data: dict[str, Any] = Field(default_factory=dict, description="Additional data to pass")


@register
class SubWorkflowNode(BaseNode[SubWorkflowParams]):
    node_type = "sub_workflow"
    display_name = "Execute Sub-workflow"
    version = 1
    description = "Helpers for calling other n8n workflows. Used for designing modular, microservice-like workflows."
    category = "Flow"
    icon = "sub_workflow"
    parameters_schema = SubWorkflowParams
    idempotency = "conditionally_idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: SubWorkflowParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from sqlalchemy import select
        from app.db import get_session
        from app.models import WorkflowRecord, Execution
        from app.engine.executor import execute_workflow
        import uuid

        child_depth = ctx.execution_depth + 1
        if child_depth > MAX_SUBWORKFLOW_DEPTH:
            raise NodeExecutionError(
                f"Sub-workflow nesting exceeds MAX_SUBWORKFLOW_DEPTH={MAX_SUBWORKFLOW_DEPTH} "
                f"(this node would run at depth {child_depth}).",
                code="SUBWORKFLOW_DEPTH_EXCEEDED",
                node_id=ctx.node_id,
                retryable=False,
            )

        db = get_session()
        try:
            # Load the sub-workflow
            workflow_record = db.execute(
                select(WorkflowRecord).where(
                    WorkflowRecord.id == params.workflow_id,
                    WorkflowRecord.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            if workflow_record is None:
                raise NodeExecutionError(
                    f"Sub-workflow '{params.workflow_id}' not found.",
                    code="SUBWORKFLOW_NOT_FOUND",
                    node_id=ctx.node_id,
                    retryable=False,
                )

            # Permission check: executing user must own or have edit access
            from app.api.access import get_permission
            perm = get_permission(db, params.workflow_id, type("User", (), {"id": ctx.user_id})())  # type: ignore[arg-type]
            if perm is None or perm == "view":
                raise NodeExecutionError(
                    f"Insufficient permissions to run sub-workflow '{params.workflow_id}'.",
                    code="SUBWORKFLOW_ACCESS_DENIED",
                    node_id=ctx.node_id,
                    retryable=False,
                )

            # Build trigger items from input
            trigger_items = []
            for item in input_items:
                merged = {**item, **params.data}
                trigger_items.append(merged)

            if not trigger_items:
                trigger_items = [params.data]

            # Execute the sub-workflow
            from app.schemas.workflow import Workflow as WorkflowSchema

            workflow = WorkflowSchema.model_validate(workflow_record.data)
            execution_id = f"sub_{uuid.uuid4().hex[:12]}"

            # Phase 8: propagate credential resolver and event sink so
            # the child execution can resolve credentials and stream
            # events back to the parent.
            from typing import Callable, Any as _Any
            child_event_sink = ctx._emit_event if ctx._emit_event is not None else None

            result = await execute_workflow(
                workflow=workflow,
                trigger_items=trigger_items,
                execution_id=execution_id,
                http_client=ctx.http_client,
                cancel_event=ctx.cancel_event,
                event_sink=child_event_sink,
                credential_resolver=ctx._credential_resolver,
                env_vars=ctx.env_vars or None,
                execution_depth=child_depth,
                workspace_id=ctx.workspace_id,
                user_id=ctx.user_id,
            )

            if result.status != "success":
                detail = f": {result.error}" if result.error is not None else "."
                raise NodeExecutionError(
                    f"Sub-workflow '{params.workflow_id}' finished with status "
                    f"'{result.status}'{detail}",
                    code="SUBWORKFLOW_FAILED",
                    node_id=ctx.node_id,
                    retryable=False,
                )

            # Collect output items from terminal nodes' results
            output_items = []
            for node_result in (result.results or {}).values():
                if isinstance(node_result, dict) and "main" in node_result:
                    output_items.extend(node_result["main"])

            return NodeResult(
                output_items=output_items or [{}],
                metadata={
                    "execution_id": execution_id,
                    "status": result.status,
                    "workflow_id": params.workflow_id,
                    "depth": child_depth,
                },
            )
        finally:
            db.close()


ExecuteSubWorkflowNode = SubWorkflowNode
from app.nodes.registry import NODE_REGISTRY  # noqa: E402
NODE_REGISTRY["execute_sub_workflow"] = SubWorkflowNode
