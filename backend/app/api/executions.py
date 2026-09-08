"""Execution endpoints (spec 9): run, list, detail, items, retry, cancel.

Runs flow through the job queue (Phase 15, spec 13): the API creates the
execution row in ``queued`` state and enqueues a job; a worker (the
embedded consumer by default, or external ``python -m app.queue.worker``
processes) claims it, transitions it to ``running``, executes and
persists the outcome (spec 25). Cancellation is cooperative and durable:
the endpoint marks the execution ``cancelling`` and the worker's monitor
picks it up (spec 36).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import accessible_ids, get_permission, get_workflow
from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.audit import EXECUTION_CANCEL, EXECUTION_RESUME, EXECUTION_RETRY, EXECUTION_RUN, log_event
from app.credentials.validator import validate_workflow_credentials
from app.db import get_db
from app.engine.errors import WorkflowValidationError
from app.metrics import execution_started
from app.models import Execution, User
from app.models.workflow import WorkflowRecord
from app.queue import get_queue
from app.queue.worker import ensure_embedded_consumer

router = APIRouter(tags=["executions"])
logger = logging.getLogger("api.executions")

IN_PROGRESS_STATUSES = frozenset({"queued", "running", "cancelling"})


class RunRequest(BaseModel):
    data: dict[str, Any] | list[dict[str, Any]] | None = None


class RetryRequest(BaseModel):
    """Phase 13 (workflow debugger): retry the whole execution (default)
    or safely re-run from one failed node, seeding upstream outputs."""

    node_id: str | None = None


class ResumeRequest(BaseModel):
    """Approve/reject decision for a paused execution (Phase 32)."""

    approved: bool = True


def _to_dict(rec: Execution) -> dict[str, Any]:
    return {
        "id": rec.id,
        "workflow_id": rec.workflow_id,
        "workflow_version": rec.workflow_version,
        "trigger": rec.trigger,
        "status": rec.status,
        "error": rec.error,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
        # Pause metadata (Phase 32): node_id/message while the run waits
        # on an approval decision.
        "pause_state": rec.pause_state,
    }


def start_execution(
    db: Session,
    *,
    workflow_id: str,
    user_id: int,
    version: int,
    workflow_data: dict,
    trigger: str,
    trigger_items: list[dict[str, Any]],
    workspace_id: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> str:
    """Create the execution row (queued) and enqueue the job (spec 25/13).

    Shared by manual runs, webhooks and the scheduler; returns the new
    execution id. A worker claims the job, flips it to ``running`` and
    executes the exact workflow snapshot (spec 24.3). ``extra_payload``
    carries debugger directives (e.g. ``_retry_from_node``, Phase 13).

    Validation (spec 12.7): credential references are verified BEFORE
    queueing — workflows with unimplemented or invalid providers never
    enter the queue.
    """
    # Validate credential references before queue — fail fast with clear error
    try:
        validate_workflow_credentials(workflow_data, db, user_id)
    except WorkflowValidationError as ve:
        # Create a failed execution record for audit, then raise for API to return 422
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        db.add(Execution(
            id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            workflow_version=version,
            workflow_data=workflow_data,
            trigger=trigger,
            trigger_data=trigger_items,
            status="failed",
            error=ve.to_dict(),
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        ))
        db.commit()
        raise ve
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    db.add(Execution(
        id=execution_id,
        workflow_id=workflow_id,
        user_id=user_id,
        workflow_version=version,
        workflow_data=workflow_data,
        trigger=trigger,
        trigger_data=trigger_items,
        status="queued",
        # Explicit microsecond timestamp: server_default (CURRENT_TIMESTAMP)
        # has second resolution, so executions created within the same
        # second would tie in history ordering (SQLite).
        started_at=datetime.now(UTC),
    ))
    db.commit()
    payload = {
        "workflow_data": workflow_data,
        "trigger_items": trigger_items,
        "trigger": trigger,
        "user_id": user_id,
        "workflow_id": workflow_id,
        "version": version,
        "workspace_id": workspace_id,
        **(extra_payload or {}),
    }
    if not get_queue().enqueue(job_id, execution_id, payload):
        # Duplicate delivery guard: another execution for this id already
        # queued (should not happen with fresh ids; keep the row accurate).
        rec = db.get(Execution, execution_id)
        if rec is not None:
            rec.status = "failed"
            rec.error = {"code": "DUPLICATE_QUEUE", "message": "Execution was already queued."}
            db.commit()
    execution_started(execution_id, trigger)
    ensure_embedded_consumer()
    return execution_id


def has_running_execution(db: Session, workflow_id: str) -> bool:
    """Spec 8.4/13: never run two executions of the same workflow at once
    for webhook/schedule triggers (skip if one is queued or running)."""
    return db.scalar(
        select(Execution.id).where(
            Execution.workflow_id == workflow_id,
            Execution.status.in_(("queued", "running", "cancelling")),
        )
    ) is not None


def workflow_workspace(db: Session, workflow_id: str) -> str | None:
    """Best-effort workspace lookup for env resolution (Phase 31).

    Executions carry their own snapshot and outlive workflow deletion;
    a missing row just means no workspace-scoped env vars.
    """
    from app.models.workflow import WorkflowRecord

    rec = db.get(WorkflowRecord, workflow_id)
    return rec.workspace_id if rec is not None else None


@router.post("/api/workflows/{workflow_id}/run", tags=["workflows"], status_code=status.HTTP_202_ACCEPTED)
async def run_workflow(
    workflow_id: str,
    body: RunRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    # Plan quota (Phase 34): monthly execution budget per workspace plan.
    from app.billing.service import enforce_plan_limit

    enforce_plan_limit(db, rec.workspace_id, "executions")
    raw = body.data if body is not None else None
    trigger_items: list[dict[str, Any]]
    if isinstance(raw, dict):
        trigger_items = [raw]
    else:
        trigger_items = raw if raw is not None else [{}]
    try:
        execution_id = start_execution(
            db,
            workflow_id=workflow_id,
            user_id=user.id,
            version=rec.version,
            workflow_data=rec.data,
            trigger="manual",
            trigger_items=trigger_items,
            workspace_id=rec.workspace_id,
        )
    except WorkflowValidationError as ve:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ve.to_dict())
    log_event(db, EXECUTION_RUN, target_type="workflow", target_id=workflow_id, user_id=user.id,
              detail={"execution_id": execution_id})
    return ok({"execution_id": execution_id})


def _can_view_execution(db: Session, rec: Execution, user: User) -> bool:
    """Owners and anyone who can view the workflow see its executions.

    After a workflow is (soft-)deleted, the owner may still inspect past
    executions: the rows carry their own snapshot and must remain
    auditable. Non-owners lose access with the workflow.
    """
    permission = get_permission(db, rec.workflow_id, user)
    if permission is not None:
        return True
    return rec.user_id == user.id


def _can_edit_execution(db: Session, rec: Execution, user: User) -> bool:
    permission = get_permission(db, rec.workflow_id, user)
    return permission in ("owner", "edit")


@router.get("/api/executions")
def list_executions(
    workflow_id: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    page, size = page_params(page=page, pageSize=pageSize)
    ids = accessible_ids(db, user)
    if not ids:
        return ok([], {"page": page, "pageSize": size, "total": 0})
    stmt = select(Execution).where(Execution.workflow_id.in_(ids))
    count_stmt = select(func.count()).select_from(Execution).where(Execution.workflow_id.in_(ids))
    if workflow_id:
        stmt = stmt.where(Execution.workflow_id == workflow_id)
        count_stmt = count_stmt.where(Execution.workflow_id == workflow_id)
    if status:
        stmt = stmt.where(Execution.status == status)
        count_stmt = count_stmt.where(Execution.status == status)
    total = db.scalar(count_stmt) or 0
    recs = db.scalars(
        stmt.order_by(Execution.started_at.desc(), Execution.id.desc())
        .offset((page - 1) * size).limit(size)
    ).all()
    names = {
        wid: name
        for wid, name in db.execute(
            select(WorkflowRecord.id, WorkflowRecord.name).where(
                WorkflowRecord.id.in_({r.workflow_id for r in recs})
            )
        ).all() if recs
    }
    items = [_to_dict(r) for r in recs]
    for item in items:
        item["workflow_name"] = names.get(item["workflow_id"], item["workflow_id"][:8])
    return ok(items, {"page": page, "pageSize": size, "total": total})


@router.get("/api/executions/{execution_id}")
def get_execution(execution_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    results_outputs = (rec.results or {}).get("outputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if results_outputs and isinstance(results_outputs, dict):
        for step in trace:
            nid = step.get("node_id")
            if nid in results_outputs and results_outputs[nid]:
                step["outputs"] = results_outputs[nid]

    data = {
        **_to_dict(rec),
        "results": rec.results,
        "node_statuses": rec.node_statuses,
        "trace": trace,
        "workflow_data": rec.workflow_data,
    }
    return ok(data)


@router.get("/api/executions/{execution_id}/items")
def get_execution_items(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    """Paginated per-node snapshots (spec 9; polled by the canvas in M5)."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    outputs: dict = (rec.results or {}).get("outputs", {})
    statuses: dict = rec.node_statuses or {}
    snapshots = [
        {"node_id": nid, "status": statuses.get(nid, "success"), "outputs": outputs.get(nid, {})}
        for nid in outputs
    ]
    total = len(snapshots)
    page, size = page_params(page=page, pageSize=pageSize)
    start = (page - 1) * size
    return ok(
        snapshots[start : start + size],
        {"page": page, "pageSize": size, "total": total},
    )


