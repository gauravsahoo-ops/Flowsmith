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
from sqlalchemy.orm import Session, defer

from app.api.access import accessible_ids, get_permission, get_workflow
from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.audit import (
    EXECUTION_CANCEL,
    EXECUTION_EXPORT,
    EXECUTION_RESUME,
    EXECUTION_RETRY,
    EXECUTION_RUN,
    log_event,
)
from app.credentials.validator import validate_workflow_credentials
from app.db import get_db
from app.engine.errors import WorkflowValidationError
from app.engine.redact import (
    redact_results,
    redact_sensitive,
    redact_trace_steps,
    sanitize_csv_cell,
)
from app.metrics import execution_started
from app.models import Execution, User
from app.models.monitoring_telemetry import (
    ApiRequestTelemetry,
    ExecutionRetryHistory,
    ExecutionStep,
)
from app.models.workflow import WorkflowRecord
from app.queue import get_queue
from app.queue.worker import ensure_embedded_consumer

router = APIRouter(tags=["executions"])
logger = logging.getLogger("api.executions")

IN_PROGRESS_STATUSES = frozenset({"queued", "running", "cancelling"})


class RunRequest(BaseModel):
    data: dict[str, Any] | list[dict[str, Any]] | None = None


class RetryRequest(BaseModel):
    """Retry the whole execution (default) or safely re-run from one failed node."""

    node_id: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None


class ResumeRequest(BaseModel):
    """Approve/reject decision for a paused execution (Phase 32)."""

    approved: bool = True


