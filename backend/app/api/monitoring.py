"""Monitoring dashboard API: execution stats, queue depth, system health."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.db import get_db
from app.metrics import _PROCESS_START
from app.models import Execution, User, WebhookDelivery, WorkflowRecord

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/stats")
def get_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return execution statistics, queue depth, and system health."""
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    # Total workflows
    total_workflows = db.scalar(select(func.count()).select_from(WorkflowRecord)) or 0
    active_workflows = db.scalar(
        select(func.count()).select_from(WorkflowRecord).where(WorkflowRecord.active.is_(True))
    ) or 0

    # Execution counts
    total_executions = db.scalar(select(func.count()).select_from(Execution)) or 0
    running_executions = db.scalar(
        select(func.count()).select_from(Execution).where(Execution.status == "running")
    ) or 0
    queued_executions = db.scalar(
        select(func.count()).select_from(Execution).where(Execution.status == "queued")
    ) or 0

    # Success/failure rates (last hour)
    hour_success = db.scalar(
        select(func.count()).select_from(Execution)
        .where(Execution.status == "success")
        .where(Execution.started_at >= hour_ago)
    ) or 0
    hour_failed = db.scalar(
        select(func.count()).select_from(Execution)
        .where(Execution.status == "failed")
        .where(Execution.started_at >= hour_ago)
    ) or 0

    # Success/failure rates (last 24h)
    day_success = db.scalar(
        select(func.count()).select_from(Execution)
        .where(Execution.status == "success")
        .where(Execution.started_at >= day_ago)
    ) or 0
    day_failed = db.scalar(
        select(func.count()).select_from(Execution)
        .where(Execution.status == "failed")
        .where(Execution.started_at >= day_ago)
    ) or 0

    # Webhook deliveries
    total_deliveries = db.scalar(select(func.count()).select_from(WebhookDelivery)) or 0
    recent_deliveries = db.scalar(
        select(func.count()).select_from(WebhookDelivery)
        .where(WebhookDelivery.received_at >= hour_ago)
    ) or 0

    # System uptime
    uptime_seconds = time.monotonic() - _PROCESS_START

    return ok({
        "workflows": {"total": total_workflows, "active": active_workflows},
        "executions": {
            "total": total_executions,
            "running": running_executions,
            "queued": queued_executions,
        },
        "last_hour": {"success": hour_success, "failed": hour_failed},
        "last_24h": {"success": day_success, "failed": day_failed},
        "webhooks": {"total": total_deliveries, "last_hour": recent_deliveries},
        "uptime_seconds": round(uptime_seconds, 1),
    })


@router.get("/metrics")
def get_metrics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return Prometheus-style metrics as JSON."""
    total_workflows = db.scalar(select(func.count()).select_from(WorkflowRecord)) or 0
    total_executions = db.scalar(select(func.count()).select_from(Execution)) or 0
    running = db.scalar(
        select(func.count()).select_from(Execution).where(Execution.status == "running")
    ) or 0
    uptime = round(time.monotonic() - _PROCESS_START, 1)

    return ok({
        "workflows_total": total_workflows,
        "executions_total": total_executions,
        "executions_running": running,
        "uptime_seconds": uptime,
    })


@router.get("/dlq")
def get_dead_letter_queue(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    """Return failed or poison executions for Dead Letter Queue inspection."""
    from app.api.access import accessible_ids

    allowed_wfs = accessible_ids(db, user)
    stmt = (
        select(Execution)
        .where(Execution.status.in_(["failed", "error"]))
        .where(Execution.workflow_id.in_(allowed_wfs))
        .order_by(Execution.started_at.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    p, sz = page_params(page=page, pageSize=pageSize)
    executions = db.scalars(stmt.offset((p - 1) * sz).limit(sz)).all()

    items = []
    for exc in executions:
        wf = db.get(WorkflowRecord, exc.workflow_id)
        statuses = exc.node_statuses or {}
        failed_nodes = [nid for nid, st in statuses.items() if st in ("failed", "error")]
        items.append({
            "id": exc.id,
            "workflow_id": exc.workflow_id,
            "workflow_name": wf.name if wf else "Unknown Workflow",
            "status": exc.status,
            "error": exc.error,
            "failed_nodes": failed_nodes,
            "started_at": exc.started_at.isoformat() if exc.started_at else None,
            "finished_at": exc.finished_at.isoformat() if exc.finished_at else None,
            "duration_ms": (
                (exc.finished_at - exc.started_at).total_seconds() * 1000
                if (exc.finished_at and exc.started_at)
                else None
            ),
        })

    return ok(items, {"page": p, "pageSize": sz, "total": total})


@router.post("/dlq/{execution_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_dead_letter(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Requeue a Dead Letter Queue execution."""
    from app.api.executions import retry_execution

    return await retry_execution(execution_id=execution_id, body=None, user=user, db=db)


