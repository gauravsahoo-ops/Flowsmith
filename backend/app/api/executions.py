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
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import cast, or_, select, String
from sqlalchemy.orm import Session

from app.api.access import (
    accessible_ids,
    batch_permissions,
    get_permission,
    get_workflow,
    validate_connector_ownership,
)
from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.audit import (
    EXECUTION_EXPORT,
    EXECUTION_RUN,
    log_event,
)
from app.db import get_db
from app.engine.errors import WorkflowValidationError
from app.engine.redact import (
    preview_sanitize,
    redact_results,
    redact_sensitive,
    redact_trace_steps,
    sanitize_csv_cell,
)
from app.models import Execution, User
from app.models.monitoring_telemetry import (
    ApiRequestTelemetry,
)
from app.models.workflow import WorkflowRecord
from app.queue.worker import ensure_embedded_consumer
from app.repositories import ExecutionFilters, ExecutionRepository
from app.services.execution_service import ExecutionService, ExecutionServiceError

router = APIRouter(tags=["executions"])
logger = logging.getLogger("api.executions")

IN_PROGRESS_STATUSES = frozenset({"queued", "running", "cancelling"})
EXPORT_ROW_LIMIT = 10_000
# Trace rows are already bounded by the executor (one row per record step),
# and per-record steps keep their single input item. Each nested list inside
# a row must stay small too: the same 200-300 record array is attached to the
# loop/trigger/IF steps, so a 500-item window multiplied the detail payload to
# ~12 MB for a 291-step run and locked the inspector UI while it rendered.
# 50 mirrors the results preview (MAX_PREVIEW_ITEMS); the full data remains
# available through the execution export.
TRACE_PREVIEW_MAX_ITEMS = 50
TRACE_PREVIEW_MAX_ROWS = 5000


