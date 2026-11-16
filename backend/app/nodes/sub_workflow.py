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

Durable nested approvals:
- A database-sourced, awaited child gets a checkpoint ``Execution`` row with
  a deterministic id derived from the parent execution + node + mode + item.
  The row is created before the child runs; no queue job and no independent
  resume path are created.
- ``onceForEach`` runs its items sequentially and keeps one checkpoint row per
  item, so completed items are reused verbatim on resume. When any child
  pauses for human/tool approval, the parent pauses too and stores a
  public-only descriptor (including the paused ``item_index``). The parent
  execution remains the resume authority; on resume the paused item is
  re-entered with its persisted outputs (so completed side effects are not
  repeated), then later items continue.
- ``defineBelow`` children and fire-and-forget children cannot be
  checkpointed, so a pause raises the typed
  ``SUBWORKFLOW_PAUSE_UNSUPPORTED`` error.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine import expressions as _expr
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

logger = logging.getLogger("sub_workflow")

# Keep strong refs to fire-and-forget child executions so tasks are never
# garbage-collected mid-flight, and surface their failures in the log.
_BG_TASKS: set[asyncio.Task] = set()

#: Per-run KV key carrying the approval decision on a resumed execution.
STORAGE_KEY = "_approval_data"


def _spawn_background(coro: Any) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BG_TASKS.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("background child execution failed: %s", t.exception())

    task.add_done_callback(_done)
    return task

#: Maximum sub-workflow nesting depth (parent counts as depth 0).
MAX_SUBWORKFLOW_DEPTH = 5


def child_execution_id(
    parent_execution_id: str,
    node_id: str,
    mode: str,
    item_index: int,
    target_workflow_id: str,
) -> str:
    """Deterministic checkpoint id for one awaited child run.

    Determinism is what makes resume idempotent: the resumed parent computes
    the same id and re-enters the existing child checkpoint instead of
    creating a second one.
    """
    raw = f"{parent_execution_id}|{node_id}|{mode}|{item_index}|{target_workflow_id}"
    return "sub_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]


def _node_type(workflow: Any, node_id: str | None) -> str | None:
    if not node_id:
        return None
    for node in workflow.nodes:
        if node.id == node_id:
            return str(node.type)
    return None