@router.get("/summary")
def get_monitoring_summary(
    workflow_id: str | None = None,
    connector: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return comprehensive monitoring summary cards, error distribution, and activity metrics."""
    from app.api.access import accessible_ids

    allowed_wfs = accessible_ids(db, user)
    if not allowed_wfs:
        return ok({
            "cards": {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "in_progress_executions": 0,
                "partially_successful_executions": 0,
                "cancelled_executions": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0.0,
                "total_records_processed": 0,
                "total_records_read": 0,
                "total_records_failed": 0,
                "retry_volume": 0,
            },
            "error_distribution": {},
        })

    stmt = select(Execution).where(Execution.workflow_id.in_(allowed_wfs))
    if workflow_id:
        stmt = stmt.where(Execution.workflow_id == workflow_id)
    if connector:
        term = f"%{connector.strip()}%"
        stmt = stmt.where(
            (Execution.source_connector.ilike(term)) | (Execution.destination_connector.ilike(term))
        )
    if start_date:
        try:
            dt_s = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            stmt = stmt.where(Execution.started_at >= dt_s)
        except Exception:
            pass
    if end_date:
        try:
            dt_e = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            stmt = stmt.where(Execution.started_at <= dt_e)
        except Exception:
            pass

    from sqlalchemy.orm import defer

    recs = db.scalars(
        stmt.options(
            defer(Execution.trace),
            defer(Execution.results),
            defer(Execution.workflow_data),
            defer(Execution.node_statuses),
        )
    ).all()

    total_execs = len(recs)
    success_count = 0
    failed_count = 0
    in_progress_count = 0
    partial_success_count = 0
    cancelled_count = 0
    total_duration_ms = 0.0
    duration_sample_count = 0
    total_records = 0
    total_read = 0
    total_failed_records = 0
    total_retries = 0
    errors_by_type: dict[str, int] = {}

    for r in recs:
        st = (r.status or "").lower()
        if st in ("success", "completed"):
            success_count += 1
        elif st in ("failed", "error", "timeout"):
            failed_count += 1
        elif st in ("running", "queued", "waiting_approval", "waiting_auth"):
            in_progress_count += 1
        elif st == "partial_success":
            partial_success_count += 1
        elif st in ("cancelled", "cancelling"):
            cancelled_count += 1
        else:
            in_progress_count += 1

        dur = r.duration_ms
        if dur is None and r.started_at and r.finished_at:
            dur = (r.finished_at - r.started_at).total_seconds() * 1000.0
        if dur is not None and dur > 0:
            total_duration_ms += dur
            duration_sample_count += 1

        rec_proc = r.records_processed or ((r.records_created or 0) + (r.records_updated or 0))
        total_records += rec_proc
        total_read += (r.records_read or 0)
        total_failed_records += (r.records_failed or 0)
        total_retries += (r.retry_count or 0)

        if r.error_type:
            errors_by_type[r.error_type] = errors_by_type.get(r.error_type, 0) + 1
        elif st in ("failed", "error", "timeout"):
            errors_by_type["UNSPECIFIED_FAILURE"] = errors_by_type.get("UNSPECIFIED_FAILURE", 0) + 1

    eligible_terminal = success_count + failed_count + partial_success_count
    success_rate = round((success_count / eligible_terminal) * 100.0, 1) if eligible_terminal > 0 else 0.0
    avg_duration_ms = round(total_duration_ms / duration_sample_count, 1) if duration_sample_count > 0 else 0.0

    return ok({
        "total_executions": total_execs,
        "successful_executions": success_count,
        "failed_executions": failed_count,
        "in_progress_executions": in_progress_count,
        "running_executions": in_progress_count,
        "partially_successful_executions": partial_success_count,
        "cancelled_executions": cancelled_count,
        "success_rate_percent": success_rate,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration_ms,
        "total_records_processed": total_records,
        "total_records_read": total_read,
        "total_records_failed": total_failed_records,
        "total_retries": total_retries,
        "error_breakdown": errors_by_type,
        "cards": {
            "total_executions": total_execs,
            "successful_executions": success_count,
            "failed_executions": failed_count,
            "in_progress_executions": in_progress_count,
            "partially_successful_executions": partial_success_count,
            "cancelled_executions": cancelled_count,
            "success_rate": success_rate,
            "avg_duration_ms": avg_duration_ms,
            "total_records_processed": total_records,
            "total_records_read": total_read,
            "total_records_failed": total_failed_records,
            "retry_volume": total_retries,
        },
        "error_distribution": errors_by_type,
    })


