"""Sub-workflow node.

Executes another workflow as a sub-workflow, passing input items as
the trigger data. Returns the sub-workflow's output items.

Parameters:
  - source: database or defineBelow
  - workflow_selector: list or id
  - workflow_id: the ID of the workflow to execute
  - workflow_json: direct workflow JSON definition
  - mode: onceWithAll (pass all items in one run) or onceForEach (run individually per item)
  - options: waitForSubWorkflowCompletion, etc.
  - data: optional additional data to pass to the sub-workflow

Hardening:
- Recursion guard: nesting deeper than MAX_SUBWORKFLOW_DEPTH fails with
  a typed SUBWORKFLOW_DEPTH_EXCEEDED error.
- Cancellation propagates down.
- Fire-and-forget support if waitForSubWorkflowCompletion is False.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine import expressions as _expr
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

#: Maximum sub-workflow nesting depth (parent counts as depth 0).
MAX_SUBWORKFLOW_DEPTH = 5


class SubWorkflowParams(BaseModel):
    source: Literal["database", "defineBelow"] = Field(
        default="database",
        description="Workflow source: database or defineBelow",
    )
    workflow_selector: Literal["list", "id"] = Field(
        default="list",
        description="Workflow selection mode: list or id",
    )
    workflow_id: str = Field(
        default="",
        description="ID of the workflow to execute",
    )
    workflow_json: str | dict[str, Any] = Field(
        default="",
        description="Workflow definition JSON if source=defineBelow",
    )
    mode: Literal["onceWithAll", "onceForEach"] = Field(
        default="onceWithAll",
        description="Execution mode: onceWithAll or onceForEach",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Options such as waitForSubWorkflowCompletion",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional data to pass",
    )


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
        from app.models import WorkflowRecord
        from app.schemas.workflow import Workflow as WorkflowSchema
        from app.engine.executor import execute_workflow

        child_depth = ctx.execution_depth + 1
        if child_depth > MAX_SUBWORKFLOW_DEPTH:
            raise NodeExecutionError(
                f"Sub-workflow nesting exceeds MAX_SUBWORKFLOW_DEPTH={MAX_SUBWORKFLOW_DEPTH} "
                f"(this node would run at depth {child_depth}).",
                code="SUBWORKFLOW_DEPTH_EXCEEDED",
                node_id=ctx.node_id,
                retryable=False,
            )

        wait_for_completion = bool(params.options.get("waitForSubWorkflowCompletion", True))

        # 1. Determine the target workflow schema
        workflow: WorkflowSchema | None = None
        target_wf_id = params.workflow_id

        # Resolve expression if present in workflow_id
        if isinstance(target_wf_id, str) and "{{" in target_wf_id:
            first_item = input_items[0] if input_items else {}
            target_wf_id = str(_expr.resolve(target_wf_id, {"$json": first_item}))

        if params.source == "defineBelow":
            raw_def = params.workflow_json
            if isinstance(raw_def, str):
                try:
                    raw_def = json.loads(raw_def)
                except Exception as e:
                    raise NodeExecutionError(
                        f"Invalid JSON provided in Define Below: {e}",
                        code="INVALID_SUBWORKFLOW_JSON",
                        node_id=ctx.node_id,
                    ) from e
            if not isinstance(raw_def, dict):
                raise NodeExecutionError(
                    "Workflow definition in Define Below must be a valid JSON object.",
                    code="INVALID_SUBWORKFLOW_JSON",
                    node_id=ctx.node_id,
                )
            workflow = WorkflowSchema.model_validate(raw_def)
        else:
            if not target_wf_id or not target_wf_id.strip():
                raise NodeExecutionError(
                    "No sub-workflow selected. Please select a workflow to execute.",
                    code="SUBWORKFLOW_NOT_SELECTED",
                    node_id=ctx.node_id,
                )

            db = get_session()
            try:
                workflow_record = db.execute(
                    select(WorkflowRecord).where(
                        WorkflowRecord.id == target_wf_id.strip(),
                        WorkflowRecord.deleted_at.is_(None),
                    )
                ).scalar_one_or_none()

                if workflow_record is None:
                    raise NodeExecutionError(
                        f"Sub-workflow '{target_wf_id}' not found.",
                        code="SUBWORKFLOW_NOT_FOUND",
                        node_id=ctx.node_id,
                        retryable=False,
                    )

                from app.api.access import get_permission
                perm = get_permission(db, target_wf_id.strip(), type("User", (), {"id": ctx.user_id})())  # type: ignore[arg-type]
                if perm is None or perm == "view":
                    raise NodeExecutionError(
                        f"Insufficient permissions to run sub-workflow '{target_wf_id}'.",
                        code="SUBWORKFLOW_ACCESS_DENIED",
                        node_id=ctx.node_id,
                        retryable=False,
                    )

                workflow = WorkflowSchema.model_validate(workflow_record.data)
            finally:
                db.close()

        if workflow is None:
            raise NodeExecutionError("Failed to load sub-workflow schema.", node_id=ctx.node_id)

        child_event_sink = ctx._emit_event if ctx._emit_event is not None else None

        async def _exec_child(trigger_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            child_execution_id = f"sub_{uuid.uuid4().hex[:12]}"
            res = await execute_workflow(
                workflow=workflow,
                trigger_items=trigger_items,
                execution_id=child_execution_id,
                http_client=ctx.http_client,
                cancel_event=ctx.cancel_event,
                event_sink=child_event_sink,
                credential_resolver=ctx._credential_resolver,
                env_vars=ctx.env_vars or None,
                execution_depth=child_depth,
                workspace_id=ctx.workspace_id,
                user_id=ctx.user_id,
            )
            if res.status != "success":
                detail = f": {res.error}" if res.error is not None else "."
                raise NodeExecutionError(
                    f"Sub-workflow '{target_wf_id}' finished with status '{res.status}'{detail}",
                    code="SUBWORKFLOW_FAILED",
                    node_id=ctx.node_id,
                    retryable=False,
                )
            sources = {c.source for c in workflow.connections}
            terminal_ids = {n.id for n in workflow.nodes if n.id not in sources}
            out: list[dict[str, Any]] = []
            for nid in terminal_ids:
                nr = (res.results or {}).get(nid)
                if isinstance(nr, dict) and "main" in nr:
                    out.extend(nr["main"])
            if not out:
                # Fallback to last node output if no terminal node matched
                for nid, nr in (res.results or {}).items():
                    if isinstance(nr, dict) and "main" in nr:
                        out.extend(nr["main"])
            return out

        # 2. Fire and forget mode
        if not wait_for_completion:
            items_to_send = []
            for it in input_items:
                items_to_send.append({**it, **params.data})
            if not items_to_send:
                items_to_send = [params.data] if params.data else [{}]

            # Spawn task in background
            asyncio.create_task(_exec_child(items_to_send))
            return NodeResult(
                output_items=input_items or [{}],
                metadata={"status": "dispatched", "workflow_id": target_wf_id},
            )

        # 3. Synchronous execution modes
        if params.mode == "onceForEach" and len(input_items) > 1:
            aggregated_outputs: list[dict[str, Any]] = []
            for item in input_items:
                item_payload = [{**item, **params.data}]
                single_res = await _exec_child(item_payload)
                aggregated_outputs.extend(single_res)
            return NodeResult(
                output_items=aggregated_outputs or [{}],
                metadata={
                    "status": "success",
                    "workflow_id": target_wf_id,
                    "depth": child_depth,
                    "mode": "onceForEach",
                },
            )
        else:
            merged_items = []
            for item in input_items:
                merged_items.append({**item, **params.data})
            if not merged_items:
                merged_items = [params.data] if params.data else [{}]

            out_items = await _exec_child(merged_items)
            return NodeResult(
                output_items=out_items or [{}],
                metadata={
                    "status": "success",
                    "workflow_id": target_wf_id,
                    "depth": child_depth,
                    "mode": "onceWithAll",
                },
            )


ExecuteSubWorkflowNode = SubWorkflowNode

