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