def _preview_trace_rows(trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Window each trace step's payload without dropping record-level rows.

    The generic preview sanitizer caps a list at 50 entries. Applied to the
    trace itself that silently hid every record after the 50th even though
    the engine emitted per-record steps. Keep all rows, bound each row's
    inputs/outputs instead. A generous overall row cap protects the response
    from pathological multi-node runs; the omission is explicit and the full
    trace remains available through Export.
    """
    rows = [
        preview_sanitize(dict(step), max_items=TRACE_PREVIEW_MAX_ITEMS)
        for step in (trace or [])
        if isinstance(step, dict)
    ]
    if len(rows) > TRACE_PREVIEW_MAX_ROWS:
        omitted = len(rows) - TRACE_PREVIEW_MAX_ROWS
        rows = rows[:TRACE_PREVIEW_MAX_ROWS]
        rows.append({
            "node_id": "__trace_truncated__",
            "node_type": "trace",
            "status": "skipped",
            "started_at": rows[-1].get("started_at") if rows else None,
            "duration_ms": 0,
            "note": (
                f"Trace preview limited to {TRACE_PREVIEW_MAX_ROWS} rows; "
                f"{omitted} further steps are stored. Use Export for the complete trace."
            ),
        })
    return rows


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


def _public_pause_state(pause: Any) -> Any:
    """Return pause metadata without encrypted resume blobs.

    Tool-approval pauses carry an encrypted ReAct checkpoint in ``state``.
    The worker reads it from PostgreSQL; API clients only need the display
    metadata (tool, risk, message, approvers).
    """
    if not isinstance(pause, dict):
        return pause
    return {key: value for key, value in pause.items() if key != "state"}


def _to_dict(
    rec: Execution,
    wf_name: str | None = None,
    search: str | None = None,
    user_email: str | None = None,
    db: Session | None = None,
    preloaded_staged: list[Any] | None = None,
    preloaded_api_reqs: list[Any] | None = None,
    preloaded_errors: list[Any] | None = None,
    redact_search_values: bool = False,
) -> dict[str, Any]:
    duration_ms = rec.duration_ms
    if duration_ms is None and rec.started_at is not None:
        # SQLite returns naive datetimes while PostgreSQL returns aware ones.
        # Normalize both so acceptance runs on SQLite do not crash here.
        started = rec.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        finished = rec.finished_at or datetime.now(UTC)
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=UTC)
        duration_ms = round((finished - started).total_seconds() * 1000.0, 2)

    source_conn = rec.source_connector
    dest_conn = rec.destination_connector
    src_obj = rec.source_object
    dst_obj = rec.destination_object
    http_m = rec.http_method
    api_ep = rec.api_endpoint
    http_sc = rec.http_status_code
    r_read = rec.records_read or 0
    r_created = rec.records_created or 0
    r_updated = rec.records_updated or 0
    r_skipped = rec.records_skipped or 0
    r_failed = rec.records_failed or 0
    r_proc = rec.records_processed or 0
    if not wf_name:
        wf_name = getattr(rec, "workflow_name", None)

    # Dynamic fallback if integration metadata or status code is missing/default
    # CRITICAL PERFORMANCE GUARD: Avoid triggering lazy loading on deferred columns (trace, workflow_data)
    from sqlalchemy.orm.base import NO_VALUE

    raw_wf_data = rec.__dict__.get("workflow_data")
    wf_data = raw_wf_data if (raw_wf_data is not None and raw_wf_data is not NO_VALUE) else None

    raw_trace = rec.__dict__.get("trace")
    trace = raw_trace if (raw_trace is not None and raw_trace is not NO_VALUE) else None

    if wf_data is not None and (
        not dest_conn
        or dest_conn in ("flowsmith_output", "flowsmith.data_load", "data_load")
        or not src_obj
        or src_obj in ("payload", "trigger", "event", "data")
        or not dst_obj
        or not http_sc
        or r_read <= 1
    ):
        try:
            from app.services.telemetry_service import extract_execution_flow_metadata, extract_node_record_counts
            meta = extract_execution_flow_metadata(
                wf_data,
                trigger=rec.trigger,
                trace=trace,
                error=rec.error,
                status=rec.status,
                workflow_name=wf_name,
            )
            if dest_conn in ("flowsmith.data_load", "data_load", "csv_parser", "csv", "tsv", "file"):
                source_conn = "data_load"
                dest_conn = meta.get("destination_connector") or "flowsmith_output"
            elif not dest_conn or (dest_conn == "flowsmith_output" and meta.get("destination_connector") != "flowsmith_output"):
                dest_conn = meta.get("destination_connector") or dest_conn

            if not source_conn or (source_conn in ("manual", "schedule", "cron", "flowsmith_trigger") and meta.get("source_connector") == "data_load"):
                source_conn = meta.get("source_connector") or source_conn

            if not src_obj or src_obj in ("payload", "trigger", "event", "data"):
                src_obj = meta.get("source_object") or dst_obj or meta.get("destination_object")
            if not dst_obj:
                dst_obj = meta.get("destination_object") or src_obj
            if not http_m:
                http_m = meta.get("http_method")
            if not api_ep:
                api_ep = meta.get("api_endpoint")
            if not http_sc:
                http_sc = meta.get("http_status_code")

            if trace and (r_read <= 1 or r_proc <= 3):
                max_batch = 0
                ds_read = 0
                for s in trace:
                    c = extract_node_record_counts(s)
                    nt = str(s.get("node_type") or "").lower()
                    if "data_load" in nt or "csv" in nt:
                        ds_read = max(ds_read, c["output_record_count"], c["input_record_count"])
                    max_batch = max(max_batch, c["output_record_count"], c["input_record_count"])
                if max_batch > 1:
                    r_read = ds_read if ds_read > 0 else max_batch
                    r_proc = max_batch
                    r_created = max_batch
        except Exception:
            logger.debug("flow metadata extraction failed for execution=%s", rec.id, exc_info=True)
    elif wf_data is None:
        # Fallback defaults for list queries when snapshot is deferred
        if not source_conn:
            source_conn = rec.trigger or "manual"
        if not dest_conn or dest_conn in ("flowsmith_output", "flowsmith.data_load", "data_load"):
            dest_conn = dest_conn or "flowsmith_output"
        if not src_obj or src_obj in ("payload", "trigger", "event", "data"):
            src_obj = src_obj or "record"
        if not dst_obj:
            dst_obj = src_obj or "record"
        if not http_m:
            http_m = "POST"
        if not http_sc:
            http_sc = 200 if rec.status == "success" else (500 if rec.status in ("failed", "error", "timeout") else 202)

    search_matches = []
    if search and search.strip():
        try:
            from app.services.telemetry_service import extract_execution_search_matches
            search_matches = extract_execution_search_matches(
                rec,
                search.strip(),
                workflow_name=wf_name,
                user_email=user_email,
                db=db if (preloaded_staged is None and preloaded_api_reqs is None and preloaded_errors is None) else None,
                preloaded_staged=preloaded_staged,
                preloaded_api_reqs=preloaded_api_reqs,
                preloaded_errors=preloaded_errors,
                redact_values=redact_search_values,
            )
        except Exception:
            logger.warning(
                "search match extraction failed for execution=%s", rec.id, exc_info=True
            )

    return {
        "id": rec.id,
        "workflow_id": rec.workflow_id,
        "workflow_name": wf_name,
        "workflow_version": rec.workflow_version,
        "trigger": rec.trigger,
        "status": rec.status,
        "error": rec.error,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
        "pause_state": _public_pause_state(rec.pause_state),
        "duration_ms": duration_ms,
        "queue_wait_ms": getattr(rec, "queue_wait_ms", None),
        "source_connector": source_conn or rec.trigger or "flowsmith_trigger",
        "destination_connector": dest_conn or "flowsmith_output",
        "source_object": src_obj,
        "destination_object": dst_obj,
        "http_method": http_m,
        "api_endpoint": api_ep,
        "http_status_code": http_sc,
        "records_read": r_read,
        "records_created": r_created,
        "records_updated": r_updated,
        "records_skipped": r_skipped,
        "records_failed": r_failed,
        "records_processed": r_proc if r_proc > 0 else (r_created + r_updated),
        "retry_count": rec.retry_count or 0,
        "error_type": rec.error_type,
        "error_code": rec.error_code,
        "error_summary": rec.error_summary or (rec.error.get("message") if isinstance(rec.error, dict) else str(rec.error) if rec.error else None),
        "correlation_id": rec.correlation_id,
        "parent_execution_id": rec.parent_execution_id,
        "organization_id": rec.organization_id,
        "workspace_id": rec.workspace_id,
        "search_matches": search_matches,
        "matched": bool(search_matches),
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
    organization_id: str | None = None,
) -> str:
    """Create the execution row (queued) and enqueue the job (spec 25/13).

    Shared by manual runs, webhooks, retries and the scheduler; returns the
    new execution id. This wrapper keeps the historical import/patch target
    (``app.api.executions.start_execution``) stable while the application
    service owns validation, row creation, enqueue/compensation, metrics and
    embedded-consumer startup.
    """
    nodes = workflow_data.get("nodes") if isinstance(workflow_data, dict) else None
    validate_connector_ownership(db, user_id, nodes)
    return ExecutionService(
        db,
        # Resolved at call time so tests can keep patching this module-level
        # symbol to suppress the embedded consumer.
        ensure_consumer=ensure_embedded_consumer,
    ).start_execution(
        workflow_id=workflow_id,
        user_id=user_id,
        version=version,
        workflow_data=workflow_data,
        trigger=trigger,
        trigger_items=trigger_items,
        workspace_id=workspace_id,
        extra_payload=extra_payload,
        parent_execution_id=parent_execution_id,
        retry_count=retry_count,
        correlation_id=correlation_id,
        organization_id=organization_id,
    )


def has_running_execution(db: Session, workflow_id: str) -> bool:
    """Spec 8.4/13: never run two executions of the same workflow at once
    for webhook/schedule triggers (skip if one is queued or running)."""
    return db.scalar(
        select(Execution.id).where(
            Execution.workflow_id == workflow_id,
            Execution.trigger != "sub_workflow",
            Execution.status.in_(
                ("queued", "running", "cancelling", "waiting_approval", "waiting_auth")
            ),
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
def run_workflow(
    workflow_id: str,
    body: RunRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rec = get_workflow(db, workflow_id, user, require_edit=True)
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


def _parse_iso_timestamp(value: str | None, field: str) -> datetime | None:
    """Parse an ISO-8601 query timestamp; keep the historical 422 shape."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            422,
            f"{field} must be a valid ISO-8601 timestamp.",
        ) from exc


