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


INTERNAL_UTILITY_TYPES = frozenset({
    "condition",
    "if_condition",
    "filter",
    "merge",
    "switch",
    "router",
    "split",
    "loop",
    "sub_workflow",
    "execute_sub_workflow",
    "set_variable",
    "set",
    "variables",
    "set_data",
    "code",
    "python_code",
    "javascript_code",
    "function",
    "noop",
    "delay",
    "wait",
    "sleep",
    "logger",
    "log",
    "debug",
    "transform",
    "data_transform",
    "json_transform",
    "mapper",
    "flowsmith_output",
    "output",
    "response",
    "webhook_response",
    "respond_to_webhook",
    "stop",
    "stop_and_error",
})

TRIGGER_TYPES = frozenset({
    "manual_trigger",
    "manual",
    "schedule",
    "cron",
    "webhook",
    "form_trigger",
    "chat_trigger",
    "error_trigger",
})

DATA_SOURCE_TYPES = frozenset({
    "flowsmith.data_load",
    "data_load",
    "dataload",
    "csv_parser",
    "csv",
    "tsv",
    "file",
    "file_io",
    "google_drive",
    "s3",
    "aws_s3",
    "ftp",
    "sftp",
})


def extract_node_object_name(params: dict[str, Any] | None) -> str | None:
    """Extract business entity or object from node parameters."""
    if not isinstance(params, dict):
        return None
    for key in (
        "object_name",
        "target_object",
        "object_type",
        "resource",
        "entity",
        "table_name",
        "table",
        "sheet_name",
        "collection_name",
        "collection",
        "topic",
        "channel",
        "project_key",
        "repo",
    ):
        val = params.get(key)
        if val and isinstance(val, str) and val.strip() and not val.strip().startswith("{{"):
            return val.strip()
    return None


def extract_execution_flow_metadata(
    workflow_data: dict[str, Any] | None,
    *,
    trigger: str | None = None,
    trace: list[dict[str, Any]] | None = None,
    error: Any = None,
    status: str | None = None,
    workflow_name: str | None = None,
) -> dict[str, Any]:
    """Accurately deduce integration flow, objects, and HTTP call summary.
    
    Ensures external integration connectors (salesforce, hubspot, jira, etc.) and
    data sources (data_load, csv_parser) are accurately identified and never
    masked by internal utility nodes (code, set_variable, filter).
    """
    wf = workflow_data or {}
    nodes = wf.get("nodes", []) if isinstance(wf, dict) else []

    source_connector = None
    destination_connector = None
    source_object = None
    destination_object = None
    http_method = None
    http_status_code = None
    api_endpoint = None

    # 1. Identify data source node (data_load, csv, etc.)
    data_source_node = None
    for n in nodes:
        ntype = n.get("type", "")
        if ntype in DATA_SOURCE_TYPES or "data_load" in ntype:
            data_source_node = n
            break

    # 2. Identify trigger node
    trigger_node = None
    for n in nodes:
        ntype = n.get("type", "")
        if ntype in TRIGGER_TYPES:
            trigger_node = n
            break

    # 3. Identify destination connector (business external node)
    external_nodes = [
        n for n in nodes
        if n.get("type") not in INTERNAL_UTILITY_TYPES
        and n.get("type") not in TRIGGER_TYPES
        and n != data_source_node
    ]

    dest_node = external_nodes[-1] if external_nodes else None

    # Source connector resolution
    if data_source_node:
        raw_type = data_source_node.get("type", "data_load")
        source_connector = "data_load" if "data_load" in raw_type else raw_type
        params = data_source_node.get("parameters", {}) or {}
        source_object = extract_node_object_name(params) or params.get("file_format") or "file"
    elif trigger_node:
        source_connector = trigger_node.get("type", "trigger")
        if source_connector == "manual_trigger":
            source_connector = "manual"
        params = trigger_node.get("parameters", {}) or {}
        source_object = extract_node_object_name(params)
    elif trigger:
        source_connector = trigger
    else:
        source_connector = "manual"

    # Destination connector resolution
    if dest_node:
        destination_connector = dest_node.get("type")
        params = dest_node.get("parameters", {}) or {}
        destination_object = extract_node_object_name(params)

        op = str(params.get("operation") or params.get("bulk_operation") or "").lower()
        if any(w in op for w in ("bulk", "insert", "create", "send", "post", "add")):
            http_method = "POST"
        elif any(w in op for w in ("update", "patch", "modify", "upsert")):
            http_method = "PATCH"
        elif any(w in op for w in ("delete", "remove")):
            http_method = "DELETE"
        elif any(w in op for w in ("query", "search", "get", "read", "list", "soql")):
            http_method = "GET"
        else:
            http_method = "POST"

        if params.get("custom_api_url"):
            api_endpoint = redact_url(params.get("custom_api_url"))
        elif params.get("url"):
            api_endpoint = redact_url(params.get("url"))
        elif destination_connector == "salesforce":
            if op == "bulk":
                api_endpoint = "/services/data/v63.0/jobs/ingest"
            elif destination_object:
                api_endpoint = f"/services/data/v63.0/sobjects/{destination_object}"
    else:
        http_node = next((n for n in nodes if n.get("type") == "http_request"), None)
        if http_node:
            destination_connector = "http_request"
            p = http_node.get("parameters", {}) or {}
            http_method = p.get("method", "GET").upper()
            api_endpoint = redact_url(p.get("url", ""))
            destination_object = extract_node_object_name(p)
        else:
            destination_connector = "flowsmith_output"

    # If destination_object is still None, try inferring from source_object or workflow name
    if not destination_object and source_object and source_object != "file":
        destination_object = source_object
    elif not destination_object and workflow_name:
        for entity in ("Contact", "Lead", "Account", "Case", "Opportunity", "Customer", "Invoice", "User"):
            if entity.lower() in workflow_name.lower():
                destination_object = entity
                break

    if not source_object and destination_object:
        source_object = destination_object

    # HTTP Status Code resolution
    if destination_connector not in ("flowsmith_output", None):
        st = (status or "").lower()
        if st in ("success", "completed"):
            is_bulk = "bulk" in str((dest_node.get("parameters", {}) or {}).get("operation", "") if dest_node else "")
            http_status_code = 201 if (http_method == "POST" and (is_bulk or destination_connector == "salesforce")) else 200
            if not http_method:
                http_method = "POST"
        elif st in ("failed", "error"):
            code_found = None
            if isinstance(error, dict):
                for k in ("status_code", "status", "http_status"):
                    val = error.get(k)
                    if isinstance(val, int) and 400 <= val <= 599:
                        code_found = val
                        break
            if not code_found and error:
                import re
                m = re.search(r'\b(4\d\d|5\d\d)\b', str(error))
                if m:
                    code_found = int(m.group(1))
            http_status_code = code_found or 400
            if not http_method:
                http_method = "POST"
        elif st in ("cancelled", "cancelling"):
            http_status_code = None

    return {
        "source_connector": source_connector,
        "destination_connector": destination_connector,
        "source_object": source_object,
        "destination_object": destination_object,
        "http_method": http_method,
        "http_status_code": http_status_code,
        "api_endpoint": api_endpoint,
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
        node_type_map = {n.get("id"): n for n in nodes if isinstance(n, dict)}

        # 1. Pop buffered API calls
        with _API_BUFFERS_LOCK:
            buffered_api_calls = _API_BUFFERS.pop(execution_id, [])

        # 2. Timing
        started_at = rec.started_at or datetime.now(UTC)
        finished_at = rec.finished_at or datetime.now(UTC)
        duration_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000.0)
        rec.duration_ms = round(duration_ms, 2)

        # 3. Detect connectors, objects, and HTTP summaries
        flow_meta = extract_execution_flow_metadata(
            workflow_data,
            trigger=rec.trigger,
            trace=result.trace if hasattr(result, "trace") and result.trace else rec.trace,
            error=rec.error,
            status=rec.status,
            workflow_name=getattr(rec, "workflow_name", None),
        )

        if not rec.source_connector or (rec.source_connector == "manual" and flow_meta["source_connector"] == "data_load"):
            rec.source_connector = flow_meta["source_connector"]
        if not rec.destination_connector or rec.destination_connector == "flowsmith_output":
            rec.destination_connector = flow_meta["destination_connector"]
        if not rec.source_object:
            rec.source_object = flow_meta["source_object"]
        if not rec.destination_object:
            rec.destination_object = flow_meta["destination_object"]
        if not rec.http_method and flow_meta["http_method"]:
            rec.http_method = flow_meta["http_method"]
        if not rec.api_endpoint and flow_meta["api_endpoint"]:
            rec.api_endpoint = flow_meta["api_endpoint"]
        if not rec.http_status_code and flow_meta["http_status_code"]:
            rec.http_status_code = flow_meta["http_status_code"]

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