def _to_dict(rec: Execution) -> dict[str, Any]:
    duration_ms = rec.duration_ms
    if duration_ms is None and rec.started_at:
        end = rec.finished_at or datetime.now(UTC)
        duration_ms = round((end - rec.started_at).total_seconds() * 1000.0, 2)

    return {
        "id": rec.id,
        "workflow_id": rec.workflow_id,
        "workflow_version": rec.workflow_version,
        "trigger": rec.trigger,
        "status": rec.status,
        "error": rec.error,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
        "pause_state": rec.pause_state,
        "duration_ms": duration_ms,
        "source_connector": rec.source_connector or rec.trigger or "flowsmith_trigger",
        "destination_connector": rec.destination_connector or "flowsmith_output",
        "source_object": rec.source_object,
        "destination_object": rec.destination_object,
        "http_method": rec.http_method,
        "api_endpoint": rec.api_endpoint,
        "http_status_code": rec.http_status_code,
        "records_read": rec.records_read or 0,
        "records_created": rec.records_created or 0,
        "records_updated": rec.records_updated or 0,
        "records_skipped": rec.records_skipped or 0,
        "records_failed": rec.records_failed or 0,
        "records_processed": rec.records_processed or (rec.records_created or 0) + (rec.records_updated or 0),
        "retry_count": rec.retry_count or 0,
        "error_type": rec.error_type,
        "error_code": rec.error_code,
        "error_summary": rec.error_summary or (rec.error.get("message") if isinstance(rec.error, dict) else str(rec.error) if rec.error else None),
        "correlation_id": rec.correlation_id,
        "parent_execution_id": rec.parent_execution_id,
        "organization_id": rec.organization_id,
        "workspace_id": rec.workspace_id,
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
    parent_execution_id: str | None = None,
    retry_count: int = 0,
    correlation_id: str | None = None,
    organization_id: int | None = None,
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
            workspace_id=workspace_id,
            parent_execution_id=parent_execution_id,
            retry_count=retry_count,
            correlation_id=correlation_id,
            organization_id=organization_id,
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
        started_at=datetime.now(UTC),
        workspace_id=workspace_id,
        parent_execution_id=parent_execution_id,
        retry_count=retry_count,
        correlation_id=correlation_id,
        organization_id=organization_id,
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
    from app.telemetry.tracer import inject_trace_context
    inject_trace_context(payload)
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
    from app.billing.service import enforce_can_start_execution

    enforce_can_start_execution(db, rec.workspace_id)
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


SORT_COLUMNS = {
    "started_at": Execution.started_at,
    "duration_ms": Execution.duration_ms,
    "records_processed": Execution.records_processed,
    "status": Execution.status,
    "id": Execution.id,
}


def _build_execution_query(
    db: Session,
    ids: list[str],
    *,
    workflow_id: str | None = None,
    status: str | None = None,
    connector: str | None = None,
    source_object: str | None = None,
    destination_object: str | None = None,
    http_status: int | None = None,
    error_type: str | None = None,
    trigger: str | None = None,
    search: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    stmt = (
        select(Execution)
        .options(
            defer(Execution.trace),
            defer(Execution.results),
            defer(Execution.workflow_data),
            defer(Execution.node_statuses),
        )
        .where(Execution.workflow_id.in_(ids))
    )
    if workflow_id:
        stmt = stmt.where(Execution.workflow_id == workflow_id)
    if status:
        st_lower = status.lower()
        if st_lower == "failed":
            stmt = stmt.where(Execution.status.in_(("failed", "error", "timeout")))
        elif st_lower == "running":
            stmt = stmt.where(Execution.status.in_(("running", "queued", "waiting_approval", "waiting_auth")))
        elif st_lower == "cancelled":
            stmt = stmt.where(Execution.status.in_(("cancelled", "cancelling")))
        elif st_lower == "partial_success":
            stmt = stmt.where(Execution.status == "partial_success")
        elif st_lower == "retrying":
            stmt = stmt.where(Execution.status == "retrying")
        elif st_lower == "success":
            stmt = stmt.where(Execution.status == "success")
        else:
            stmt = stmt.where(Execution.status == status)
    if connector:
        term = f"%{connector.strip()}%"
        stmt = stmt.where(
            (Execution.source_connector.ilike(term)) | (Execution.destination_connector.ilike(term))
        )
    if source_object:
        stmt = stmt.where(Execution.source_object.ilike(f"%{source_object.strip()}%"))
    if destination_object:
        stmt = stmt.where(Execution.destination_object.ilike(f"%{destination_object.strip()}%"))
    if http_status is not None:
        stmt = stmt.where(Execution.http_status_code == http_status)
    if error_type:
        stmt = stmt.where(Execution.error_type == error_type)
    if trigger:
        stmt = stmt.where(Execution.trigger == trigger)
    if start_date:
        try:
            dt_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            stmt = stmt.where(Execution.started_at >= dt_start)
        except Exception:
            pass
    if end_date:
        try:
            dt_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            stmt = stmt.where(Execution.started_at <= dt_end)
        except Exception:
            pass
    if search:
        sterm = f"%{search.strip()}%"
        matching_wf_ids = [
            wid for (wid,) in db.execute(
                select(WorkflowRecord.id).where(WorkflowRecord.name.ilike(sterm))
            ).all()
        ]
        from sqlalchemy import or_
        predicates = [
            Execution.id.ilike(sterm),
            Execution.error_summary.ilike(sterm),
            Execution.api_endpoint.ilike(sterm),
            Execution.correlation_id.ilike(sterm),
        ]
        if matching_wf_ids:
            predicates.append(Execution.workflow_id.in_(matching_wf_ids))
        stmt = stmt.where(or_(*predicates))

    return stmt


@router.get("/api/executions")
def list_executions(
    workflow_id: str | None = None,
    status: str | None = None,
    connector: str | None = None,
    source_object: str | None = None,
    destination_object: str | None = None,
    http_status: int | None = None,
    error_type: str | None = None,
    trigger: str | None = None,
    search: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sort_by: str = "started_at",
    sort_dir: str = "desc",
    page: int = 1,
    pageSize: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    page, size = page_params(page=page, pageSize=pageSize)
    ids = accessible_ids(db, user)
    if not ids:
        return ok([], {"page": page, "pageSize": size, "total": 0})

    stmt = _build_execution_query(
        db,
        ids,
        workflow_id=workflow_id,
        status=status,
        connector=connector,
        source_object=source_object,
        destination_object=destination_object,
        http_status=http_status,
        error_type=error_type,
        trigger=trigger,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    col = SORT_COLUMNS.get(sort_by, Execution.started_at)
    order_clause = col.asc() if sort_dir.lower() == "asc" else col.desc()
    stmt = stmt.order_by(order_clause, Execution.id.desc()).offset((page - 1) * size).limit(size)

    recs = db.scalars(stmt).all()
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


@router.get("/api/executions/export")
def export_executions_csv(
    workflow_id: str | None = None,
    status: str | None = None,
    connector: str | None = None,
    source_object: str | None = None,
    destination_object: str | None = None,
    http_status: int | None = None,
    error_type: str | None = None,
    trigger: str | None = None,
    search: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Export filtered execution logs as a secure, tenant-scoped CSV with formula protection."""
    from fastapi.responses import Response
    import csv
    import io

    ids = accessible_ids(db, user)
    if not ids:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["execution_id", "timestamp", "workflow_name", "status", "duration_ms", "source_connector", "destination_connector", "http_method", "http_status_code", "records_read", "records_processed", "records_failed", "retry_count", "error_summary"])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="flowsmith-executions-export.csv"'},
        )

    stmt = _build_execution_query(
        db,
        ids,
        workflow_id=workflow_id,
        status=status,
        connector=connector,
        source_object=source_object,
        destination_object=destination_object,
        http_status=http_status,
        error_type=error_type,
        trigger=trigger,
        search=search,
        start_date=start_date,
        end_date=end_date,
    ).order_by(Execution.started_at.desc(), Execution.id.desc()).limit(10000)

    recs = db.scalars(stmt).all()
    names = {
        wid: name
        for wid, name in db.execute(
            select(WorkflowRecord.id, WorkflowRecord.name).where(
                WorkflowRecord.id.in_({r.workflow_id for r in recs})
            )
        ).all() if recs
    }

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "execution_id",
        "timestamp",
        "workflow_name",
        "status",
        "duration_ms",
        "source_connector",
        "destination_connector",
        "http_method",
        "http_status_code",
        "records_read",
        "records_processed",
        "records_failed",
        "retry_count",
        "error_type",
        "error_summary",
    ])

    for r in recs:
        d = _to_dict(r)
        wf_name = names.get(r.workflow_id, r.workflow_id)
        writer.writerow([
            sanitize_csv_cell(d["id"]),
            sanitize_csv_cell(d["started_at"].isoformat() if d["started_at"] else ""),
            sanitize_csv_cell(wf_name),
            sanitize_csv_cell(d["status"]),
            sanitize_csv_cell(d["duration_ms"]),
            sanitize_csv_cell(d["source_connector"]),
            sanitize_csv_cell(d["destination_connector"]),
            sanitize_csv_cell(d["http_method"] or ""),
            sanitize_csv_cell(d["http_status_code"] or ""),
            sanitize_csv_cell(d["records_read"]),
            sanitize_csv_cell(d["records_processed"]),
            sanitize_csv_cell(d["records_failed"]),
            sanitize_csv_cell(d["retry_count"]),
            sanitize_csv_cell(d["error_type"] or ""),
            sanitize_csv_cell(d["error_summary"] or ""),
        ])

    log_event(
        db,
        EXECUTION_EXPORT,
        target_type="executions",
        target_id="filtered",
        user_id=user.id,
        detail={"count": len(recs), "filters": {"workflow_id": workflow_id, "status": status, "connector": connector}},
    )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="flowsmith-executions-export.csv"'},
    )



@router.get("/api/executions/{execution_id}")
def get_execution(execution_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    results_outputs = (rec.results or {}).get("outputs") if isinstance(rec.results, dict) else {}
    results_inputs = (rec.results or {}).get("inputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if (results_outputs and isinstance(results_outputs, dict)) or (results_inputs and isinstance(results_inputs, dict)):
        for step in trace:
            nid = step.get("node_id")
            if results_outputs and isinstance(results_outputs, dict) and nid in results_outputs and results_outputs[nid]:
                step["full_outputs"] = results_outputs[nid]
                if not step.get("outputs"):
                    step["outputs"] = results_outputs[nid]
            if results_inputs and isinstance(results_inputs, dict) and nid in results_inputs and results_inputs[nid]:
                step["full_inputs"] = results_inputs[nid]
                if not step.get("inputs"):
                    step["inputs"] = results_inputs[nid]
    trace = redact_trace_steps(trace)

    data = {
        **_to_dict(rec),
        "results": redact_results(rec.results),
        "node_statuses": rec.node_statuses,
        "trace": trace,
        "workflow_data": redact_sensitive(rec.workflow_data),
    }
    return ok(data)


@router.get("/api/executions/{execution_id}/export")
def export_execution(
    execution_id: str,
    format: str = "json",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Export execution trace and results as downloadable JSON or CSV audit file."""
    from fastapi.responses import Response

    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    results_outputs = (rec.results or {}).get("outputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if results_outputs and isinstance(results_outputs, dict):
        for step in trace:
            nid = step.get("node_id")
            if nid in results_outputs and results_outputs[nid] and not step.get("outputs"):
                step["outputs"] = results_outputs[nid]
    trace = redact_trace_steps(trace)

    data = {
        **_to_dict(rec),
        "results": redact_results(rec.results),
        "node_statuses": rec.node_statuses,
        "trace": trace,
        "workflow_data": redact_sensitive(rec.workflow_data),
    }

    if format.lower() == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "step_index", "node_id", "node_type", "status",
            "duration_ms", "started_at", "attempts", "retries",
            "error_code", "error_message", "note",
        ])
        for idx, step in enumerate(trace, 1):
            err = step.get("error") or {}
            writer.writerow([
                idx,
                step.get("node_id", ""),
                step.get("node_type", ""),
                step.get("status", ""),
                step.get("duration_ms", 0),
                step.get("started_at", ""),
                step.get("attempts", 1),
                step.get("retries", 0),
                err.get("code", "") if isinstance(err, dict) else "",
                err.get("message", str(err)) if isinstance(err, dict) else str(err),
                step.get("note", ""),
            ])
        csv_content = output.getvalue()
        filename = f"execution-{execution_id[:8]}-trace.csv"
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    import json
    json_content = json.dumps(data, indent=2, default=str)
    filename = f"execution-{execution_id[:8]}-audit.json"
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        {"node_id": nid, "status": statuses.get(nid, "success"), "outputs": redact_sensitive(outputs.get(nid, {}))}
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
    results_inputs = (rec.results or {}).get("inputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if (results_outputs and isinstance(results_outputs, dict)) or (results_inputs and isinstance(results_inputs, dict)):
        for step in trace:
            nid = step.get("node_id")
            if results_outputs and isinstance(results_outputs, dict) and nid in results_outputs and results_outputs[nid]:
                step["full_outputs"] = results_outputs[nid]
                if not step.get("outputs"):
                    step["outputs"] = results_outputs[nid]
            if results_inputs and isinstance(results_inputs, dict) and nid in results_inputs and results_inputs[nid]:
                step["full_inputs"] = results_inputs[nid]
                if not step.get("inputs"):
                    step["inputs"] = results_inputs[nid]
    return ok({"steps": redact_trace_steps(trace)})


@router.get("/api/executions/{execution_id}/flamegraph")
def get_execution_flamegraph_endpoint(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return hierarchical waterfall/flamegraph data structure for the execution (Roadmap Initiative C)."""
    from app.telemetry.flamegraph import generate_execution_flamegraph

    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    trace = [dict(s) for s in (rec.trace or [])]
    flamegraph_data = generate_execution_flamegraph(trace)
    return ok(flamegraph_data)


@router.get("/api/executions/{execution_id}/steps")
def get_execution_steps(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return structured DAG step telemetry for an execution."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    step_rows = db.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.sequence_number.asc())
    ).all()

    if step_rows:
        data = [
            {
                "id": s.id,
                "node_id": s.node_id,
                "node_type": s.node_type,
                "step_name": s.step_name,
                "sequence_number": s.sequence_number,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "duration_ms": s.duration_ms,
                "input_record_count": s.input_record_count,
                "output_record_count": s.output_record_count,
                "created_record_count": s.created_record_count,
                "updated_record_count": s.updated_record_count,
                "skipped_record_count": s.skipped_record_count,
                "failed_record_count": s.failed_record_count,
                "error_type": s.error_type,
                "error_code": s.error_code,
                "error_message": s.error_message,
                "retry_count": s.retry_count,
                "metadata": getattr(s, "step_metadata", None),
            }
            for s in step_rows
        ]
        return ok(data)

    # Fallback to rec.trace for runs executed prior to telemetry table migration
    trace = redact_trace_steps([dict(s) for s in (rec.trace or [])])
    return ok(trace)


@router.get("/api/executions/{execution_id}/timeline")
def get_execution_timeline(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return chronological DAG timeline events for execution inspection."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    events: list[dict[str, Any]] = []

    # 1. Trigger / Enqueued event
    if rec.started_at:
        events.append({
            "type": "trigger",
            "title": f"Workflow triggered via {rec.trigger or 'manual'}",
            "status": "success",
            "timestamp": rec.started_at.isoformat(),
            "duration_ms": 0,
            "details": {
                "trigger": rec.trigger,
                "source_connector": rec.source_connector or rec.trigger,
            },
        })

    # 2. Step traces & API calls
    steps = db.scalars(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.sequence_number.asc())
    ).all()

    api_calls = db.scalars(
        select(ApiRequestTelemetry)
        .options(
            defer(ApiRequestTelemetry.request_payload),
            defer(ApiRequestTelemetry.response_payload),
        )
        .where(ApiRequestTelemetry.execution_id == execution_id)
        .order_by(ApiRequestTelemetry.created_at.asc())
    ).all()
    api_by_step: dict[str, list[ApiRequestTelemetry]] = {}
    for a in api_calls:
        if a.step_id:
            api_by_step.setdefault(a.step_id, []).append(a)

    if steps:
        for s in steps:
            step_events: list[dict[str, Any]] = []
            for a in api_by_step.get(s.id, []):
                step_events.append({
                    "type": "api_call",
                    "title": f"{a.http_method} {a.endpoint_url}",
                    "status": "success" if a.http_status_code and a.http_status_code < 400 else "failed",
                    "status_code": a.http_status_code,
                    "duration_ms": a.duration_ms,
                    "request_id": a.id,
                })

            events.append({
                "type": "step",
                "step_id": s.id,
                "node_id": s.node_id,
                "title": s.step_name or s.node_id,
                "node_type": s.node_type,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "duration_ms": s.duration_ms,
                "record_counts": {
                    "in": s.input_record_count,
                    "out": s.output_record_count,
                    "created": s.created_record_count,
                    "updated": s.updated_record_count,
                    "skipped": s.skipped_record_count,
                    "failed": s.failed_record_count,
                },
                "error": {
                    "type": s.error_type,
                    "code": s.error_code,
                    "message": s.error_message,
                } if s.error_code else None,
                "api_calls": step_events,
            })
    else:
        # Fallback from trace
        trace = rec.trace or []
        for s in trace:
            events.append({
                "type": "step",
                "step_id": s.get("node_id"),
                "node_id": s.get("node_id"),
                "title": s.get("node_id"),
                "node_type": s.get("node_type", "node"),
                "status": "failed" if s.get("status") in ("error", "failed") else "success",
                "duration_ms": s.get("duration_ms", 0),
                "error": s.get("error"),
                "api_calls": [],
            })

    # 3. Terminal event
    events.append({
        "type": "terminal",
        "title": f"Execution {rec.status}",
        "status": rec.status,
        "timestamp": rec.finished_at.isoformat() if rec.finished_at else (rec.started_at.isoformat() if rec.started_at else None),
        "duration_ms": rec.duration_ms,
        "details": {
            "records_processed": rec.records_processed,
            "error_summary": rec.error_summary,
        },
    })

    return ok({"events": events, "status": rec.status, "duration_ms": rec.duration_ms})


@router.get("/api/executions/{execution_id}/requests")
def list_execution_requests(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return lightweight list of outbound API calls for API inspector."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    rows = db.scalars(
        select(ApiRequestTelemetry)
        .options(
            defer(ApiRequestTelemetry.request_payload),
            defer(ApiRequestTelemetry.response_payload),
        )
        .where(ApiRequestTelemetry.execution_id == execution_id)
        .order_by(ApiRequestTelemetry.created_at.asc())
    ).all()

    items = [
        {
            "id": r.id,
            "execution_id": r.execution_id,
            "step_id": r.step_id,
            "node_id": r.node_id,
            "connector_name": r.connector_name,
            "operation": r.operation,
            "http_method": r.http_method,
            "endpoint_url": r.endpoint_url,
            "http_status_code": r.http_status_code,
            "duration_ms": r.duration_ms,
            "error_message": r.error_message,
            "is_truncated": r.is_truncated,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return ok(items)


@router.get("/api/executions/{execution_id}/requests/{request_id}")
def get_execution_request_detail(
    execution_id: str,
    request_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Lazy-load full payload and headers for one specific API call."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    req = db.scalar(
        select(ApiRequestTelemetry).where(
            ApiRequestTelemetry.execution_id == execution_id,
            ApiRequestTelemetry.id == request_id,
        )
    )
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API request telemetry record not found.")

    return ok({
        "id": req.id,
        "execution_id": req.execution_id,
        "step_id": req.step_id,
        "node_id": req.node_id,
        "connector_name": req.connector_name,
        "operation": req.operation,
        "http_method": req.http_method,
        "endpoint_url": req.endpoint_url,
        "query_params": req.query_params,
        "request_headers": req.request_headers,
        "request_payload": req.request_payload,
        "http_status_code": req.http_status_code,
        "response_headers": req.response_headers,
        "response_payload": req.response_payload,
        "duration_ms": req.duration_ms,
        "error_message": req.error_message,
        "is_truncated": req.is_truncated,
        "correlation_id": req.correlation_id,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    })


@router.get("/api/executions/{execution_id}/retries")
def get_execution_retries(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return historical retry attempts linked to this execution."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    rows = db.scalars(
        select(ExecutionRetryHistory).where(
            (ExecutionRetryHistory.original_execution_id == execution_id)
            | (ExecutionRetryHistory.retry_execution_id == execution_id)
        ).order_by(ExecutionRetryHistory.attempt_number.asc())
    ).all()

    items = [
        {
            "id": r.id,
            "execution_id": r.retry_execution_id,
            "original_execution_id": r.original_execution_id,
            "retry_execution_id": r.retry_execution_id,
            "attempt_number": r.attempt_number,
            "retry_reason": r.retry_reason,
            "failed_step_id": r.failed_step_id,
            "retry_trigger": r.retry_trigger,
            "triggered_by": r.initiated_by_user_id or r.retry_trigger,
            "initiated_by_user_id": r.initiated_by_user_id,
            "retry_policy": r.retry_policy,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return ok(items)


@router.post("/api/executions/{execution_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_execution(
    execution_id: str,
    body: RetryRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Re-run snapshotted workflow version with retry tracking and idempotency."""
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    # Idempotency check: prevent duplicate submissions
    if body and body.idempotency_key:
        recent_retry = db.scalar(
            select(ExecutionRetryHistory)
            .where(
                ExecutionRetryHistory.original_execution_id == execution_id,
                ExecutionRetryHistory.retry_policy == body.idempotency_key,
            )
        )
        if recent_retry:
            return ok({"execution_id": recent_retry.retry_execution_id, "idempotent_replay": True})

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
    from app.billing.service import enforce_can_start_execution

    workspace_id = workflow_workspace(db, rec.workflow_id)
    enforce_can_start_execution(db, workspace_id)

    next_attempt = (rec.retry_count or 0) + 1
    new_id = start_execution(
        db,
        workflow_id=rec.workflow_id,
        user_id=user.id,
        version=rec.workflow_version,
        workflow_data=rec.workflow_data,
        trigger="node_retry" if node_id else "retry",
        trigger_items=trigger_items,
        workspace_id=workspace_id,
        extra_payload=extra_payload,
        parent_execution_id=execution_id,
        retry_count=next_attempt,
        correlation_id=rec.correlation_id or execution_id,
        organization_id=rec.organization_id,
    )

    retry_row = ExecutionRetryHistory(
        id=f"retry_{uuid.uuid4().hex[:12]}",
        original_execution_id=execution_id,
        retry_execution_id=new_id,
        attempt_number=next_attempt,
        retry_reason=body.reason if body and body.reason else ("node_retry" if node_id else "manual_retry"),
        failed_step_id=node_id,
        retry_trigger="manual",
        initiated_by_user_id=user.id,
        retry_policy=body.idempotency_key if body else None,
        status="pending",
        created_at=datetime.now(UTC),
    )
    db.add(retry_row)
    db.commit()

    log_event(
        db,
        EXECUTION_RETRY,
        target_type="execution",
        target_id=execution_id,
        user_id=user.id,
        detail={
            "new_execution_id": new_id,
            "attempt_number": next_attempt,
            **({"node_id": node_id} if node_id else {}),
        },
    )
    return ok({"execution_id": new_id, "attempt_number": next_attempt})



@router.post("/api/executions/{execution_id}/cancel")
def cancel_execution(execution_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    if rec.status not in IN_PROGRESS_STATUSES | {"waiting_approval", "waiting_auth"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Execution is not running.")

    from app.eventbus import bus
    from app.execution_runtime import signal_cancel

    # 1. Waiting approval/auth: terminal immediately
    if rec.status in ("waiting_approval", "waiting_auth"):
        values = {
            "status": "cancelled",
            "finished_at": datetime.now(UTC),
            "pause_state": None,
            "error": rec.error or {"code": "CANCELLED_WHILE_WAITING", "message": "Cancelled while waiting for action."},
        }
        flipped = (
            db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status.in_(("waiting_approval", "waiting_auth")))
            .update(values)
        )
        if flipped == 0:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Execution is no longer waiting.")
        db.commit()
        bus.publish(execution_id, {
            "event": "execution.cancelled",
            "execution_id": execution_id,
            "workflow_id": rec.workflow_id,
            "status": "cancelled",
        })
        log_event(db, EXECUTION_CANCEL, target_type="execution", target_id=execution_id, user_id=user.id)
        return ok({"id": execution_id, "status": "cancelled"})

    # 2. Queued execution: not claimed by a worker yet -> transition directly to cancelled
    if rec.status == "queued":
        values = {
            "status": "cancelled",
            "finished_at": datetime.now(UTC),
            "error": rec.error or {"code": "CANCELLED_IN_QUEUE", "message": "Execution cancelled before starting."},
        }
        flipped = (
            db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status == "queued")
            .update(values)
        )
        if flipped == 0:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Execution is no longer queued.")
        db.commit()
        bus.publish(execution_id, {
            "event": "execution.cancelled",
            "execution_id": execution_id,
            "workflow_id": rec.workflow_id,
            "status": "cancelled",
        })
        log_event(db, EXECUTION_CANCEL, target_type="execution", target_id=execution_id, user_id=user.id)
        return ok({"id": execution_id, "status": "cancelled"})

    # 3. Already cancelling -> FORCE CANCEL immediately
    if rec.status == "cancelling":
        values = {
            "status": "cancelled",
            "finished_at": datetime.now(UTC),
            "error": rec.error or {"code": "FORCE_CANCELLED", "message": "Execution force-cancelled by user."},
        }
        flipped = (
            db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status == "cancelling")
            .update(values)
        )
        if flipped == 0:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Execution is not cancelling.")
        db.commit()
        signal_cancel(execution_id)
        bus.publish(execution_id, {
            "event": "execution.cancelled",
            "execution_id": execution_id,
            "workflow_id": rec.workflow_id,
            "status": "cancelled",
        })
        log_event(db, EXECUTION_CANCEL, target_type="execution", target_id=execution_id, user_id=user.id)
        return ok({"id": execution_id, "status": "cancelled"})

    # 4. Running execution -> transition to cancelling, signal local runner instantly
    flipped = (
        db.query(Execution)
        .filter(Execution.id == execution_id, Execution.status == "running")
        .update({"status": "cancelling"})
    )
    if flipped == 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Execution is not running.")
    db.commit()
    # Instantly notify in-process runner if active locally
    signal_cancel(execution_id)
    bus.publish(execution_id, {
        "event": "execution.cancelling",
        "execution_id": execution_id,
        "workflow_id": rec.workflow_id,
        "status": "cancelling",
    })
    log_event(db, EXECUTION_CANCEL, target_type="execution", target_id=execution_id, user_id=user.id)
    return ok({"id": execution_id, "status": "cancelling"})


@router.post("/api/executions/{execution_id}/resume")
def resume_execution(
    execution_id: str,
    body: ResumeRequest | None = None,
    approved: bool | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resume a paused execution with an approve/reject decision or after authentication reconnect."""
    approved = bool(approved) if approved is not None else (bool(body.approved) if body is not None else True)
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    if rec.status not in ("waiting_approval", "waiting_auth"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Execution is not waiting for approval or authentication.")

    pause = rec.pause_state or {}
    is_auth_pause = rec.status == "waiting_auth"

    if not is_auth_pause:
        allowed = pause.get("approvers") or []
        if allowed and user.id not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a listed approver for this step.")

    # Re-queue for the worker to pick up.
    queue = get_queue()
    if is_auth_pause:
        # Re-run from the paused node seeding prior upstream results
        paused_node = pause.get("node_id")
        payload = {
            "workflow_data": rec.workflow_data,
            "trigger_items": rec.trigger_data or [{}],
            "trigger": rec.trigger,
            "user_id": rec.user_id,
            "workflow_id": rec.workflow_id,
            "version": rec.workflow_version,
            "workspace_id": workflow_workspace(db, rec.workflow_id),
            "_retry_from_node": paused_node,
            "_retry_source": execution_id,
        }
    else:
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

    # CAS: claim the resume atomically
    target_status = rec.status
    flipped = (
        db.query(Execution)
        .filter(Execution.id == execution_id, Execution.status == target_status)
        .update({"status": "queued"})
    )
    if flipped == 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Execution is no longer waiting.")
    db.commit()
    if not queue.requeue(execution_id, payload):
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        if not queue.enqueue(job_id, execution_id, payload):
            db.query(Execution).filter(
                Execution.id == execution_id, Execution.status == "queued"
            ).update({"status": target_status})
            db.commit()
            raise HTTPException(status.HTTP_409_CONFLICT, "Execution is already queued.")
    log_event(db, EXECUTION_RESUME, target_type="execution", target_id=execution_id, user_id=user.id,
              detail={"resumed_from": target_status, "approved": approved})
    return ok({"id": execution_id, "status": "queued"})


class RunNodeRequest(BaseModel):
    """Execute a single node with seeded upstream data (standalone or referencing prior run)."""
    node_id: str
    source_execution_id: str | None = None


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

    Reuses persisted upstream data from the latest (or specified) execution so
    the target node runs with real inputs. Useful for step-by-step debugging.
    """
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    from app.billing.service import enforce_can_start_execution

    enforce_can_start_execution(db, rec.workspace_id)
    workflow_nodes = {n.get("id") for n in (rec.data or {}).get("nodes", [])}
    if body.node_id not in workflow_nodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node '{body.node_id}'.")

    source_exec_id = body.source_execution_id
    source_rec = None
    if source_exec_id:
        # Scope to this workflow: never reuse trigger data from another
        # tenant's execution (arbitrary-ID IDOR).
        source_rec = db.scalar(
            select(Execution).where(
                Execution.id == source_exec_id,
                Execution.workflow_id == workflow_id,
            )
        )
    if source_rec is None:
        source_rec = db.execute(
            select(Execution)
            .where(Execution.workflow_id == workflow_id)
            .order_by(Execution.started_at.desc(), Execution.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if source_rec:
            source_exec_id = source_rec.id

    trigger_items = (source_rec.trigger_data if source_rec and source_rec.trigger_data else None) or [{}]

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
            extra_payload={
                "_run_node": body.node_id,
                "_source_execution": source_exec_id,
            },
        )
    except WorkflowValidationError as ve:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ve.to_dict())
    log_event(db, EXECUTION_RUN, target_type="workflow", target_id=workflow_id, user_id=user.id,
              detail={"execution_id": execution_id, "run_node": body.node_id, "source_execution": source_exec_id})
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
    from app.billing.service import enforce_can_start_execution

    enforce_can_start_execution(db, rec.workspace_id)
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