@router.get("/api/executions/{execution_id}/trace")
def get_execution_trace(
    execution_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Step-by-step run log for the debugger (M8 + Phase 13): each step
    records the node's inputs, outputs, error, status, duration and the
    structured attempt/retry counts. Sensitive-looking keys are masked."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    results_outputs = (rec.results or {}).get("outputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if results_outputs and isinstance(results_outputs, dict):
        for step in trace:
            nid = step.get("node_id")
            if nid in results_outputs and results_outputs[nid]:
                step["outputs"] = results_outputs[nid]
    return ok({"steps": trace})


@router.post("/api/executions/{execution_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_execution(
    execution_id: str,
    body: RetryRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run the exact snapshotted workflow version (spec 24.3, 9).

    With ``node_id`` (Phase 13): safe node retry — a NEW execution that
    seeds the persisted outputs of every upstream node so only the failed
    node and its descendants re-execute. The target must have actually
    failed; upstream side effects are never re-run.
    """
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    node_id = (body.node_id if body is not None else None) or None
    extra_payload: dict[str, Any] | None = None
    if node_id:
        workflow_nodes = {n.get("id") for n in (rec.workflow_data or {}).get("nodes", [])}
        if node_id not in workflow_nodes:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node '{node_id}'.")
        statuses = rec.node_statuses or {}
        node_status = statuses.get(node_id)
        if rec.status in IN_PROGRESS_STATUSES or rec.status == "waiting_approval":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cannot retry a node while the execution is still running.",
            )
        if node_status not in ("error", "failed"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Node '{node_id}' did not fail (status: {node_status or 'unknown'}); "
                "only failed nodes can be retried safely.",
            )
        extra_payload = {"_retry_from_node": node_id, "_retry_source": execution_id}

    trigger_items = rec.trigger_data or [{}]
    new_id = start_execution(
        db,
        workflow_id=rec.workflow_id,
        user_id=user.id,
        version=rec.workflow_version,
        workflow_data=rec.workflow_data,
        trigger="node_retry" if node_id else "retry",
        trigger_items=trigger_items,
        workspace_id=workflow_workspace(db, rec.workflow_id),
        extra_payload=extra_payload,
    )
    log_event(db, EXECUTION_RETRY, target_type="execution", target_id=execution_id, user_id=user.id,
              detail={"new_execution_id": new_id, **({"node_id": node_id} if node_id else {})})
    return ok({"execution_id": new_id})


@router.post("/api/executions/{execution_id}/cancel")
def cancel_execution(execution_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    if rec.status not in IN_PROGRESS_STATUSES | {"waiting_approval"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Execution is not running.")
    # Durable cooperative cancel (spec 36): mark it in the DB; the
    # worker's monitor flips the engine's cancel event. A waiting
    # execution has no active run — the flag itself is terminal.
    was_waiting = rec.status == "waiting_approval"
    rec.status = "cancelling" if not was_waiting else "cancelled"
    if was_waiting:
        rec.finished_at = datetime.now(UTC)
        rec.pause_state = None
        if rec.error is None:
            rec.error = {"code": "CANCELLED_WHILE_WAITING", "message": "Cancelled while waiting for approval."}
    db.commit()
    log_event(db, EXECUTION_CANCEL, target_type="execution", target_id=execution_id, user_id=user.id)
    return ok({"id": execution_id, "status": rec.status})


@router.post("/api/executions/{execution_id}/resume")
def resume_execution(
    execution_id: str,
    body: ResumeRequest | None = None,
    approved: bool | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resume a paused execution with an approve/reject decision.

    Accepts the decision as a JSON body (`{"approved": false}`) or, for
    backward compatibility, as the `approved` query parameter. The
    requester must be able to edit the workflow; when the approval node
    restricts ``approvers``, the requester must be listed. Replaying
    persisted node outputs means upstream nodes never re-run (Phase 32).
    """
    approved = bool(approved) if approved is not None else (bool(body.approved) if body is not None else True)
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    if rec.status != "waiting_approval":
        raise HTTPException(status.HTTP_409_CONFLICT, "Execution is not waiting for approval.")

    approved = bool(body.approved) if body is not None else True
    pause = rec.pause_state or {}
    allowed = pause.get("approvers") or []
    if allowed and user.id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a listed approver for this step.")

    # Re-queue for the worker to pick up. The jobs table is unique per
    # execution, so this resets the original job row (durable resume).
    queue = get_queue()
    payload = {
        "workflow_data": rec.workflow_data,
        "trigger_items": rec.trigger_data or [{}],
        "trigger": rec.trigger,
        "user_id": rec.user_id,
        "workflow_id": rec.workflow_id,
        "version": rec.workflow_version,
        "workspace_id": workflow_workspace(db, rec.workflow_id),
        "_approval_data": {
            "approved": approved,
            "approved_by": user.id,
            "approved_at": datetime.now(UTC).isoformat(),
            "node_id": pause.get("node_id"),
        },
    }
    if not queue.requeue(execution_id, payload):
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        if not queue.enqueue(job_id, execution_id, payload):
            raise HTTPException(status.HTTP_409_CONFLICT, "Execution is already queued.")
    rec.status = "queued"
    db.commit()
    log_event(db, EXECUTION_RESUME, target_type="execution", target_id=execution_id, user_id=user.id,
              detail={"approved": approved})
    return ok({"id": execution_id, "status": "queued"})


class RunNodeRequest(BaseModel):
    """Execute a single node with seeded upstream data (standalone, no prior execution needed)."""
    node_id: str


class RunToNodeRequest(BaseModel):
    """Execute all nodes up to (and including) a specific node."""
    node_id: str


@router.post("/api/workflows/{workflow_id}/run-node", status_code=status.HTTP_202_ACCEPTED)
async def run_single_node(
    workflow_id: str,
    body: RunNodeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Execute a single node in isolation.

    Seeds dummy upstream data so the target node runs with whatever
    expression inputs it references.  Useful for step-by-step debugging.
    """
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    from app.billing.service import enforce_plan_limit

    enforce_plan_limit(db, rec.workspace_id, "executions")
    workflow_nodes = {n.get("id") for n in (rec.data or {}).get("nodes", [])}
    if body.node_id not in workflow_nodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node '{body.node_id}'.")
    try:
        execution_id = start_execution(
            db,
            workflow_id=workflow_id,
            user_id=user.id,
            version=rec.version,
            workflow_data=rec.data,
            trigger="manual",
            trigger_items=[{}],
            workspace_id=rec.workspace_id,
            extra_payload={"_run_node": body.node_id},
        )
    except WorkflowValidationError as ve:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ve.to_dict())
    log_event(db, EXECUTION_RUN, target_type="workflow", target_id=workflow_id, user_id=user.id,
              detail={"execution_id": execution_id, "run_node": body.node_id})
    return ok({"execution_id": execution_id})


@router.post("/api/workflows/{workflow_id}/run-to-node", status_code=status.HTTP_202_ACCEPTED)
async def run_to_node(
    workflow_id: str,
    body: RunToNodeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Execute all nodes up to and including the specified node.

    Downstream nodes are seeded as skipped so the engine only runs the
    chain leading to (and including) the target.
    """
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    from app.billing.service import enforce_plan_limit

    enforce_plan_limit(db, rec.workspace_id, "executions")
    workflow_nodes = {n.get("id") for n in (rec.data or {}).get("nodes", [])}
    if body.node_id not in workflow_nodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node '{body.node_id}'.")
    try:
        execution_id = start_execution(
            db,
            workflow_id=workflow_id,
            user_id=user.id,
            version=rec.version,
            workflow_data=rec.data,
            trigger="manual",
            trigger_items=[{}],
            workspace_id=rec.workspace_id,
            extra_payload={"_run_to_node": body.node_id},
        )
    except WorkflowValidationError as ve:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ve.to_dict())
    log_event(db, EXECUTION_RUN, target_type="workflow", target_id=workflow_id, user_id=user.id,
              detail={"execution_id": execution_id, "run_to_node": body.node_id})
    return ok({"execution_id": execution_id})