def backfill_execution_telemetry_metadata(db: Session | None = None) -> int:
    """One-time or startup backfill routine that updates executions missing integration metadata."""
    from app.db import get_session
    from app.models.workflow import WorkflowRecord
    from sqlalchemy import or_

    close_db = False
    if db is None:
        db = get_session()
        close_db = True

    updated_count = 0
    try:
        wf_map = {
            w.id: (w.name, w.data)
            for w in db.query(WorkflowRecord).all()
        }

        recs = db.query(Execution).filter(
            or_(
                Execution.destination_connector == None,
                Execution.destination_connector == "flowsmith_output",
                Execution.http_status_code == None,
                Execution.source_connector == None,
            )
        ).all()

        for rec in recs:
            wf_info = wf_map.get(rec.workflow_id)
            wf_name = wf_info[0] if wf_info else ""
            wf_data = rec.workflow_data or (wf_info[1] if wf_info else {})

            meta = extract_execution_flow_metadata(
                wf_data,
                trigger=rec.trigger,
                trace=rec.trace,
                error=rec.error,
                status=rec.status,
                workflow_name=wf_name,
            )

            modified = False
            if not rec.source_connector or (rec.source_connector == "manual" and meta["source_connector"] == "data_load"):
                rec.source_connector = meta["source_connector"]
                modified = True
            if not rec.destination_connector or (rec.destination_connector == "flowsmith_output" and meta["destination_connector"] != "flowsmith_output"):
                rec.destination_connector = meta["destination_connector"]
                modified = True
            if not rec.source_object and meta["source_object"]:
                rec.source_object = meta["source_object"]
                modified = True
            if not rec.destination_object and meta["destination_object"]:
                rec.destination_object = meta["destination_object"]
                modified = True
            if not rec.http_method and meta["http_method"]:
                rec.http_method = meta["http_method"]
                modified = True
            if not rec.api_endpoint and meta["api_endpoint"]:
                rec.api_endpoint = meta["api_endpoint"]
                modified = True
            if not rec.http_status_code and meta["http_status_code"]:
                rec.http_status_code = meta["http_status_code"]
                modified = True

            if modified:
                updated_count += 1
                if updated_count % 100 == 0:
                    db.commit()

        if updated_count > 0:
            db.commit()
            logger.info("Successfully backfilled %d execution telemetry records", updated_count)
    except Exception as exc:
        logger.exception("Failed during execution telemetry backfill: %s", exc)
        db.rollback()
    finally:
        if close_db:
            db.close()

    return updated_count