def _terminal_outputs(
    workflow: Any, outputs: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Extract the child's terminal-node items (existing success contract)."""
    outputs = outputs or {}
    sources = {c.source for c in workflow.connections}
    terminal_ids = {n.id for n in workflow.nodes if n.id not in sources}
    out: list[dict[str, Any]] = []
    for nid in terminal_ids:
        nr = outputs.get(nid)
        if isinstance(nr, dict) and "main" in nr:
            out.extend(nr["main"])
    if not out:
        # Fallback to last node output if no terminal node matched
        for nr in outputs.values():
            if isinstance(nr, dict) and "main" in nr:
                out.extend(nr["main"])
    return out


def _may_pause_statically(workflow: Any) -> bool:
    """Whether the child contains a node we know will stop for approval.

    Only ``human_approval`` is statically detectable. An agent's gated tool
    call depends on runtime policy, so it is caught by the pause guard when
    the child actually stops.
    """
    return any(node.type == "human_approval" for node in workflow.nodes)


def _pause_descriptor(
    *,
    ctx: NodeContext,
    workflow: Any,
    child_id: str,
    child_pause_state: dict[str, Any],
    mode: str,
    item_index: int,
    item_total: int,
    depth: int,
) -> dict[str, Any]:
    """Public parent pause metadata — never child results/trace/state."""
    child_node_id = child_pause_state.get("node_id")
    child_pause_type = child_pause_state.get("type")
    if not child_pause_type:
        child_pause_type = _node_type(workflow, child_node_id)
    paused_at = child_pause_state.get("paused_at") or datetime.now(UTC).isoformat()
    return {
        "type": "sub_workflow",
        "node_id": ctx.node_id,
        "child_execution_id": child_id,
        "child_workflow_id": workflow.id,
        "child_node_id": child_node_id,
        "child_pause_type": child_pause_type,
        "message": child_pause_state.get("message"),
        "approvers": list(child_pause_state.get("approvers") or []),
        "timeout_hours": child_pause_state.get("timeout_hours"),
        "tool_name": child_pause_state.get("tool_name"),
        "risk_tier": child_pause_state.get("risk_tier"),
        "approval_id": child_pause_state.get("approval_id"),
        "paused_at": paused_at,
        "mode": mode,
        "item_index": item_index,
        "item_total": item_total,
        "depth": depth,
    }


def _paused_result(
    *,
    ctx: NodeContext,
    workflow: Any,
    child_id: str,
    child_pause_state: dict[str, Any],
    mode: str,
    item_index: int,
    item_total: int,
    depth: int,
) -> NodeResult:
    descriptor = _pause_descriptor(
        ctx=ctx,
        workflow=workflow,
        child_id=child_id,
        child_pause_state=child_pause_state,
        mode=mode,
        item_index=item_index,
        item_total=item_total,
        depth=depth,
    )
    return NodeResult(
        output_items=[],
        metadata={
            "waiting_approval": True,
            "type": "sub_workflow",
            "child_execution_id": child_id,
            "pause_state": descriptor,
            "message": descriptor.get("message"),
        },
    )


def _child_results(result: Any) -> dict[str, Any]:
    return {
        "outputs": dict(result.results or {}),
        "inputs": dict(result.inputs or {}),
    }


def _persist_child_terminal(child_id: str, result: Any) -> None:
    """Finalize the checkpoint row; it is history, not a resumable run."""
    from app.db import get_session
    from app.models import Execution
    from app.orchestration.finalizer import node_statuses

    db = get_session()
    try:
        row = db.get(Execution, child_id)
        if row is None:
            return
        computed = node_statuses(result.events, execution_id=child_id)
        row.status = result.status
        row.results = _child_results(result)
        row.trace = result.trace
        row.node_statuses = {**(row.node_statuses or {}), **computed}
        row.error = result.error.to_dict() if result.error else None
        row.finished_at = datetime.now(UTC)
        row.pause_state = None
        db.commit()
    finally:
        db.close()


def _persist_child_pause(
    child_id: str,
    workflow: Any,
    result: Any,
) -> dict[str, Any] | None:
    """Store the child checkpoint pause and return its merged pause state."""
    from app.db import get_session
    from app.models import Execution
    from app.orchestration.finalizer import node_statuses

    db = get_session()
    try:
        row = db.get(Execution, child_id)
        if row is None:
            return None
        # The node already wrote its own pause state (approval_id, encrypted
        # tool state, ...). Merge the engine's pause info on top and pin the
        # paused node id.
        child_pause_state = dict(row.pause_state or {})
        info = dict(result.pause_info or {})
        info_pause = info.get("pause_state")
        if isinstance(info_pause, dict):
            child_pause_state.update(info_pause)
        if result.paused_node_id:
            child_pause_state["node_id"] = result.paused_node_id
        if not child_pause_state.get("type"):
            child_pause_state["type"] = (
                _node_type(workflow, child_pause_state.get("node_id")) or "approval"
            )
        if not child_pause_state.get("paused_at"):
            child_pause_state["paused_at"] = datetime.now(UTC).isoformat()

        row.status = "waiting_approval"
        row.pause_state = child_pause_state
        row.results = _child_results(result)
        row.trace = result.trace
        row.node_statuses = {
            **(row.node_statuses or {}),
            **node_statuses(result.events, execution_id=child_id),
        }
        row.error = None
        row.finished_at = None
        db.commit()
        return child_pause_state
    finally:
        db.close()


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
    description = "Helpers for calling other workflows. Used for designing modular, microservice-like workflows."
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
        from app.models import Execution, WorkflowRecord
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

        mode = params.mode
        multi_item_foreach = mode == "onceForEach" and len(input_items) > 1

        # Cases that cannot be checkpointed must never silently lose a child
        # pause. Reject statically-detectable pauses up front with a typed
        # error; runtime-only pauses are rejected by the pause guard below.
        if _may_pause_statically(workflow):
            if not wait_for_completion:
                raise NodeExecutionError(
                    f"Sub-workflow '{target_wf_id}' can pause for approval and "
                    "cannot run fire-and-forget.",
                    code="SUBWORKFLOW_PAUSE_UNSUPPORTED",
                    node_id=ctx.node_id,
                    retryable=False,
                )

        child_event_sink = ctx._emit_event if ctx._emit_event is not None else None

        def _merged_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            merged = [{**it, **params.data} for it in items]
            if not merged:
                merged = [params.data] if params.data else [{}]
            return merged

        def _success_result(out_items: list[dict[str, Any]], *, child_id: str | None = None) -> NodeResult:
            metadata: dict[str, Any] = {
                "status": "success",
                "workflow_id": target_wf_id,
                "depth": child_depth,
                "mode": mode,
            }
            if child_id is not None:
                metadata["child_execution_id"] = child_id
            return NodeResult(output_items=out_items or [{}], metadata=metadata)

        async def _exec_child(trigger_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """Legacy, non-checkpointed child execution.

            Used for defineBelow, fire-and-forget and multi-item onceForEach
            children, and for direct engine calls with no parent execution
            row. A pause here cannot be made durable, so it raises the
            explicit unsupported error instead of looking like a failure.
            """
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
            if res.paused or res.status == "waiting_approval":
                # No durable child row exists for these modes. Fail with an
                # explicit code instead of the misleading SUBWORKFLOW_FAILED,
                # and never leave the parent waiting on an unpersisted child.
                raise NodeExecutionError(
                    f"Sub-workflow '{target_wf_id}' paused for approval; "
                    "nested approval pauses are not supported in this mode.",
                    code="SUBWORKFLOW_PAUSE_UNSUPPORTED",
                    node_id=ctx.node_id,
                    retryable=False,
                )
            if res.status != "success":
                detail = f": {res.error}" if res.error is not None else "."
                raise NodeExecutionError(
                    f"Sub-workflow '{target_wf_id}' finished with status '{res.status}'{detail}",
                    code="SUBWORKFLOW_FAILED",
                    node_id=ctx.node_id,
                    retryable=False,
                )
            return _terminal_outputs(workflow, res.results)

        def _raise_stored_failure(row: Any, workflow_id: str) -> None:
            err = row.error or {}
            code = err.get("code")
            message = err.get("message") or ""
            if code == "APPROVAL_REJECTED":
                raise NodeExecutionError(
                    message or "Sub-workflow approval was rejected.",
                    code="APPROVAL_REJECTED",
                    node_id=ctx.node_id,
                    retryable=False,
                )
            detail = f": {message}" if message else "."
            raise NodeExecutionError(
                f"Sub-workflow '{workflow_id}' finished with status '{row.status}'{detail}",
                code="SUBWORKFLOW_FAILED",
                node_id=ctx.node_id,
                retryable=False,
            )

        # 2. Fire and forget mode
        if not wait_for_completion:
            items_to_send = _merged_items(input_items)
            # Spawn task in background (strong ref + error logging)
            _spawn_background(_exec_child(items_to_send))
            return NodeResult(
                output_items=input_items or [{}],
                metadata={"status": "dispatched", "workflow_id": target_wf_id},
            )

        # 3. Resolve durability. The parent execution row is the resume
        # authority. Direct engine calls (unit tests, embedded invocations)
        # may have no row: keep the legacy behavior for them.
        parent_row = None
        parent_organization_id: str | None = None
        parent_user_id: int | None = None
        if ctx.execution_id:
            db = get_session()
            try:
                parent_row = db.get(Execution, ctx.execution_id)
                if parent_row is not None:
                    parent_organization_id = parent_row.organization_id
                    parent_user_id = parent_row.user_id
            finally:
                db.close()

        durable = parent_row is not None

        # Inline defineBelow children have no workflow row of their own; point
        # the checkpoint's FK at the parent workflow while the snapshot keeps
        # the inline child definition authoritative.
        child_workflow_id = (
            parent_row.workflow_id
            if parent_row is not None and params.source != "database"
            else workflow.id
        )

        if not durable:
            # Without a parent checkpoint row nothing can own a nested pause.
            # Fail before running any item instead of losing the pause (or
            # repeating completed work) halfway through a multi-item loop.
            if multi_item_foreach and _may_pause_statically(workflow):
                raise NodeExecutionError(
                    f"Sub-workflow '{target_wf_id}' can pause for approval; "
                    "multi-item onceForEach pauses require a durable parent execution.",
                    code="SUBWORKFLOW_PAUSE_UNSUPPORTED",
                    node_id=ctx.node_id,
                    retryable=False,
                )
            if multi_item_foreach:
                aggregated_outputs: list[dict[str, Any]] = []
                for item in input_items:
                    single_res = await _exec_child(_merged_items([item]))
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
            out_items = await _exec_child(_merged_items(input_items))
            return _success_result(out_items)

        # 4. Durable path: one deterministic child checkpoint per item. The
        # root ApprovalRequest belongs to the top-level execution; the child
        # rows are only checkpoints.
        if isinstance(ctx.approval_owner, dict):
            approval_owner = ctx.approval_owner
        else:
            approval_owner = {
                "run_id": ctx.execution_id,
                "node_id": ctx.node_id,
                "workflow_id": ctx.workflow_id,
                "organization_id": parent_organization_id,
                "workspace_id": ctx.workspace_id,
                "requested_by": ctx.user_id or parent_user_id,
            }

        merged_items = _merged_items(input_items)
        if mode == "onceForEach":
            item_batches = [[item] for item in merged_items]
        else:
            item_batches = [merged_items]
        item_total = len(item_batches)

        decision = await ctx.storage.get(STORAGE_KEY)
        is_resume = (
            isinstance(decision, dict)
            and decision.get("node_id") is not None
            and decision.get("node_id") == ctx.node_id
        )

        # A resumed parent must re-enter the exact paused child checkpoint.
        # The parent descriptor records which item paused, so a vanished
        # checkpoint fails instead of silently repeating its side effects.
        expected_paused_index: int | None = None
        if is_resume and parent_row is not None:
            parent_pause = parent_row.pause_state or {}
            if (
                parent_pause.get("type") == "sub_workflow"
                and parent_pause.get("node_id") == ctx.node_id
                and isinstance(parent_pause.get("item_index"), int)
            ):
                expected_paused_index = parent_pause["item_index"]

        aggregated_outputs: list[dict[str, Any]] = []
        executed_child_ids: list[str] = []

        for item_index, item_trigger_items in enumerate(item_batches):
            child_id = child_execution_id(
                ctx.execution_id,
                ctx.node_id,
                mode,
                item_index,
                workflow.id,
            )

            # Load (or create) the deterministic child checkpoint row.
            created = False
            db = get_session()
            try:
                row = db.get(Execution, child_id)
            finally:
                db.close()

            if row is None and is_resume and (
                item_index == 0 or item_index == expected_paused_index
            ):
                raise NodeExecutionError(
                    f"Sub-workflow checkpoint '{child_id}' for '{target_wf_id}' "
                    "no longer exists; the child cannot be resumed safely.",
                    code="SUBWORKFLOW_CHILD_NOT_FOUND",
                    node_id=ctx.node_id,
                    retryable=False,
                )

            if row is None:
                from sqlalchemy.exc import IntegrityError

                db = get_session()
                try:
                    db.add(Execution(
                        id=child_id,
                        workflow_id=child_workflow_id,
                        user_id=ctx.user_id or parent_user_id,
                        workflow_version=workflow.version,
                        workflow_data=workflow.model_dump(mode="json"),
                        trigger="sub_workflow",
                        trigger_data=item_trigger_items,
                        status="running",
                        parent_execution_id=ctx.execution_id,
                        workspace_id=ctx.workspace_id,
                        organization_id=parent_organization_id,
                    ))
                    db.commit()
                    created = True
                except IntegrityError:
                    # A concurrent duplicate created the same deterministic row.
                    db.rollback()
                    created = False
                finally:
                    db.close()

            if not created:
                db = get_session()
                try:
                    row = db.get(Execution, child_id)
                finally:
                    db.close()
                if row is None:
                    raise NodeExecutionError(
                        f"Sub-workflow checkpoint '{child_id}' could not be created.",
                        code="SUBWORKFLOW_CHILD_NOT_FOUND",
                        node_id=ctx.node_id,
                        retryable=False,
                    )
                assert row is not None

                if row.status == "success":
                    # Completed items are durable checkpoints: reuse their
                    # persisted outputs without repeating their side effects.
                    outputs = (row.results or {}).get("outputs") or {}
                    aggregated_outputs.extend(_terminal_outputs(workflow, outputs))
                    executed_child_ids.append(child_id)
                    continue

                if row.status == "waiting_approval":
                    if not is_resume:
                        # Duplicate delivery without a decision: re-surface the
                        # existing pause instead of running the child again.
                        return _paused_result(
                            ctx=ctx,
                            workflow=workflow,
                            child_id=child_id,
                            child_pause_state=dict(row.pause_state or {}),
                            mode=mode,
                            item_index=item_index,
                            item_total=item_total,
                            depth=child_depth,
                        )
                    # Resume this item below.
                elif row.status == "running":
                    raise NodeExecutionError(
                        f"Sub-workflow '{target_wf_id}' is still running "
                        f"(checkpoint '{child_id}'); refusing to duplicate its side effects.",
                        code="SUBWORKFLOW_CHILD_BUSY",
                        node_id=ctx.node_id,
                        retryable=False,
                    )
                else:
                    # failed / cancelled / timeout: propagate the stored outcome.
                    _raise_stored_failure(row, target_wf_id)

            # 5. Execute the child. On resume, replay completed outputs and pass
            # a child-scoped decision (never the encrypted checkpoint state).
            child_workflow = workflow
            trigger_items = item_trigger_items
            initial_results = None
            storage_seed = None
            if not created:
                assert row is not None
                child_pause_state = dict(row.pause_state or {})
                child_workflow = WorkflowSchema.model_validate(row.workflow_data)
                trigger_items = list(row.trigger_data or item_trigger_items)
                child_decision = {
                    "approved": bool(decision.get("approved")) if isinstance(decision, dict) else False,
                    "approved_by": (decision or {}).get("approved_by"),
                    "approved_at": (decision or {}).get("approved_at", ""),
                    "node_id": child_pause_state.get("node_id"),
                    "pause_type": child_pause_state.get("type"),
                    "tool_name": child_pause_state.get("tool_name"),
                    "approval_id": child_pause_state.get("approval_id")
                    or (decision or {}).get("approval_id"),
                    # No "state": the child agent reads its encrypted checkpoint
                    # from its own execution row as the fallback.
                }
                prior_outputs = (row.results or {}).get("outputs") or {}
                initial_results = {
                    nid: by_handle
                    for nid, by_handle in prior_outputs.items()
                    if nid != child_pause_state.get("node_id")
                } or None
                storage_seed = {STORAGE_KEY: child_decision}

                # Keep pause_state until the child re-pauses/finishes: the agent's
                # encrypted-state fallback reads it from this row.
                db = get_session()
                try:
                    run_row = db.get(Execution, child_id)
                    if run_row is not None:
                        run_row.status = "running"
                        run_row.error = None
                        run_row.finished_at = None
                        db.commit()
                finally:
                    db.close()

            try:
                res = await execute_workflow(
                    workflow=child_workflow,
                    trigger_items=trigger_items,
                    execution_id=child_id,
                    http_client=ctx.http_client,
                    cancel_event=ctx.cancel_event,
                    event_sink=child_event_sink,
                    credential_resolver=ctx._credential_resolver,
                    env_vars=ctx.env_vars or None,
                    initial_results=initial_results,
                    storage_seed=storage_seed,
                    execution_depth=child_depth,
                    workspace_id=ctx.workspace_id,
                    user_id=ctx.user_id,
                    approval_owner=approval_owner,
                )
            except asyncio.CancelledError:
                from app.engine.executor import ExecutionResult

                _persist_child_terminal(
                    child_id,
                    ExecutionResult(
                        status="cancelled",
                        error=NodeExecutionError(
                            "Execution cancelled while running the sub-workflow.",
                            code="CANCELLED",
                            node_id=ctx.node_id,
                            retryable=False,
                        ),
                    ),
                )
                raise
            except Exception as exc:
                # A validation/setup failure happens before execute_workflow can
                # return a failed result; never leave the checkpoint "running".
                from app.engine.executor import ExecutionResult

                _persist_child_terminal(
                    child_id,
                    ExecutionResult(
                        status="failed",
                        error=NodeExecutionError(
                            str(exc),
                            code="SUBWORKFLOW_FAILED",
                            node_id=ctx.node_id,
                            retryable=False,
                        ),
                    ),
                )
                raise

            if res.paused or res.status == "waiting_approval":
                child_pause_state = _persist_child_pause(
                    child_id, child_workflow, res
                )
                if child_pause_state is None:
                    raise NodeExecutionError(
                        f"Sub-workflow checkpoint '{child_id}' disappeared while "
                        "persisting its approval pause.",
                        code="SUBWORKFLOW_CHILD_NOT_FOUND",
                        node_id=ctx.node_id,
                        retryable=False,
                    )
                return _paused_result(
                    ctx=ctx,
                    workflow=child_workflow,
                    child_id=child_id,
                    child_pause_state=child_pause_state,
                    mode=mode,
                    item_index=item_index,
                    item_total=item_total,
                    depth=child_depth,
                )

            _persist_child_terminal(child_id, res)
            if res.status != "success":
                error = res.error
                if error is not None and getattr(error, "code", None) == "APPROVAL_REJECTED":
                    raise NodeExecutionError(
                        error.message,
                        code="APPROVAL_REJECTED",
                        node_id=ctx.node_id,
                        retryable=False,
                    )
                detail = f": {error}" if error is not None else "."
                raise NodeExecutionError(
                    f"Sub-workflow '{target_wf_id}' finished with status '{res.status}'{detail}",
                    code="SUBWORKFLOW_FAILED",
                    node_id=ctx.node_id,
                    retryable=False,
                )

            aggregated_outputs.extend(_terminal_outputs(child_workflow, res.results))
            executed_child_ids.append(child_id)

        return _success_result(
            aggregated_outputs,
            child_id=executed_child_ids[0] if len(item_batches) == 1 else None,
        )


ExecuteSubWorkflowNode = SubWorkflowNode
