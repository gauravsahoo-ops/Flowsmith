"""Telemetry and execution lifecycle persistence service (Flowsmith Logs & Monitoring).

Provides:
- Thread-safe capturing of outbound API request/response telemetry.
- Step-trace normalization and persistence into ExecutionStep models.
- Execution-level aggregation: record processing metrics, connector detection,
  safe error categorization, canonical status mapping, and indexable columns.
- Defense-in-depth secret redaction and payload size bounding.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.engine.redact import (
    redact_headers,
    redact_payload,
    redact_url,
    sanitize_error,
)
from app.models.execution import Execution
from app.models.monitoring_telemetry import ApiRequestTelemetry, ExecutionStep

logger = logging.getLogger("telemetry.service")

# Thread-safe in-memory buffer for in-flight executions before persistence
_API_BUFFERS_LOCK = threading.Lock()
_API_BUFFERS: dict[str, list[dict[str, Any]]] = {}

# Canonical 6 statuses
CANONICAL_STATUSES = frozenset({
    "success",
    "failed",
    "running",
    "partial_success",
    "retrying",
    "cancelled",
})

# Status mapping from internal engine states
INTERNAL_TO_CANONICAL: dict[str, str] = {
    "success": "success",
    "completed": "success",
    "failed": "failed",
    "error": "failed",
    "timeout": "timeout",
    "running": "running",
    "queued": "running",
    "waiting_approval": "running",
    "waiting_auth": "running",
    "partial_success": "partial_success",
    "retrying": "retrying",
    "cancelling": "cancelled",
    "cancelled": "cancelled",
}


def map_canonical_status(raw_status: str | None, has_partial: bool = False, is_retrying: bool = False) -> str:
    """Map internal engine state to the 6 canonical statuses."""
    if is_retrying:
        return "retrying"
    if has_partial:
        return "partial_success"
    if not raw_status:
        return "running"
    return INTERNAL_TO_CANONICAL.get(raw_status.lower(), "failed")


def record_api_call(
    *,
    execution_id: str,
    node_id: str | None = None,
    connector_name: str | None = None,
    operation: str | None = None,
    http_method: str = "GET",
    endpoint_url: str = "",
    query_params: dict[str, Any] | None = None,
    request_headers: dict[str, Any] | None = None,
    request_payload: Any = None,
    http_status_code: int | None = None,
    response_headers: dict[str, Any] | None = None,
    response_payload: Any = None,
    duration_ms: float | None = None,
    error_message: str | None = None,
    correlation_id: str | None = None,
    organization_id: int | None = None,
    workspace_id: str | None = None,
) -> str:
    """Buffer an outbound API request/response with sensitive-data masking."""
    req_id = f"req_{uuid.uuid4().hex[:12]}"

    sanitized_url = redact_url(endpoint_url)
    sanitized_headers = redact_headers(request_headers)
    sanitized_resp_headers = redact_headers(response_headers)
    sanitized_req_body, req_truncated = redact_payload(request_payload)
    sanitized_resp_body, resp_truncated = redact_payload(response_payload)
    is_truncated = req_truncated or resp_truncated

    entry: dict[str, Any] = {
        "id": req_id,
        "execution_id": execution_id,
        "step_id": None,  # Linked upon step persistence
        "node_id": node_id,
        "connector_name": connector_name,
        "operation": operation,
        "http_method": http_method.upper() if http_method else "GET",
        "endpoint_url": sanitized_url,
        "query_params": query_params,
        "request_headers": sanitized_headers,
        "request_payload": sanitized_req_body,
        "http_status_code": http_status_code,
        "response_headers": sanitized_resp_headers,
        "response_payload": sanitized_resp_body,
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "error_message": error_message,
        "is_truncated": is_truncated,
        "correlation_id": correlation_id,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "created_at": datetime.now(UTC),
    }

    with _API_BUFFERS_LOCK:
        if execution_id not in _API_BUFFERS:
            _API_BUFFERS[execution_id] = []
        _API_BUFFERS[execution_id].append(entry)

    return req_id


def extract_node_record_counts(step: dict[str, Any]) -> dict[str, int]:
    """Calculate input, output, created, updated, skipped, failed counts for a step."""
    inputs = step.get("inputs")
    outputs = step.get("outputs")
    note = str(step.get("note") or "").lower()

    in_count = 0
    if isinstance(inputs, list):
        in_count = len(inputs)
    elif isinstance(inputs, dict):
        in_count = 1 if inputs else 0

    out_count = 0
    created_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    if step.get("status") in ("error", "failed"):
        failed_count = max(in_count, 1)

    if isinstance(outputs, list):
        out_count = len(outputs)
    elif isinstance(outputs, dict):
        if "items" in outputs and isinstance(outputs["items"], list):
            out_count = len(outputs["items"])
        elif "main" in outputs and isinstance(outputs["main"], list):
            out_count = len(outputs["main"])
        else:
            out_count = 1 if outputs else 0

    # Inspect node operation heuristics
    node_type = str(step.get("node_type") or "").lower()
    if "create" in node_type or "insert" in node_type or "add" in note:
        created_count = out_count
    elif "update" in node_type or "patch" in node_type or "modify" in note:
        updated_count = out_count
    elif "filter" in node_type or "skip" in note:
        skipped_count = max(0, in_count - out_count)
    else:
        created_count = out_count

    return {
        "input_record_count": in_count,
        "output_record_count": out_count,
        "created_record_count": created_count,
        "updated_record_count": updated_count,
        "skipped_record_count": skipped_count,
        "failed_record_count": failed_count,
    }


def finalize_execution_telemetry(
    db: Session,
    rec: Execution,
    result: Any,
    job: Any,
) -> None:
    """Extract and persist all telemetry (ExecutionStep, ApiRequestTelemetry, Execution columns)."""
    try:
        execution_id = rec.id
        workflow_data = getattr(job, "workflow_data", {}) or rec.workflow_data or {}
        nodes = workflow_data.get("nodes", []) or []

        # 1. Pop buffered API calls
        with _API_BUFFERS_LOCK:
            buffered_api_calls = _API_BUFFERS.pop(execution_id, [])

        # 2. Timing
        started_at = rec.started_at or datetime.now(UTC)
        finished_at = rec.finished_at or datetime.now(UTC)
        duration_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000.0)
        rec.duration_ms = round(duration_ms, 2)

        # 3. Detect connectors and objects
        source_connector = None
        destination_connector = None
        source_object = None
        destination_object = None

        node_type_map = {n.get("id"): n for n in nodes if isinstance(n, dict)}
        for idx, node in enumerate(nodes):
            ntype = node.get("type", "")
            params = node.get("parameters", {}) or {}
            obj = params.get("object_type") or params.get("resource") or params.get("entity") or None

            if idx == 0 or ntype in ("webhook", "schedule", "manual_trigger", "dataload"):
                if not source_connector:
                    source_connector = ntype
                    source_object = obj or ("file" if ntype == "dataload" else "payload")
            elif ntype not in ("condition", "if_condition", "filter", "merge", "switch", "router"):
                destination_connector = ntype
                destination_object = obj

        # If HTTP request node was executed, inspect parameters
        for node in nodes:
            if node.get("type") == "http_request":
                p = node.get("parameters", {}) or {}
                if not rec.http_method:
                    rec.http_method = p.get("method", "GET").upper()
                if not rec.api_endpoint:
                    rec.api_endpoint = redact_url(p.get("url", ""))

        rec.source_connector = source_connector or "flowsmith_trigger"
        rec.destination_connector = destination_connector or "flowsmith_output"
        rec.source_object = source_object
        rec.destination_object = destination_object

        # 4. Process steps & record counters
        trace = result.trace if hasattr(result, "trace") and result.trace else (rec.trace or [])
        total_read = 0
        total_created = 0
        total_updated = 0
        total_skipped = 0
        total_failed = 0

        step_db_rows: list[ExecutionStep] = []
        node_step_map: dict[str, str] = {}

        for seq, step in enumerate(trace, 1):
            step_id = f"step_{execution_id[-8:]}_{seq}"
            nid = step.get("node_id", f"node_{seq}")
            node_step_map[nid] = step_id
            counts = extract_node_record_counts(step)

            if seq == 1:
                total_read += counts["input_record_count"] or counts["output_record_count"]
            total_created += counts["created_record_count"]
            total_updated += counts["updated_record_count"]
            total_skipped += counts["skipped_record_count"]
            total_failed += counts["failed_record_count"]

            step_status = step.get("status", "success")
            if step_status in ("error", "failed"):
                step_status = "failed"
            elif step_status == "skipped":
                step_status = "skipped"
            else:
                step_status = "success"

            step_err = step.get("error")
            e_type, e_code, e_msg = sanitize_error(step_err) if step_err else (None, None, None)

            # Node display name
            ndata = node_type_map.get(nid, {})
            step_name = ndata.get("name") or ndata.get("label") or nid

            err_details = None
            if isinstance(step_err, dict):
                err_details = dict(step_err)
            elif step_err:
                err_details = {"error": str(step_err)}
            if step.get("note"):
                err_details = err_details or {}
                err_details["note"] = step.get("note")

            step_row = ExecutionStep(
                id=step_id,
                execution_id=execution_id,
                organization_id=rec.organization_id,
                workspace_id=rec.workspace_id,
                node_id=nid,
                node_type=step.get("node_type") or ndata.get("type", "unknown"),
                step_name=step_name,
                operation=step.get("operation"),
                connector_id=step.get("connector_id"),
                sequence_number=seq,
                parent_step_id=None,
                status=step_status,
                started_at=started_at,
                completed_at=finished_at,
                duration_ms=float(step.get("duration_ms") or 0.0),
                input_record_count=counts["input_record_count"],
                output_record_count=counts["output_record_count"],
                created_record_count=counts["created_record_count"],
                updated_record_count=counts["updated_record_count"],
                skipped_record_count=counts["skipped_record_count"],
                failed_record_count=counts["failed_record_count"],
                error_type=e_type,
                error_code=e_code,
                error_message=e_msg,
                retry_count=step.get("retries", 0),
                correlation_id=rec.correlation_id,
                inputs=step.get("inputs"),
                outputs=step.get("outputs"),
                error_details=err_details,
            )
            step_db_rows.append(step_row)

        # 5. Persist ApiRequestTelemetry rows
        api_db_rows: list[ApiRequestTelemetry] = []
        for call_data in buffered_api_calls:
            call_node = call_data.get("node_id")
            linked_step_id = node_step_map.get(call_node) if call_node else None

            # Update execution HTTP summary if not already set
            if not rec.http_method:
                rec.http_method = call_data.get("http_method")
            if not rec.api_endpoint:
                rec.api_endpoint = call_data.get("endpoint_url")
            if not rec.http_status_code:
                rec.http_status_code = call_data.get("http_status_code")

            api_row = ApiRequestTelemetry(
                id=call_data["id"],
                execution_id=execution_id,
                step_id=linked_step_id,
                organization_id=rec.organization_id,
                workspace_id=rec.workspace_id,
                node_id=call_node,
                connector_name=call_data.get("connector_name") or rec.destination_connector,
                operation=call_data.get("operation"),
                http_method=call_data.get("http_method", "GET"),
                endpoint_url=call_data.get("endpoint_url", ""),
                query_params=call_data.get("query_params"),
                request_headers=call_data.get("request_headers"),
                request_payload=call_data.get("request_payload"),
                http_status_code=call_data.get("http_status_code"),
                response_headers=call_data.get("response_headers"),
                response_payload=call_data.get("response_payload"),
                duration_ms=call_data.get("duration_ms"),
                error_message=call_data.get("error_message"),
                is_truncated=call_data.get("is_truncated", False),
                correlation_id=rec.correlation_id,
                created_at=call_data.get("created_at") or datetime.now(UTC),
            )
            api_db_rows.append(api_row)

        # 6. Overall record statistics
        rec.records_read = total_read
        rec.records_created = total_created
        rec.records_updated = total_updated
        rec.records_skipped = total_skipped
        rec.records_failed = total_failed
        rec.records_processed = total_created + total_updated

        # 7. Partial success detection & canonical status
        has_partial = (
            rec.status == "success"
            and total_failed > 0
            and (total_created > 0 or total_updated > 0)
        )
        is_retrying = rec.status == "retrying"
        rec.status = map_canonical_status(rec.status, has_partial=has_partial, is_retrying=is_retrying)

        # 8. Safe error extraction
        if rec.status == "failed" or rec.error:
            e_type, e_code, e_sum = sanitize_error(rec.error)
            rec.error_type = e_type
            rec.error_code = e_code
            rec.error_summary = e_sum

        # 9. Batch add to session
        for s_row in step_db_rows:
            db.merge(s_row)
        for a_row in api_db_rows:
            db.merge(a_row)

        db.commit()
    except Exception as exc:
        logger.exception("Failed to finalize telemetry for execution %s: %s", getattr(rec, "id", "unknown"), exc)
        db.rollback()