def _execution_filters(
    *,
    workflow_id: str | None,
    status: str | None,
    connector: str | None,
    source_object: str | None,
    destination_object: str | None,
    http_status: int | None,
    error_type: str | None,
    trigger: str | None,
    search: str | None,
    start_date: str | None,
    end_date: str | None,
    include_children: bool = False,
) -> ExecutionFilters:
    return ExecutionFilters(
        workflow_id=workflow_id,
        status=status,
        connector=connector,
        source_object=source_object,
        destination_object=destination_object,
        http_status=http_status,
        error_type=error_type,
        trigger=trigger,
        search=search,
        include_children=include_children,
        started_after=_parse_iso_timestamp(start_date, "start_date"),
        started_before=_parse_iso_timestamp(end_date, "end_date"),
    )


@router.get("/api/executions/universal-search")
def universal_search_executions_endpoint(
    q: str,
    category: str = "all",
    workflow_id: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    pageSize: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """YouTube-like Universal Search across all execution logs, steps, errors, and telemetry."""
    from app.services.telemetry_service import search_universal_executions

    res = search_universal_executions(
        db,
        user,
        query=q,
        category=category,
        workflow_id=workflow_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=pageSize,
    )
    return ok(res["results"], {
        "page": res["page"],
        "pageSize": res["pageSize"],
        "total": res["total"],
        "query": res["query"],
        "category": res["category"],
        "facets": res["facets"],
    })


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
    include_children: bool = False,
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

    filters = _execution_filters(
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
        include_children=include_children or trigger == "sub_workflow",
    )
    recs, total = ExecutionRepository(db).list_page(
        list(ids),
        filters=filters,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=size,
    )
    wf_ids = {r.workflow_id for r in recs if r.workflow_id}
    u_ids = {r.user_id for r in recs if r.user_id is not None}
    names = {
        wid: name
        for wid, name in db.execute(
            select(WorkflowRecord.id, WorkflowRecord.name).where(
                WorkflowRecord.id.in_(wf_ids)
            )
        ).all() if wf_ids
    }
    user_emails = {
        uid: email
        for uid, email in db.execute(
            select(User.id, User.email).where(
                User.id.in_(u_ids)
            )
        ).all() if u_ids
    }
    perms = batch_permissions(db, wf_ids, user)
    # Pre-batch search dependencies to eliminate N+1 queries during list serialization
    from collections import defaultdict

    rec_ids = [r.id for r in recs if r.id]
    staged_by_exec: dict[str, list[Any]] = defaultdict(list)
    api_by_exec: dict[str, list[Any]] = defaultdict(list)
    err_by_exec: dict[str, list[Any]] = defaultdict(list)

    if search and search.strip() and rec_ids:
        term = search.strip()
        from app.services.telemetry_service import parse_datetime_query
        parsed_dt = parse_datetime_query(term)
        date_win = parsed_dt.get("window") if parsed_dt else None
        dt_start, dt_end = date_win if date_win else (None, None)

        try:
            from app.models.staged_record import StagedContactRecord
            staged_filters = [
                StagedContactRecord.first_name.icontains(term, autoescape=True),
                StagedContactRecord.last_name.icontains(term, autoescape=True),
                StagedContactRecord.email.icontains(term, autoescape=True),
                StagedContactRecord.phone.icontains(term, autoescape=True),
                StagedContactRecord.department.icontains(term, autoescape=True),
                StagedContactRecord.title.icontains(term, autoescape=True),
                StagedContactRecord.status.icontains(term, autoescape=True),
                StagedContactRecord.mailing_street.icontains(term, autoescape=True),
                StagedContactRecord.mailing_city.icontains(term, autoescape=True),
                StagedContactRecord.mailing_state.icontains(term, autoescape=True),
                StagedContactRecord.mailing_postal_code.icontains(term, autoescape=True),
                StagedContactRecord.mailing_country.icontains(term, autoescape=True),
                StagedContactRecord.description.icontains(term, autoescape=True),
                StagedContactRecord.error_message.icontains(term, autoescape=True),
                StagedContactRecord.salesforce_id.icontains(term, autoescape=True),
                cast(StagedContactRecord.raw_data, String).icontains(term, autoescape=True),
            ]
            if dt_start and dt_end:
                staged_filters.append(StagedContactRecord.created_at.between(dt_start, dt_end))

            for s in db.scalars(
                select(StagedContactRecord).where(
                    StagedContactRecord.execution_id.in_(rec_ids),
                    or_(*staged_filters),
                ).limit(300)
            ).all():
                if s.execution_id:
                    staged_by_exec[s.execution_id].append(s)
        except Exception:
            logger.warning(
                "staged-record enrichment failed term=%r", term, exc_info=True
            )

        try:
            api_filters = [
                ApiRequestTelemetry.endpoint_url.icontains(term, autoescape=True),
                ApiRequestTelemetry.connector_name.icontains(term, autoescape=True),
                ApiRequestTelemetry.http_method.icontains(term, autoescape=True),
                ApiRequestTelemetry.error_message.icontains(term, autoescape=True),
                cast(ApiRequestTelemetry.request_payload, String).icontains(term, autoescape=True),
                cast(ApiRequestTelemetry.response_payload, String).icontains(term, autoescape=True),
                cast(ApiRequestTelemetry.request_headers, String).icontains(term, autoescape=True),
                cast(ApiRequestTelemetry.query_params, String).icontains(term, autoescape=True),
            ]
            if dt_start and dt_end:
                api_filters.append(ApiRequestTelemetry.created_at.between(dt_start, dt_end))

            for r in db.scalars(
                select(ApiRequestTelemetry).where(
                    ApiRequestTelemetry.execution_id.in_(rec_ids),
                    or_(*api_filters),
                ).limit(300)
            ).all():
                if r.execution_id:
                    api_by_exec[r.execution_id].append(r)
        except Exception:
            logger.warning(
                "API-telemetry enrichment failed term=%r", term, exc_info=True
            )

        try:
            from app.models.error_event import ErrorEvent
            err_filters = [
                ErrorEvent.message.icontains(term, autoescape=True),
                ErrorEvent.title.icontains(term, autoescape=True),
                ErrorEvent.code.icontains(term, autoescape=True),
            ]
            if dt_start and dt_end:
                err_filters.append(ErrorEvent.created_at.between(dt_start, dt_end))

            for e in db.scalars(
                select(ErrorEvent).where(
                    ErrorEvent.execution_id.in_(rec_ids),
                    or_(*err_filters),
                ).limit(300)
            ).all():
                if e.execution_id:
                    err_by_exec[e.execution_id].append(e)
        except Exception:
            logger.warning(
                "error-event enrichment failed term=%r", term, exc_info=True
            )

    items = [
        _to_dict(
            r,
            wf_name=names.get(r.workflow_id, r.workflow_id[:8] if r.workflow_id else "Untitled"),
            search=search,
            user_email=user_emails.get(r.user_id),
            db=db,
            preloaded_staged=staged_by_exec.get(r.id, []),
            preloaded_api_reqs=api_by_exec.get(r.id, []),
            preloaded_errors=err_by_exec.get(r.id, []),
            redact_search_values=perms.get(r.workflow_id) not in ("owner", "edit"),
        )
        for r in recs
    ]
    return ok(items, {"page": page, "pageSize": size, "total": total})


@router.get("/api/executions/error-types")
def list_execution_error_types(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return error categories that actually occur in accessible executions.

    The UI used to hard-code a stale taxonomy, so filters such as
    ``AUTH_ERROR`` never matched the canonical ``AUTHENTICATION_ERROR``.
    Returning observed values keeps both legacy rows and the current
    taxonomy filterable.
    """
    ids = accessible_ids(db, user)
    if not ids:
        return ok([])

    rows = ExecutionRepository(db).count_error_types(ids)
    return ok([
        {"value": error_type, "count": count}
        for error_type, count in rows
    ])


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
            headers={
                "Content-Disposition": 'attachment; filename="flowsmith-executions-export.csv"',
                "X-Export-Truncated": "false",
                "X-Export-Limit": str(EXPORT_ROW_LIMIT),
            },
        )

    filters = _execution_filters(
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
    recs = ExecutionRepository(db).list_for_export(
        ids,
        filters=filters,
        limit=EXPORT_ROW_LIMIT + 1,
    )
    truncated = len(recs) > EXPORT_ROW_LIMIT
    if truncated:
        recs = recs[:EXPORT_ROW_LIMIT]
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
        detail={
            "count": len(recs),
            "truncated": truncated,
            "limit": EXPORT_ROW_LIMIT,
            "filters": {
                "workflow_id": workflow_id,
                "status": status,
                "connector": connector,
            },
        },
    )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="flowsmith-executions-export.csv"',
            "X-Export-Truncated": "true" if truncated else "false",
            "X-Export-Limit": str(EXPORT_ROW_LIMIT),
        },
    )



@router.get("/api/executions/{execution_id}/status")
def get_execution_status(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Lightweight execution poll endpoint.

    The full execution payload includes the workflow snapshot, trace and
    results. A canvas polling every run does not need those on every tick;
    this endpoint keeps terminal-state polling cheap under concurrency.
    """
    rec = ExecutionRepository(db).get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    return ok({
        "id": rec.id,
        "status": rec.status,
        "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
        "duration_ms": rec.duration_ms,
        "queue_wait_ms": rec.queue_wait_ms,
        "error_summary": rec.error_summary,
    })


@router.get("/api/executions/{execution_id}")
def get_execution(
    execution_id: str,
    full: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rec = ExecutionRepository(db).get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    from app.models.workflow import WorkflowRecord
    wf_rec = db.get(WorkflowRecord, rec.workflow_id)
    workflow_name = wf_rec.name if wf_rec else rec.workflow_id

    results_outputs = (rec.results or {}).get("outputs") if isinstance(rec.results, dict) else {}
    results_inputs = (rec.results or {}).get("inputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if (results_outputs and isinstance(results_outputs, dict)) or (results_inputs and isinstance(results_inputs, dict)):
        for step in trace:
            nid = step.get("node_id")
            if not step.get("outputs") and results_outputs and isinstance(results_outputs, dict) and nid in results_outputs:
                step["outputs"] = results_outputs[nid]
            if not step.get("inputs") and results_inputs and isinstance(results_inputs, dict) and nid in results_inputs:
                step["inputs"] = results_inputs[nid]

    raw_results = rec.results
    raw_wf_data = rec.workflow_data

    if not full:
        trace = _preview_trace_rows(trace)
        raw_results = preview_sanitize(raw_results)
        raw_wf_data = preview_sanitize(raw_wf_data)

    trace = redact_trace_steps(trace)

    data = {
        **_to_dict(rec, wf_name=workflow_name),
        "results": redact_results(raw_results),
        "node_statuses": rec.node_statuses,
        "trace": trace,
        "workflow_data": redact_sensitive(raw_wf_data),
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

    rec = ExecutionRepository(db).get(execution_id)
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
    rec = ExecutionRepository(db).get(execution_id)
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


@router.get("/api/executions/{execution_id}/nodes/{node_id}/output")
def get_execution_node_output(
    execution_id: str,
    node_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the complete stored output for one node.

    The normal execution payload is deliberately preview-sanitized for fast
    rendering.  This endpoint is the explicit, per-node escape hatch used by
    the output panel when the user asks to inspect the untruncated records.
    """
    rec = ExecutionRepository(db).get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    outputs = (rec.results or {}).get("outputs", {}) if isinstance(rec.results, dict) else {}
    if node_id not in outputs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node output not found.")
    return ok({
        "node_id": node_id,
        "output": redact_sensitive(outputs[node_id]),
    })


@router.get("/api/executions/{execution_id}/trace")
def get_execution_trace(
    execution_id: str,
    full: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Step-by-step run log for the debugger (M8 + Phase 13): each step
    records the node's inputs, outputs, error, status, duration and the
    structured attempt/retry counts. Sensitive-looking keys are masked."""
    rec = ExecutionRepository(db).get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    results_outputs = (rec.results or {}).get("outputs") if isinstance(rec.results, dict) else {}
    results_inputs = (rec.results or {}).get("inputs") if isinstance(rec.results, dict) else {}
    trace = [dict(s) for s in (rec.trace or [])]
    if (results_outputs and isinstance(results_outputs, dict)) or (results_inputs and isinstance(results_inputs, dict)):
        for step in trace:
            nid = step.get("node_id")
            if not step.get("outputs") and results_outputs and isinstance(results_outputs, dict) and nid in results_outputs:
                step["outputs"] = results_outputs[nid]
            if not step.get("inputs") and results_inputs and isinstance(results_inputs, dict) and nid in results_inputs:
                step["inputs"] = results_inputs[nid]
    if not full:
        trace = _preview_trace_rows(trace)
    return ok({"steps": redact_trace_steps(trace)})


@router.get("/api/executions/{execution_id}/flamegraph")
def get_execution_flamegraph_endpoint(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return hierarchical waterfall/flamegraph data structure for the execution (Roadmap Initiative C)."""
    from app.telemetry.flamegraph import generate_execution_flamegraph

    rec = ExecutionRepository(db).get(execution_id)
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
    repo = ExecutionRepository(db)
    rec = repo.get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    can_edit = _can_edit_execution(db, rec, user)
    step_rows = repo.list_steps(execution_id)

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
                "metadata": (getattr(s, "error_details", None) or getattr(s, "step_metadata", None)) if can_edit else None,
                "inputs": getattr(s, "inputs", None) if can_edit else None,
                "outputs": getattr(s, "outputs", None) if can_edit else None,
            }
            for s in step_rows
        ]
        return ok([preview_sanitize(row) for row in data])

    # Fallback to rec.trace for runs executed prior to telemetry table migration
    trace = redact_trace_steps(_preview_trace_rows([dict(s) for s in (rec.trace or [])]))
    return ok(trace)


@router.get("/api/executions/{execution_id}/timeline")
def get_execution_timeline(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return chronological DAG timeline events for execution inspection."""
    repo = ExecutionRepository(db)
    rec = repo.get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    can_edit = _can_edit_execution(db, rec, user)

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
    steps = repo.list_steps(execution_id)

    api_calls = repo.list_api_calls(execution_id)
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
                "error": s.get("error") if can_edit else redact_sensitive(s.get("error")),
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
    page: int = 1,
    pageSize: int = 50,
    request_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return a lightweight page of outbound API calls for API inspector."""
    repo = ExecutionRepository(db)
    rec = repo.get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    p, size = page_params(page=page, pageSize=pageSize)
    rows, total, p = repo.list_api_requests(
        execution_id,
        page=p,
        page_size=size,
        focus_request_id=request_id,
    )

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
    return ok(items, {"page": p, "pageSize": size, "total": total})


@router.get("/api/executions/{execution_id}/requests/{request_id}")
def get_execution_request_detail(
    execution_id: str,
    request_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Lazy-load full payload and headers for one specific API call."""
    repo = ExecutionRepository(db)
    rec = repo.get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    # Full payloads/query params can contain credentials or tokens echoed by
    # the upstream API. The list view stays available to view shares, but the
    # raw capture is an editor-only surface.
    if not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    req = repo.get_api_request(execution_id, request_id)
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
    repo = ExecutionRepository(db)
    rec = repo.get(execution_id)
    if rec is None or not _can_view_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")

    rows = repo.list_retries(execution_id)

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

    try:
        outcome = ExecutionService(
            db,
            ensure_consumer=ensure_embedded_consumer,
        ).retry_execution(
            rec,
            user_id=user.id,
            workspace_id=workflow_workspace(db, rec.workflow_id),
            node_id=(body.node_id if body is not None else None) or None,
            reason=body.reason if body is not None else None,
            idempotency_key=body.idempotency_key if body is not None else None,
        )
    except ExecutionServiceError as exc:
        raise HTTPException(exc.http_status, detail=exc.message) from exc

    if outcome.idempotent_replay:
        return ok({
            "execution_id": outcome.execution_id,
            "idempotent_replay": True,
        })
    return ok({
        "execution_id": outcome.execution_id,
        "attempt_number": outcome.attempt_number,
    })



@router.post("/api/executions/{execution_id}/cancel")
def cancel_execution(execution_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    if rec.trigger == "sub_workflow":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Sub-execution must be cancelled through its parent execution.",
        )
    try:
        resulting_status = ExecutionService(db).cancel(rec, user_id=user.id)
    except ExecutionServiceError as exc:
        raise HTTPException(
            exc.http_status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ok({"id": execution_id, "status": resulting_status})


@router.post("/api/executions/{execution_id}/resume")
def resume_execution(
    execution_id: str,
    body: ResumeRequest | None = None,
    approved: bool | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resume a paused execution with an approve/reject decision or after authentication reconnect."""
    approved = approved if approved is not None else (body.approved if body is not None else True)
    rec = db.get(Execution, execution_id)
    if rec is None or not _can_edit_execution(db, rec, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    if rec.trigger == "sub_workflow":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Sub-execution must be resumed through its parent execution.",
        )

    workspace_id = workflow_workspace(db, rec.workflow_id)
    try:
        resulting_status = ExecutionService(db).resume(
            rec,
            user_id=user.id,
            approved=approved,
            workspace_id=workspace_id,
        )
    except ExecutionServiceError as exc:
        raise HTTPException(
            exc.http_status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ok({"id": execution_id, "status": resulting_status})


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
