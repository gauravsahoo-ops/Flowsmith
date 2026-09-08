"""Monitoring dashboard API: execution stats, queue depth, system health."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.db import get_db
from app.metrics import render_metrics, _PROCESS_START
from app.models import Execution, WorkflowRecord, WebhookDelivery

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/stats")
def get_stats(
    _: object = Depends(get_current_user),
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
    _: object = Depends(get_current_user),
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
