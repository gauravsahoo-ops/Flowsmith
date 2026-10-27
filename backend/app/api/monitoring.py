"""Monitoring dashboard API: execution stats, queue depth, system health."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.db import get_db
from app.metrics import _PROCESS_START
from app.models import (
    ApiRequestTelemetry,
    Execution,
    User,
    WebhookDelivery,
    WorkflowRecord,
)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 query value without failing the whole dashboard."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _empty_summary() -> dict:
    """Return the complete summary shape for accounts with no workflows."""
    cards = {
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
        "total_api_calls": 0,
    }
    return {
        **cards,
        "running_executions": 0,
        "success_rate_percent": 0.0,
        "total_retries": 0,
        "error_breakdown": {},
        "cards": cards,
        "error_distribution": {},
    }


@router.get("/stats")
def get_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return execution statistics, queue depth, and system health."""
    from app.api.access import accessible_ids

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    ids = list(accessible_ids(db, user))

    # Every aggregate is scoped to workflows the caller can access. The
    # dashboard is not an installation-wide admin surface. Each table gets
    # one conditional aggregate instead of one COUNT round-trip per card.
    if ids:
        wf_row = db.execute(
            select(
                func.count(WorkflowRecord.id),
                func.coalesce(
                    func.sum(case((WorkflowRecord.active.is_(True), 1), else_=0)),
                    0,
                ),
            ).where(WorkflowRecord.id.in_(ids))
        ).one()
        exec_row = db.execute(
            select(
                func.count(Execution.id),
                func.coalesce(
                    func.sum(case((Execution.status == "running", 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Execution.status == "queued", 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Execution.status.in_(("success", "completed")),
                                    Execution.started_at >= hour_ago,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Execution.status.in_(("failed", "error", "timeout")),
                                    Execution.started_at >= hour_ago,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Execution.status.in_(("success", "completed")),
                                    Execution.started_at >= day_ago,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    Execution.status.in_(("failed", "error", "timeout")),
                                    Execution.started_at >= day_ago,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(Execution.workflow_id.in_(ids))
        ).one()
        delivery_row = db.execute(
            select(
                func.count(WebhookDelivery.id),
                func.coalesce(
                    func.sum(
                        case(
                            (WebhookDelivery.received_at >= hour_ago, 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(WebhookDelivery.workflow_id.in_(ids))
        ).one()

        total_workflows, active_workflows = (int(wf_row[0]), int(wf_row[1]))
        (
            total_executions,
            running_executions,
            queued_executions,
            hour_success,
            hour_failed,
            day_success,
            day_failed,
        ) = (int(value) for value in exec_row)
        total_deliveries, recent_deliveries = (
            int(delivery_row[0]),
            int(delivery_row[1]),
        )
    else:
        total_workflows = active_workflows = 0
        total_executions = running_executions = queued_executions = 0
        hour_success = hour_failed = day_success = day_failed = 0
        total_deliveries = recent_deliveries = 0

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
    """Return Prometheus-style metrics as JSON, scoped to the caller."""
    from app.api.access import accessible_ids

    ids = list(accessible_ids(db, user))
    if ids:
        total_workflows = db.scalar(
            select(func.count()).select_from(WorkflowRecord)
            .where(WorkflowRecord.id.in_(ids))
        ) or 0
        total_executions = db.scalar(
            select(func.count()).select_from(Execution)
            .where(Execution.workflow_id.in_(ids))
        ) or 0
        running = db.scalar(
            select(func.count()).select_from(Execution)
            .where(Execution.workflow_id.in_(ids), Execution.status == "running")
        ) or 0
    else:
        total_workflows = total_executions = running = 0
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
    workflow_ids = {exc.workflow_id for exc in executions if exc.workflow_id}
    workflow_names = (
        dict(
            db.execute(
                select(WorkflowRecord.id, WorkflowRecord.name).where(
                    WorkflowRecord.id.in_(workflow_ids)
                )
            ).all()
        )
        if workflow_ids
        else {}
    )

    items = []
    for exc in executions:
        statuses = exc.node_statuses or {}
        failed_nodes = [nid for nid, st in statuses.items() if st in ("failed", "error")]
        items.append({
            "id": exc.id,
            "workflow_id": exc.workflow_id,
            "workflow_name": workflow_names.get(exc.workflow_id, "Unknown Workflow"),
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

    allowed_wfs = list(accessible_ids(db, user))
    if not allowed_wfs:
        return ok(_empty_summary())

    filters = [Execution.workflow_id.in_(allowed_wfs)]
    if workflow_id:
        filters.append(Execution.workflow_id == workflow_id)
    if connector:
        term = f"%{connector.strip()}%"
        filters.append(
            or_(
                Execution.source_connector.ilike(term),
                Execution.destination_connector.ilike(term),
            )
        )
    parsed_start = _parse_iso_datetime(start_date)
    parsed_end = _parse_iso_datetime(end_date)
    if parsed_start:
        filters.append(Execution.started_at >= parsed_start)
    if parsed_end:
        filters.append(Execution.started_at <= parsed_end)

    status = func.lower(Execution.status)
    success_condition = status.in_(("success", "completed"))
    failed_condition = status.in_(("failed", "error", "timeout"))
    partial_condition = status == "partial_success"
    cancelled_condition = status.in_(("cancelled", "cancelling"))

    duration_expr = case(
        (Execution.duration_ms > 0, Execution.duration_ms),
        (
            and_(
                Execution.duration_ms.is_(None),
                Execution.started_at.is_not(None),
                Execution.finished_at.is_not(None),
            ),
            func.extract("epoch", Execution.finished_at - Execution.started_at) * 1000.0,
        ),
        else_=None,
    )
    records_expr = case(
        (
            func.coalesce(Execution.records_processed, 0) > 0,
            Execution.records_processed,
        ),
        else_=(
            func.coalesce(Execution.records_created, 0)
            + func.coalesce(Execution.records_updated, 0)
        ),
    )

    aggregate = db.execute(
        select(
            func.count(Execution.id),
            func.coalesce(func.sum(case((success_condition, 1), else_=0)), 0),
            func.coalesce(func.sum(case((failed_condition, 1), else_=0)), 0),
            func.coalesce(func.sum(case((partial_condition, 1), else_=0)), 0),
            func.coalesce(func.sum(case((cancelled_condition, 1), else_=0)), 0),
            func.avg(duration_expr),
            func.coalesce(func.sum(records_expr), 0),
            func.coalesce(func.sum(Execution.records_read), 0),
            func.coalesce(func.sum(Execution.records_failed), 0),
            func.coalesce(func.sum(Execution.retry_count), 0),
            func.coalesce(
                func.sum(
                    case(
                        (and_(failed_condition, Execution.error_type.is_(None)), 1),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(*filters)
    ).one()

    (
        total_execs,
        success_count,
        failed_count,
        partial_success_count,
        cancelled_count,
        avg_duration,
        total_records,
        total_read,
        total_failed_records,
        total_retries,
        failed_without_error,
    ) = aggregate
    total_execs = int(total_execs or 0)
    success_count = int(success_count or 0)
    failed_count = int(failed_count or 0)
    partial_success_count = int(partial_success_count or 0)
    cancelled_count = int(cancelled_count or 0)
    total_records = int(total_records or 0)
    total_read = int(total_read or 0)
    total_failed_records = int(total_failed_records or 0)
    total_retries = int(total_retries or 0)
    failed_without_error = int(failed_without_error or 0)
    in_progress_count = max(
        0,
        total_execs
        - success_count
        - failed_count
        - partial_success_count
        - cancelled_count,
    )

    error_rows = db.execute(
        select(Execution.error_type, func.count(Execution.id))
        .where(*filters, Execution.error_type.is_not(None))
        .group_by(Execution.error_type)
    ).all()
    errors_by_type = {
        str(error_type): int(count)
        for error_type, count in error_rows
        if error_type
    }
    if failed_without_error:
        errors_by_type["UNSPECIFIED_FAILURE"] = failed_without_error
    errors_by_type = dict(
        sorted(errors_by_type.items(), key=lambda item: item[1], reverse=True)
    )

    total_api_calls = int(
        db.scalar(
            select(func.count(ApiRequestTelemetry.id))
            .select_from(ApiRequestTelemetry)
            .join(Execution, Execution.id == ApiRequestTelemetry.execution_id)
            .where(*filters)
        )
        or 0
    )

    eligible_terminal = success_count + failed_count + partial_success_count
    success_rate = (
        round((success_count / eligible_terminal) * 100.0, 1)
        if eligible_terminal > 0
        else 0.0
    )
    avg_duration_ms = round(float(avg_duration), 1) if avg_duration is not None else 0.0

    cards = {
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
        "total_api_calls": total_api_calls,
    }
    return ok({
        **cards,
        "running_executions": in_progress_count,
        "success_rate_percent": success_rate,
        "total_retries": total_retries,
        "error_breakdown": errors_by_type,
        "cards": cards,
        "error_distribution": errors_by_type,
    })


