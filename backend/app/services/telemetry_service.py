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
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from dateutil import parser as date_parser
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


def _extract_item_collection_count(item: Any) -> int | None:
    """Check if an item is an envelope or dict containing a collection of records."""
    if not isinstance(item, dict):
        return None
    # 1. Direct count fields
    for k in (
        "total_csv_records",
        "total_rows",
        "total_records",
        "total_parsed",
        "valid_unique_contacts",
        "persisted_to_staged_db",
        "record_count",
        "records_count",
        "count",
    ):
        v = item.get(k)
        if isinstance(v, int) and v > 0:
            return v
    # 2. Check summary object
    summary = item.get("summary")
    if isinstance(summary, dict):
        for k in (
            "total_csv_records",
            "total_rows",
            "total_records",
            "total_parsed",
            "unique_count",
            "valid_unique_contacts",
            "persisted_count",
        ):
            v = summary.get(k)
            if isinstance(v, int) and v > 0:
                return v
    # 3. Check record list keys
    for lk in ("records", "rows", "data", "items"):
        lst = item.get(lk)
        if isinstance(lst, list) and len(lst) > 0:
            return len(lst)
    return None


def extract_node_record_counts(step: dict[str, Any]) -> dict[str, int]:
    """Calculate input, output, created, updated, skipped, failed counts for a step."""
    inputs = step.get("inputs")
    outputs = step.get("outputs")
    note = str(step.get("note") or "").lower()

    in_count = 0
    if isinstance(inputs, list):
        if inputs:
            env_cnt = _extract_item_collection_count(inputs[0])
            in_count = env_cnt if env_cnt is not None else len(inputs)
    elif isinstance(inputs, dict):
        env_cnt = _extract_item_collection_count(inputs)
        in_count = env_cnt if env_cnt is not None else (1 if inputs else 0)

    out_count = 0
    created_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    if step.get("status") in ("error", "failed"):
        failed_count = max(in_count, 1)

    items_list = None
    if isinstance(outputs, list):
        items_list = outputs
    elif isinstance(outputs, dict):
        if "items" in outputs and isinstance(outputs["items"], list):
            items_list = outputs["items"]
        elif "main" in outputs and isinstance(outputs["main"], list):
            items_list = outputs["main"]
        else:
            env_cnt = _extract_item_collection_count(outputs)
            out_count = env_cnt if env_cnt is not None else (1 if outputs else 0)

    if items_list is not None:
        if items_list:
            env_cnt = _extract_item_collection_count(items_list[0])
            out_count = env_cnt if env_cnt is not None else len(items_list)
        else:
            out_count = 0

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
            last_node = nodes[-1] if nodes else None
            if last_node and last_node != data_source_node:
                lt = str(last_node.get("type") or "").lower()
                if lt in ("code", "python_code", "javascript_code", "function"):
                    destination_connector = "code"

    if destination_connector in DATA_SOURCE_TYPES or "data_load" in str(destination_connector):
        destination_connector = "flowsmith_output"

    # If destination_object is still None, try inferring from source_object or workflow name
    if not destination_object and source_object and source_object not in ("file", "payload", "trigger", "event", "data"):
        destination_object = source_object
    elif not destination_object and workflow_name:
        for entity in ("Contact", "Lead", "Account", "Case", "Opportunity", "Customer", "Invoice", "User"):
            if entity.lower() in workflow_name.lower():
                destination_object = entity
                break

    if (not source_object or source_object in ("file", "payload", "trigger", "event", "data")) and destination_object:
        source_object = destination_object
    elif not source_object and workflow_name:
        for entity in ("Contact", "Lead", "Account", "Case", "Opportunity", "Customer", "Invoice", "User"):
            if entity.lower() in workflow_name.lower():
                source_object = entity
                break

    if not destination_object and source_object:
        destination_object = source_object

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


def extract_search_strings(obj: Any, max_chars: int = 4000) -> str:
    """Recursively extract key terms, emails, identifiers, and values from structured JSON/dict/list."""
    if not obj:
        return ""
    terms: list[str] = []

    def _visit(val: Any, depth: int = 0):
        if depth > 5 or sum(len(t) for t in terms) >= max_chars:
            return
        if val is None:
            return
        if isinstance(val, (str, int, float, bool)):
            s = str(val).strip()
            if s and len(s) < 200:
                terms.append(s)
            elif s and len(s) >= 200:
                terms.append(s[:100])
        elif isinstance(val, dict):
            for k, v in list(val.items())[:50]:
                terms.append(str(k))
                _visit(v, depth + 1)
        elif isinstance(val, (list, tuple)):
            items_list = list(val)
            sample_items = items_list[:5] + (items_list[-5:] if len(items_list) > 10 else [])
            for item in sample_items:
                _visit(item, depth + 1)

    try:
        _visit(obj)
    except Exception:
        pass

    return " ".join(terms)[:max_chars]


MONTH_NAMES = frozenset({
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"
})


def format_datetime_variants(dt: datetime | str | None) -> list[str]:
    """Generate all natural language, formal, ordinal, ISO, and human representations for a datetime."""
    if not dt:
        return []
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            try:
                dt = date_parser.parse(dt)
            except Exception:
                return [dt]
    try:
        day = dt.day
        suffix = "th" if 4 <= day <= 20 or 24 <= day <= 30 else ["st", "nd", "rd"][day % 10 - 1] if day % 10 in (1, 2, 3) else "th"
        hour12 = dt.strftime("%I:%M:%S %p").lstrip("0")
        time_lower = hour12.lower()
        month_name = dt.strftime("%B")
        month_abbr = dt.strftime("%b")
        hms = dt.strftime("%H:%M:%S")

        return [
            f"{month_name} {day}{suffix} {dt.year}, {time_lower}",
            f"{month_name} {day}{suffix} {dt.year} {time_lower}",
            f"{month_name} {day}, {dt.year} {hms}",
            f"{month_name} {day}, {dt.year}",
            f"{month_abbr} {day}, {dt.year} {hour12}",
            f"{month_abbr} {day} {dt.year} {hms}",
            f"{month_abbr} {day}, {dt.year}",
            dt.strftime("%Y-%m-%d %H:%M:%S"),
            dt.strftime("%Y-%m-%d"),
            time_lower,
            hms,
            f"{month_name} {day}",
            f"{month_name} {day}{suffix}",
            f"{month_abbr} {day}",
            dt.isoformat(),
        ]
    except Exception:
        return [str(dt)]


def format_human_timestamp(dt: datetime | str | None) -> str:
    """Format a datetime into a standard natural timestamp like 'October 21st 2026, 7:20:20 am'."""
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            try:
                dt = date_parser.parse(dt)
            except Exception:
                return dt
    try:
        day = dt.day
        suffix = "th" if 4 <= day <= 20 or 24 <= day <= 30 else ["st", "nd", "rd"][day % 10 - 1] if day % 10 in (1, 2, 3) else "th"
        hour12 = dt.strftime("%I:%M:%S %p").lstrip("0").lower()
        return f"{dt.strftime('%B')} {day}{suffix} {dt.year}, {hour12}"
    except Exception:
        return str(dt)


def parse_datetime_query(query: str) -> dict[str, Any] | None:
    """Safely parse user search queries that represent natural dates, times, or timestamps."""
    if not query or not query.strip():
        return None
    q = query.strip()
    q_lower = q.lower()

    has_month = any(m in q_lower for m in MONTH_NAMES)
    has_iso = bool(re.search(r"\b\d{4}-\d{2}(-\d{2})?\b", q))
    has_slash_date = bool(re.search(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", q))
    has_time = bool(re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b", q_lower))

    if not (has_month or has_iso or has_slash_date or has_time):
        return None

    clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", q, flags=re.I)
    try:
        dt = date_parser.parse(clean, fuzzy=False)
    except Exception:
        return None

    if clean.isdigit():
        return None

    has_seconds = bool(re.search(r":\d{2}:\d{2}", clean))
    has_year = bool(re.search(r"\b20\d{2}\b", clean)) or has_iso

    if has_seconds and (has_month or has_iso or has_slash_date or has_year):
        precision = "exact_second"
        win = (dt - timedelta(seconds=2), dt + timedelta(seconds=2))
    elif has_time and (has_month or has_iso or has_slash_date or has_year):
        precision = "minute"
        win = (dt.replace(second=0), dt.replace(second=59) + timedelta(seconds=1))
    elif has_month or has_iso or has_slash_date or has_year:
        precision = "day"
        win = (
            dt.replace(hour=0, minute=0, second=0, microsecond=0),
            dt.replace(hour=23, minute=59, second=59, microsecond=999999),
        )
    elif has_seconds:
        precision = "time_only_second"
        win = None
    else:
        precision = "time_only"
        win = None

    return {"dt": dt, "precision": precision, "window": win, "clean": clean}


def matches_datetime(target_dt: datetime | str | None, raw_term: str, parsed: dict[str, Any] | None = None) -> bool:
    """Check if a datetime field matches the search query string or parsed datetime range."""
    if not target_dt:
        return False
    if isinstance(target_dt, str):
        try:
            target_dt = datetime.fromisoformat(target_dt.replace("Z", "+00:00"))
        except Exception:
            try:
                target_dt = date_parser.parse(target_dt)
            except Exception:
                return False

    if parsed is None:
        parsed = parse_datetime_query(raw_term)

    variants = format_datetime_variants(target_dt)
    term_lower = raw_term.strip().lower()
    clean_term = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", term_lower)

    if any(term_lower in v.lower() or clean_term in v.lower() for v in variants):
        return True

    if parsed and parsed.get("window"):
        start_w, end_w = parsed["window"]
        if target_dt.tzinfo is not None and start_w.tzinfo is None:
            start_w = start_w.replace(tzinfo=target_dt.tzinfo)
            end_w = end_w.replace(tzinfo=target_dt.tzinfo)
        elif target_dt.tzinfo is None and start_w.tzinfo is not None:
            target_dt = target_dt.replace(tzinfo=start_w.tzinfo)
        if start_w <= target_dt <= end_w:
            return True

    if parsed and parsed.get("precision") in ("time_only_second", "time_only"):
        p_dt = parsed["dt"]
        if p_dt.hour == target_dt.hour and p_dt.minute == target_dt.minute:
            if parsed["precision"] == "time_only_second":
                return abs(p_dt.second - target_dt.second) <= 2
            return True

    return False


def _format_step_match_label(ntitle: str, path: str, key: str, is_output: bool = False) -> str:
    """Format an informative, location-aware label for step inputs and outputs."""
    direction = "Output" if is_output else "Input"
    k_lower = key.lower()
    path_lower = path.lower()
    if k_lower in ("to", "recipient", "recipients") or ("email" in k_lower and "template" not in k_lower):
        return f"Step: {ntitle} › Email Recipient ({path})"
    if k_lower in ("from", "sender"):
        return f"Step: {ntitle} › Email Sender ({path})"
    if k_lower == "subject" or "subject" in path_lower:
        return f"Step: {ntitle} › Email Subject"
    if k_lower in ("body", "html", "text", "message", "content"):
        return f"Step: {ntitle} › Email Content ({direction})"
    if k_lower in ("cc", "bcc", "reply_to"):
        return f"Step: {ntitle} › Email {k_lower.upper()} ({path})"
    return f"Step: {ntitle} › {direction}.{path}"


def build_execution_search_text(
    rec: Any,
    workflow_name: str | None = None,
    user_email: str | None = None,
) -> str:
    """Build a consolidated, lowercase-searchable text index entry for an execution."""
    parts = []

    rec_id = getattr(rec, "id", None) or ""
    if rec_id:
        parts.append(rec_id)

    wf_name = workflow_name or getattr(rec, "workflow_name", None) or ""
    if wf_name:
        parts.append(wf_name)

    wf_id = getattr(rec, "workflow_id", None) or ""
    if wf_id:
        parts.append(wf_id)

    u_email = user_email or getattr(rec, "user_email", None) or ""
    if u_email:
        parts.append(u_email)

    for attr in (
        "trigger",
        "status",
        "source_connector",
        "destination_connector",
        "source_object",
        "destination_object",
        "http_method",
        "api_endpoint",
        "error_summary",
        "error_code",
        "error_type",
        "correlation_id",
        "parent_execution_id",
    ):
        v = getattr(rec, attr, None)
        if v:
            parts.append(str(v))

    # Timestamp indexing across human, ordinal, ISO, and natural date variations
    if getattr(rec, "started_at", None):
        parts.extend(format_datetime_variants(rec.started_at))
    if getattr(rec, "finished_at", None):
        parts.extend(format_datetime_variants(rec.finished_at))

    sc = getattr(rec, "http_status_code", None)
    if sc:
        parts.append(str(sc))

    err = getattr(rec, "error", None)
    if err:
        parts.append(extract_search_strings(err, max_chars=1000))

    pause = getattr(rec, "pause_state", None)
    if pause:
        parts.append(extract_search_strings(pause, max_chars=500))

    td = getattr(rec, "trigger_data", None)
    if td:
        parts.append(extract_search_strings(td, max_chars=2000))

    tr = getattr(rec, "trace", None)
    if tr and isinstance(tr, list):
        for step in tr:
            if isinstance(step, dict):
                parts.append(str(step.get("node_id") or ""))
                parts.append(str(step.get("node_title") or ""))
                parts.append(str(step.get("node_type") or ""))
                if step.get("started_at"):
                    parts.extend(format_datetime_variants(step["started_at"]))
                if step.get("error"):
                    parts.append(extract_search_strings(step["error"], max_chars=500))
                if step.get("inputs"):
                    parts.append(extract_search_strings(step["inputs"], max_chars=1000))
                if step.get("outputs"):
                    parts.append(extract_search_strings(step["outputs"], max_chars=1500))
    elif getattr(rec, "results", None):
        parts.append(extract_search_strings(rec.results, max_chars=2000))

    return " | ".join(p for p in parts if p)


def find_structured_snippet(data: Any, term: str, max_len: int = 140) -> str | None:
    """Find a key or value in data containing `term` and return a human-readable snippet."""
    if not data or not term:
        return None
    term_lower = term.lower()
    matches: list[str] = []

    def _walk(obj: Any, path: str = "", depth: int = 0):
        if len(matches) >= 2 or depth > 6:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_str = str(k)
                if term_lower in k_str.lower():
                    matches.append(f"{k_str}: {str(v)[:40]}")
                if isinstance(v, (str, int, float, bool)):
                    v_str = str(v)
                    if term_lower in v_str.lower():
                        snippet = f'{k_str}: "{v_str}"'
                        ctx_val = obj.get("Email") or obj.get("email") or obj.get("name") or obj.get("FirstName") or obj.get("id")
                        if ctx_val and str(ctx_val) != v_str:
                            snippet += f" ({ctx_val})"
                        matches.append(snippet)
                elif isinstance(v, (dict, list)):
                    _walk(v, f"{path}.{k_str}" if path else k_str, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj[:100]):
                _walk(item, f"{path}[{idx}]", depth + 1)
                if len(matches) >= 2:
                    break

    try:
        _walk(data)
    except Exception:
        pass

    if matches:
        return " | ".join(matches)[:max_len]

    s = str(data)
    idx = s.lower().find(term_lower)
    if idx != -1:
        start = max(0, idx - 30)
        end = min(len(s), idx + len(term) + 40)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(s) else ""
        return prefix + s[start:end].strip() + suffix
    return None


def find_all_json_matches(data: Any, term: str, max_depth: int = 8, max_matches: int = 20) -> list[dict[str, Any]]:
    """Recursively search any nested dict or list for keys or values matching term."""
    if not data or not term:
        return []
    term_lower = term.lower()
    results: list[dict[str, Any]] = []

    def _walk(obj: Any, path: str = "", depth: int = 0):
        if len(results) >= max_matches or depth > max_depth:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_str = str(k)
                curr_path = f"{path}.{k_str}" if path else k_str
                # Check key match
                if term_lower in k_str.lower():
                    results.append({
                        "path": curr_path,
                        "key": k_str,
                        "value": str(v)[:80] if v is not None else "",
                        "snippet": f"{k_str}: {str(v)[:60]}",
                        "type": "key",
                    })
                # Check value match
                if isinstance(v, (str, int, float, bool)):
                    v_str = str(v)
                    if term_lower in v_str.lower():
                        results.append({
                            "path": curr_path,
                            "key": k_str,
                            "value": v_str[:120],
                            "snippet": f'{k_str}: "{v_str[:80]}"',
                            "type": "value",
                        })
                elif isinstance(v, (dict, list)):
                    _walk(v, curr_path, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj[:100]):
                curr_path = f"{path}[{idx}]"
                if isinstance(item, (str, int, float, bool)):
                    item_str = str(item)
                    if term_lower in item_str.lower():
                        results.append({
                            "path": curr_path,
                            "key": f"[{idx}]",
                            "value": item_str[:120],
                            "snippet": f'[{idx}]: "{item_str[:80]}"',
                            "type": "value",
                        })
                elif isinstance(item, (dict, list)):
                    _walk(item, curr_path, depth + 1)

    try:
        _walk(data)
    except Exception:
        pass
    return results


def extract_execution_search_matches(
    rec: Any,
    search_term: str,
    *,
    workflow_name: str | None = None,
    user_email: str | None = None,
    db: Session | None = None,
    max_matches: int = 12,
    preloaded_staged: list[Any] | None = None,
    preloaded_api_reqs: list[Any] | None = None,
    preloaded_errors: list[Any] | None = None,
    preloaded_steps: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract prioritized structured match descriptors for search highlighting and deep-linking."""
    if not search_term or not search_term.strip():
        return []

    term = search_term.strip()
    term_lower = term.lower()
    parsed_date = parse_datetime_query(term)
    matches: list[dict[str, Any]] = []
    seen_snippets: set[str] = set()

    def _add_match(
        mtype: str,
        label: str,
        snippet: str | None,
        node_id: str | None = None,
        request_id: str | None = None,
        workflow_id: str | None = None,
        record_id: str | None = None,
        target: str = "execution",
        category: str | None = None,
        field_name: str | None = None,
        field_value: str | None = None,
    ):
        if not snippet or snippet in seen_snippets:
            return
        if len(matches) >= max_matches:
            return
        seen_snippets.add(snippet)
        url = f"/executions/{getattr(rec, 'id', '')}"
        if target == "timeline" and node_id:
            url += f"?tab=timeline&node={node_id}&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "timeline":
            url += f"?tab=timeline&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "requests" and request_id:
            url += f"?tab=requests&request_id={request_id}&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "requests":
            url += f"?tab=requests&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "steps" and node_id:
            url += f"?tab=steps&node={node_id}&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "steps" and record_id:
            url += f"?tab=steps&record_id={record_id}&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "steps":
            url += f"?tab=steps&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "trace":
            url += f"?tab=trace&search={term}"
            if field_name:
                url += f"&highlight={field_name}"
        elif target == "workflow" and workflow_id:
            url = f"/workflows/{workflow_id}"

        if not category:
            if mtype in ("node", "input", "output", "step", "step_time"):
                category = "steps"
            elif mtype in ("error", "error_code", "error_type"):
                category = "errors"
            elif mtype in ("staged_record", "record", "record_time"):
                category = "records"
            elif mtype in ("api", "api_request", "api_time"):
                category = "api_requests"
            elif mtype in ("trigger", "payload", "result"):
                category = "payloads"
            else:
                category = "metadata"

        matches.append({
            "type": mtype,
            "label": label,
            "snippet": snippet,
            "node_id": node_id,
            "request_id": request_id,
            "workflow_id": workflow_id,
            "record_id": record_id,
            "target": target,
            "category": category,
            "field_name": field_name or mtype,
            "field_value": field_value,
            "url": url,
        })

    # 1. Execution ID
    rec_id = getattr(rec, "id", "") or ""
    if term_lower in rec_id.lower():
        _add_match("id", "Execution ID", rec_id, target="execution", category="metadata", field_name="id", field_value=rec_id)

    # 2. Workflow Name & ID
    wf_name = workflow_name or getattr(rec, "workflow_name", "") or ""
    rec_wf_id = getattr(rec, "workflow_id", "") or ""
    if wf_name and term_lower in wf_name.lower():
        _add_match("workflow", "Workflow", wf_name, workflow_id=rec_wf_id, target="workflow", category="metadata", field_name="workflow_name", field_value=wf_name)
    elif rec_wf_id and term_lower in rec_wf_id.lower():
        _add_match("workflow", "Workflow ID", rec_wf_id, workflow_id=rec_wf_id, target="workflow", category="metadata", field_name="workflow_id", field_value=rec_wf_id)

    # 3. Execution Timestamps (e.g. "October 21st 2026, 7:20:20 am", "Oct 21, 2026", "2026-10-21")
    rec_start = getattr(rec, "started_at", None)
    if rec_start and matches_datetime(rec_start, term, parsed=parsed_date):
        human_start = format_human_timestamp(rec_start)
        _add_match(
            "started_at",
            "Timeline › Execution Started",
            f"Execution started at {human_start}",
            target="timeline",
            category="metadata",
            field_name="started_at",
            field_value=human_start,
        )

    rec_finish = getattr(rec, "finished_at", None)
    if rec_finish and matches_datetime(rec_finish, term, parsed=parsed_date):
        human_finish = format_human_timestamp(rec_finish)
        dur = getattr(rec, "duration_ms", None)
        dur_str = f" (Duration: {round(dur)}ms)" if dur is not None else ""
        _add_match(
            "finished_at",
            "Timeline › Execution Finished",
            f"Execution finished at {human_finish}{dur_str}",
            target="timeline",
            category="metadata",
            field_name="finished_at",
            field_value=human_finish,
        )

    # 4. User / Email
    u_email = user_email or getattr(rec, "user_email", "") or ""
    if u_email and term_lower in u_email.lower():
        _add_match("user", "User Email", u_email, target="execution", category="metadata", field_name="email", field_value=u_email)

    # 5. Status & Trigger
    status_val = getattr(rec, "status", "") or ""
    if status_val and term_lower in status_val.lower():
        _add_match("status", f"Status: {status_val.upper()}", f"Execution status: {status_val}", target="timeline", category="metadata", field_name="status", field_value=status_val)

    trigger_val = getattr(rec, "trigger", "") or ""
    if trigger_val and term_lower in trigger_val.lower():
        _add_match("trigger", f"Trigger: {trigger_val}", f"Trigger type: {trigger_val}", target="timeline", category="metadata", field_name="trigger", field_value=trigger_val)

    # 6. Connectors & Objects
    src_c = getattr(rec, "source_connector", "") or ""
    dst_c = getattr(rec, "destination_connector", "") or ""
    if src_c and term_lower in src_c.lower():
        _add_match("connector", f"Source: {src_c}", f"Source connector: {src_c}", target="execution", category="metadata", field_name="source_connector", field_value=src_c)
    if dst_c and term_lower in dst_c.lower():
        _add_match("connector", f"Destination: {dst_c}", f"Destination connector: {dst_c}", target="execution", category="metadata", field_name="destination_connector", field_value=dst_c)

    src_o = getattr(rec, "source_object", "") or ""
    dst_o = getattr(rec, "destination_object", "") or ""
    if (src_o and term_lower in src_o.lower()) or (dst_o and term_lower in dst_o.lower()):
        _add_match("object", "Entity Object", f"{src_o or '—'} → {dst_o or '—'}", target="execution", category="metadata", field_name="object", field_value=f"{src_o} -> {dst_o}")

    # 7. HTTP Endpoint & Method
    api_ep = getattr(rec, "api_endpoint", "") or ""
    http_m = getattr(rec, "http_method", "") or ""
    http_sc = getattr(rec, "http_status_code", None)
    if (api_ep and term_lower in api_ep.lower()) or (http_m and term_lower in http_m.lower()):
        _add_match("api", "API Call", f"{http_m} {api_ep} ({http_sc or ''})".strip(), target="requests", category="api_requests", field_name="endpoint", field_value=api_ep)
    elif http_sc and str(http_sc) == term:
        _add_match("api", "HTTP Status", f"HTTP {http_sc} ({http_m or 'POST'})", target="requests", category="api_requests", field_name="status_code", field_value=str(http_sc))

    # 8. Error details
    err_sum = getattr(rec, "error_summary", "") or ""
    if err_sum and term_lower in err_sum.lower():
        _add_match("error", "Error Diagnostic", err_sum, target="timeline", category="errors", field_name="error_summary", field_value=err_sum)
    err_code = getattr(rec, "error_code", "") or ""
    if err_code and term_lower in err_code.lower():
        _add_match("error", f"Error Code: {err_code}", err_code, target="timeline", category="errors", field_name="error_code", field_value=err_code)
    err_type = getattr(rec, "error_type", "") or ""
    if err_type and term_lower in err_type.lower():
        _add_match("error", f"Error Category: {err_type}", err_type, target="timeline", category="errors", field_name="error_type", field_value=err_type)
    err_obj = getattr(rec, "error", None)
    if err_obj and not err_sum:
        err_snip = find_structured_snippet(err_obj, term)
        if err_snip:
            _add_match("error", "Error Details", err_snip, target="timeline", category="errors", field_name="error_details", field_value=err_snip)

    # 9. Trace steps (Nodes, inputs, outputs, step errors, mail payloads)
    trace = getattr(rec, "trace", None) or []
    if isinstance(trace, list):
        for step in trace:
            if not isinstance(step, dict):
                continue
            nid = step.get("node_id") or ""
            ntitle = step.get("node_title") or nid
            ntype = step.get("node_type") or ""

            # Check node title / type / id
            if term_lower in ntitle.lower() or term_lower in nid.lower() or term_lower in ntype.lower():
                _add_match("node", f"Step: {ntitle}", f"{ntitle} ({ntype})", node_id=nid, target="timeline", category="steps", field_name="node_title", field_value=ntitle)

            # Check step timestamp
            step_start = step.get("started_at")
            if step_start and matches_datetime(step_start, term, parsed=parsed_date):
                human_step = format_human_timestamp(step_start)
                _add_match(
                    "step_time",
                    f"Step: {ntitle} › Started At",
                    f"{ntitle} ran at {human_step}",
                    node_id=nid,
                    target="timeline",
                    category="steps",
                    field_name="started_at",
                    field_value=human_step,
                )

            # Check node inputs (deep JSON match, highlighting emails and payloads)
            if step.get("inputs"):
                in_matches = find_all_json_matches(step["inputs"], term, max_matches=2)
                for im in in_matches:
                    step_lbl = _format_step_match_label(ntitle, im["path"], im["key"], is_output=False)
                    _add_match("input", step_lbl, im["snippet"], node_id=nid, target="timeline", category="steps", field_name=im["key"], field_value=im["value"])
                if not in_matches:
                    in_snip = find_structured_snippet(step["inputs"], term)
                    if in_snip:
                        _add_match("input", f"Input ({ntitle})", in_snip, node_id=nid, target="timeline", category="steps")

            # Check node outputs (deep JSON match, highlighting emails and payloads)
            if step.get("outputs"):
                out_matches = find_all_json_matches(step["outputs"], term, max_matches=3)
                for om in out_matches:
                    step_lbl = _format_step_match_label(ntitle, om["path"], om["key"], is_output=True)
                    _add_match("output", step_lbl, om["snippet"], node_id=nid, target="timeline", category="steps", field_name=om["key"], field_value=om["value"])
                if not out_matches:
                    out_snip = find_structured_snippet(step["outputs"], term)
                    if out_snip:
                        _add_match("output", f"Output ({ntitle})", out_snip, node_id=nid, target="timeline", category="steps")

            # Check node error
            if step.get("error"):
                step_err_snip = find_structured_snippet(step["error"], term)
                if step_err_snip:
                    _add_match("error", f"Node Error ({ntitle})", step_err_snip, node_id=nid, target="timeline", category="errors")

    # 9b. ExecutionStep database records (when trace is empty/deferred or preloaded)
    if (preloaded_steps is not None or (db and rec_id)) and len(matches) < max_matches:
        try:
            db_steps = preloaded_steps
            if db_steps is None and db and rec_id:
                from app.models.monitoring_telemetry import ExecutionStep
                from sqlalchemy import select, or_, cast, String
                step_stmt = select(ExecutionStep).where(
                    ExecutionStep.execution_id == rec_id,
                    or_(
                        ExecutionStep.step_name.ilike(f"%{term}%"),
                        ExecutionStep.node_id.ilike(f"%{term}%"),
                        ExecutionStep.node_type.ilike(f"%{term}%"),
                        ExecutionStep.error_message.ilike(f"%{term}%"),
                        cast(ExecutionStep.inputs, String).ilike(f"%{term}%"),
                        cast(ExecutionStep.outputs, String).ilike(f"%{term}%"),
                    ),
                ).limit(5)
                db_steps = db.scalars(step_stmt).all()
            if db_steps:
                for estep in db_steps:
                    snid = estep.node_id or ""
                    sname = estep.step_name or snid or "Step"
                    # Check node name/id
                    if term_lower in sname.lower() or term_lower in snid.lower():
                        _add_match("node", f"Step: {sname}", f"{sname} ({estep.node_type or 'step'})", node_id=snid, target="steps", category="steps", field_name="step_name", field_value=sname)
                    # Check inputs (deep JSON match, highlighting emails and payloads)
                    if estep.inputs:
                        in_m = find_all_json_matches(estep.inputs, term, max_matches=2)
                        for inm in in_m:
                            lbl = _format_step_match_label(sname, inm["path"], inm["key"], is_output=False)
                            _add_match("input", lbl, inm["snippet"], node_id=snid, target="steps", category="steps", field_name=inm["key"], field_value=inm["value"])
                    # Check outputs
                    if estep.outputs:
                        out_m = find_all_json_matches(estep.outputs, term, max_matches=2)
                        for outm in out_m:
                            lbl = _format_step_match_label(sname, outm["path"], outm["key"], is_output=True)
                            _add_match("output", lbl, outm["snippet"], node_id=snid, target="steps", category="steps", field_name=outm["key"], field_value=outm["value"])
                    # Check error
                    if estep.error_message and term_lower in estep.error_message.lower():
                        _add_match("error", f"Step: {sname} › Error", estep.error_message, node_id=snid, target="steps", category="errors", field_name="error_message", field_value=estep.error_message)
                    # Check timestamp
                    if estep.started_at and matches_datetime(estep.started_at, term, parsed=parsed_date):
                        h_time = format_human_timestamp(estep.started_at)
                        _add_match("step_time", f"Step: {sname} › Started At", f"{sname} ran at {h_time}", node_id=snid, target="steps", category="steps", field_name="started_at", field_value=h_time)
        except Exception:
            pass

    # 10. Trigger data (Inputs / Webhooks / Incoming Mails)
    td = getattr(rec, "trigger_data", None)
    if td:
        td_matches = find_all_json_matches(td, term, max_matches=2)
        for tm in td_matches:
            k_lower = tm["key"].lower()
            if "mail" in k_lower or "email" in k_lower or k_lower in ("to", "from", "recipient", "sender"):
                t_lbl = f"Trigger Payload › Email Field ({tm['path']})"
            else:
                t_lbl = f"Trigger Payload › {tm['path']}"
            _add_match("trigger", t_lbl, tm["snippet"], target="timeline", category="payloads", field_name=tm["key"], field_value=tm["value"])
        if not td_matches:
            td_snip = find_structured_snippet(td, term)
            if td_snip:
                _add_match("input", "Trigger Input", td_snip, target="timeline", category="payloads")

    # 11. Results (Outputs / Response Data)
    res = getattr(rec, "results", None)
    if res and not trace:
        res_matches = find_all_json_matches(res, term, max_matches=2)
        for rm in res_matches:
            _add_match("output", f"Execution Output › {rm['path']}", rm["snippet"], target="timeline", category="payloads", field_name=rm["key"], field_value=rm["value"])
        if not res_matches:
            res_snip = find_structured_snippet(res, term)
            if res_snip:
                _add_match("output", "Execution Output", res_snip, target="timeline", category="payloads")

    # 12. Staged contact records (CSV, Data Load, Salesforce Bulk, Record Mails & Addresses)
    if (preloaded_staged is not None or (db and rec_id)) and len(matches) < max_matches:
        try:
            staged_rows = preloaded_staged
            if staged_rows is None and db and rec_id:
                from app.models.staged_record import StagedContactRecord
                from sqlalchemy import select, or_, cast, String
                staged_stmt = select(StagedContactRecord).where(
                    StagedContactRecord.execution_id == rec_id,
                    or_(
                        StagedContactRecord.first_name.ilike(f"%{term}%"),
                        StagedContactRecord.last_name.ilike(f"%{term}%"),
                        StagedContactRecord.email.ilike(f"%{term}%"),
                        StagedContactRecord.phone.ilike(f"%{term}%"),
                        StagedContactRecord.department.ilike(f"%{term}%"),
                        StagedContactRecord.title.ilike(f"%{term}%"),
                        StagedContactRecord.mailing_street.ilike(f"%{term}%"),
                        StagedContactRecord.mailing_city.ilike(f"%{term}%"),
                        StagedContactRecord.mailing_state.ilike(f"%{term}%"),
                        StagedContactRecord.mailing_postal_code.ilike(f"%{term}%"),
                        StagedContactRecord.mailing_country.ilike(f"%{term}%"),
                        StagedContactRecord.description.ilike(f"%{term}%"),
                        StagedContactRecord.status.ilike(f"%{term}%"),
                        StagedContactRecord.error_message.ilike(f"%{term}%"),
                        StagedContactRecord.salesforce_id.ilike(f"%{term}%"),
                        cast(StagedContactRecord.raw_data, String).ilike(f"%{term}%"),
                    )
                ).limit(5)
                staged_rows = db.scalars(staged_stmt).all()
            if staged_rows:
                for srow in staged_rows[:5]:
                    row_num = srow.row_number
                    # Email match (record mails)
                    if srow.email and term_lower in srow.email.lower():
                        _add_match(
                            "staged_record",
                            f"Record #{row_num} › Email",
                            f"Row #{row_num}: {srow.first_name or ''} {srow.last_name or ''} <{srow.email}>".strip(),
                            record_id=srow.id,
                            target="steps",
                            category="records",
                            field_name="email",
                            field_value=srow.email,
                        )
                    # Mailing Address match
                    for mf in ("mailing_street", "mailing_city", "mailing_state", "mailing_postal_code", "mailing_country"):
                        mv = getattr(srow, mf, None)
                        if mv and term_lower in str(mv).lower():
                            parts_list = [p for p in (srow.mailing_street, srow.mailing_city, srow.mailing_state, srow.mailing_postal_code, srow.mailing_country) if p]
                            _add_match(
                                "staged_record",
                                f"Record #{row_num} › Mailing Address",
                                f"Row #{row_num} ({mf}): {', '.join(parts_list)}",
                                record_id=srow.id,
                                target="steps",
                                category="records",
                                field_name=mf,
                                field_value=str(mv),
                            )
                            break
                    # Name, Phone, Dept, Title, Salesforce ID, Status
                    for cf in ("first_name", "last_name", "phone", "department", "title", "description", "salesforce_id", "status"):
                        cv = getattr(srow, cf, None)
                        if cv and term_lower in str(cv).lower():
                            _add_match(
                                "staged_record",
                                f"Record #{row_num} › {cf.replace('_', ' ').title()}",
                                f"Row #{row_num} {cf}: {cv}",
                                record_id=srow.id,
                                target="steps",
                                category="records",
                                field_name=cf,
                                field_value=str(cv),
                            )
                            break
                    # Error message
                    if srow.error_message and term_lower in srow.error_message.lower():
                        _add_match(
                            "staged_record",
                            f"Record #{row_num} › Ingestion Error",
                            f"Row #{row_num} Error: {srow.error_message}",
                            record_id=srow.id,
                            target="steps",
                            category="records",
                            field_name="error_message",
                            field_value=srow.error_message,
                        )
                    # Created timestamp
                    if srow.created_at and matches_datetime(srow.created_at, term, parsed=parsed_date):
                        h_time = format_human_timestamp(srow.created_at)
                        _add_match(
                            "record_time",
                            f"Record #{row_num} › Ingested At",
                            f"Row #{row_num} ingested at {h_time}",
                            record_id=srow.id,
                            target="steps",
                            category="records",
                            field_name="created_at",
                            field_value=h_time,
                        )
                    # Deep raw_data match
                    if srow.raw_data:
                        raw_matches = find_all_json_matches(srow.raw_data, term, max_matches=2)
                        for rm in raw_matches:
                            _add_match(
                                "staged_record",
                                f"Record #{row_num} › Raw Data.{rm['path']}",
                                f"Row #{row_num}: {rm['snippet']}",
                                record_id=srow.id,
                                target="steps",
                                category="records",
                                field_name=rm["key"],
                                field_value=rm["value"],
                            )
        except Exception:
            pass

    # 13. Outbound API Requests logs (HTTP methods, endpoints, payloads, headers, emails)
    if (preloaded_api_reqs is not None or (db and rec_id)) and len(matches) < max_matches:
        try:
            matching_reqs = preloaded_api_reqs
            if matching_reqs is None and db and rec_id:
                from app.models.monitoring_telemetry import ApiRequestTelemetry
                from sqlalchemy import select, or_, cast, String
                req_stmt = select(ApiRequestTelemetry).where(
                    ApiRequestTelemetry.execution_id == rec_id,
                    or_(
                        ApiRequestTelemetry.endpoint_url.ilike(f"%{term}%"),
                        ApiRequestTelemetry.connector_name.ilike(f"%{term}%"),
                        ApiRequestTelemetry.error_message.ilike(f"%{term}%"),
                        cast(ApiRequestTelemetry.request_payload, String).ilike(f"%{term}%"),
                        cast(ApiRequestTelemetry.response_payload, String).ilike(f"%{term}%"),
                        cast(ApiRequestTelemetry.request_headers, String).ilike(f"%{term}%"),
                        cast(ApiRequestTelemetry.response_headers, String).ilike(f"%{term}%"),
                        cast(ApiRequestTelemetry.query_params, String).ilike(f"%{term}%"),
                    )
                ).limit(4)
                matching_reqs = db.scalars(req_stmt).all()
            if matching_reqs:
                for mreq in matching_reqs[:4]:
                    prefix = f"API: {mreq.http_method} {mreq.connector_name or ''}".strip()
                    # URL match
                    if term_lower in mreq.endpoint_url.lower():
                        _add_match(
                            "api_request",
                            f"{prefix} › Endpoint URL",
                            mreq.endpoint_url,
                            request_id=mreq.id,
                            node_id=mreq.node_id,
                            target="requests",
                            category="api_requests",
                            field_name="endpoint_url",
                            field_value=mreq.endpoint_url,
                        )
                    # Request payload deep match
                    if mreq.request_payload:
                        p_matches = find_all_json_matches(mreq.request_payload, term, max_matches=2)
                        for pm in p_matches:
                            _add_match(
                                "api_request",
                                f"{prefix} › Request Payload.{pm['path']}",
                                pm["snippet"],
                                request_id=mreq.id,
                                node_id=mreq.node_id,
                                target="requests",
                                category="api_requests",
                                field_name=pm["key"],
                                field_value=pm["value"],
                            )
                    # Response payload deep match
                    if mreq.response_payload:
                        rp_matches = find_all_json_matches(mreq.response_payload, term, max_matches=2)
                        for rpm in rp_matches:
                            _add_match(
                                "api_request",
                                f"{prefix} › Response Body.{rpm['path']}",
                                rpm["snippet"],
                                request_id=mreq.id,
                                node_id=mreq.node_id,
                                target="requests",
                                category="api_requests",
                                field_name=rpm["key"],
                                field_value=rpm["value"],
                            )
                    # Headers match
                    if mreq.request_headers:
                        h_matches = find_all_json_matches(mreq.request_headers, term, max_matches=1)
                        for hm in h_matches:
                            _add_match(
                                "api_request",
                                f"{prefix} › Header ({hm['key']})",
                                hm["snippet"],
                                request_id=mreq.id,
                                node_id=mreq.node_id,
                                target="requests",
                                category="api_requests",
                                field_name=hm["key"],
                                field_value=hm["value"],
                            )
                    # Timestamp match
                    if mreq.request_timestamp and matches_datetime(mreq.request_timestamp, term, parsed=parsed_date):
                        h_req = format_human_timestamp(mreq.request_timestamp)
                        _add_match(
                            "api_time",
                            f"{prefix} › Sent At",
                            f"API request sent at {h_req}",
                            request_id=mreq.id,
                            node_id=mreq.node_id,
                            target="requests",
                            category="api_requests",
                            field_name="request_timestamp",
                            field_value=h_req,
                        )
        except Exception:
            pass

    # 14. Error events - batch preloaded or fallback
    if (preloaded_errors is not None or (db and rec_id)) and len(matches) < max_matches:
        try:
            matching_errs = preloaded_errors
            if matching_errs is None and db and rec_id:
                from app.models.error_event import ErrorEvent
                from sqlalchemy import select, or_
                err_ev_stmt = select(ErrorEvent).where(
                    ErrorEvent.execution_id == rec_id,
                    or_(
                        ErrorEvent.message.ilike(f"%{term}%"),
                        ErrorEvent.title.ilike(f"%{term}%"),
                        ErrorEvent.code.ilike(f"%{term}%"),
                    )
                ).limit(2)
                matching_errs = db.scalars(err_ev_stmt).all()
            if matching_errs:
                for err_ev in matching_errs[:2]:
                    _add_match(
                        "error",
                        f"Error Event: {err_ev.title}",
                        err_ev.message[:120],
                        target="timeline",
                        category="errors",
                        field_name="error_event",
                        field_value=err_ev.message,
                    )
        except Exception:
            pass

    return matches[:max_matches]


def search_universal_executions(
    db: Session,
    user: Any,
    *,
    query: str,
    category: str = "all",
    workflow_id: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Execute a YouTube-like deep universal search across all execution logs and monitoring details."""
    from app.api.access import accessible_ids
    from app.models.workflow import WorkflowRecord
    from app.models.user import User
    from app.models.monitoring_telemetry import ExecutionStep, ApiRequestTelemetry
    from app.models.staged_record import StagedContactRecord
    from app.models.error_event import ErrorEvent
    from sqlalchemy import select, or_, cast, String

    page = max(1, page)
    page_size = max(1, min(100, page_size))

    empty_facets = {
        "all": 0,
        "steps": 0,
        "errors": 0,
        "records": 0,
        "api_requests": 0,
        "payloads": 0,
        "metadata": 0,
    }

    if not query or not query.strip():
        return {
            "query": "",
            "category": category,
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "results": [],
            "facets": empty_facets,
        }

    accessible_wf_ids = accessible_ids(db, user)
    if not accessible_wf_ids:
        return {
            "query": query,
            "category": category,
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "results": [],
            "facets": empty_facets,
        }

    term = query.strip()
    sterm = f"%{term}%"
    words = [w.strip() for w in term.split() if len(w.strip()) >= 2]

    # 1. Collect candidate workflow IDs
    matching_wf_ids = [
        wid for (wid,) in db.execute(
            select(WorkflowRecord.id).where(
                WorkflowRecord.id.in_(accessible_wf_ids),
                or_(
                    WorkflowRecord.name.ilike(sterm),
                    WorkflowRecord.description.ilike(sterm),
                )
            )
        ).all()
    ]

    # 2. Collect candidate user IDs
    matching_user_ids = [
        uid for (uid,) in db.execute(
            select(User.id).where(User.email.ilike(sterm))
        ).all()
    ]

    parsed_date = parse_datetime_query(term)
    date_win = parsed_date.get("window") if parsed_date else None

    # 3. ExecutionStep candidate IDs (only if category needs steps or payloads or all)
    matching_step_exec_ids = []
    step_preds = [
        ExecutionStep.step_name.ilike(sterm),
        ExecutionStep.node_id.ilike(sterm),
        ExecutionStep.node_type.ilike(sterm),
        ExecutionStep.error_message.ilike(sterm),
        cast(ExecutionStep.inputs, String).ilike(sterm),
        cast(ExecutionStep.outputs, String).ilike(sterm),
        cast(ExecutionStep.error_details, String).ilike(sterm),
    ]
    for w in words[:3]:
        step_preds.append(cast(ExecutionStep.inputs, String).ilike(f"%{w}%"))
        step_preds.append(cast(ExecutionStep.outputs, String).ilike(f"%{w}%"))

    if category in ("all", "steps", "payloads"):
        matching_step_exec_ids = [
            eid for (eid,) in db.execute(
                select(ExecutionStep.execution_id)
                .where(or_(*step_preds))
                .distinct()
                .limit(300)
            ).all()
        ]
        if date_win:
            w_start, w_end = date_win
            date_step_ids = [
                eid for (eid,) in db.execute(
                    select(ExecutionStep.execution_id)
                    .where(ExecutionStep.started_at.between(w_start, w_end))
                    .distinct()
                    .limit(200)
                ).all()
            ]
            matching_step_exec_ids.extend(date_step_ids)

    # 4. ApiRequestTelemetry candidate IDs (only if category needs api_requests or all)
    matching_req_exec_ids = []
    api_preds = [
        ApiRequestTelemetry.endpoint_url.ilike(sterm),
        ApiRequestTelemetry.connector_name.ilike(sterm),
        ApiRequestTelemetry.error_message.ilike(sterm),
        cast(ApiRequestTelemetry.request_payload, String).ilike(sterm),
        cast(ApiRequestTelemetry.response_payload, String).ilike(sterm),
        cast(ApiRequestTelemetry.request_headers, String).ilike(sterm),
        cast(ApiRequestTelemetry.response_headers, String).ilike(sterm),
        cast(ApiRequestTelemetry.query_params, String).ilike(sterm),
    ]
    for w in words[:3]:
        api_preds.append(cast(ApiRequestTelemetry.request_payload, String).ilike(f"%{w}%"))
        api_preds.append(cast(ApiRequestTelemetry.response_payload, String).ilike(f"%{w}%"))
        api_preds.append(ApiRequestTelemetry.endpoint_url.ilike(f"%{w}%"))

    if category in ("all", "api_requests"):
        matching_req_exec_ids = [
            eid for (eid,) in db.execute(
                select(ApiRequestTelemetry.execution_id)
                .where(or_(*api_preds))
                .distinct()
                .limit(300)
            ).all()
        ]
        if date_win:
            w_start, w_end = date_win
            date_req_ids = [
                eid for (eid,) in db.execute(
                    select(ApiRequestTelemetry.execution_id)
                    .where(ApiRequestTelemetry.request_timestamp.between(w_start, w_end))
                    .distinct()
                    .limit(200)
                ).all()
            ]
            matching_req_exec_ids.extend(date_req_ids)

    # 5. StagedContactRecord candidate IDs (only if category needs records or all)
    matching_staged_exec_ids = []
    staged_preds = [
        StagedContactRecord.first_name.ilike(sterm),
        StagedContactRecord.last_name.ilike(sterm),
        StagedContactRecord.email.ilike(sterm),
        StagedContactRecord.phone.ilike(sterm),
        StagedContactRecord.department.ilike(sterm),
        StagedContactRecord.title.ilike(sterm),
        StagedContactRecord.mailing_street.ilike(sterm),
        StagedContactRecord.mailing_city.ilike(sterm),
        StagedContactRecord.mailing_state.ilike(sterm),
        StagedContactRecord.mailing_postal_code.ilike(sterm),
        StagedContactRecord.mailing_country.ilike(sterm),
        StagedContactRecord.description.ilike(sterm),
        StagedContactRecord.status.ilike(sterm),
        StagedContactRecord.error_message.ilike(sterm),
        StagedContactRecord.salesforce_id.ilike(sterm),
        cast(StagedContactRecord.raw_data, String).ilike(sterm),
    ]
    for w in words[:3]:
        staged_preds.append(StagedContactRecord.email.ilike(f"%{w}%"))
        staged_preds.append(StagedContactRecord.first_name.ilike(f"%{w}%"))
        staged_preds.append(StagedContactRecord.last_name.ilike(f"%{w}%"))
        staged_preds.append(StagedContactRecord.mailing_street.ilike(f"%{w}%"))
        staged_preds.append(cast(StagedContactRecord.raw_data, String).ilike(f"%{w}%"))

    if category in ("all", "records"):
        matching_staged_exec_ids = [
            eid for (eid,) in db.execute(
                select(StagedContactRecord.execution_id)
                .where(or_(*staged_preds))
                .distinct()
                .limit(300)
            ).all()
        ]
        if date_win:
            w_start, w_end = date_win
            date_staged_ids = [
                eid for (eid,) in db.execute(
                    select(StagedContactRecord.execution_id)
                    .where(StagedContactRecord.created_at.between(w_start, w_end))
                    .distinct()
                    .limit(200)
                ).all()
            ]
            matching_staged_exec_ids.extend(date_staged_ids)

    # 6. ErrorEvent candidate IDs (only if category needs errors or all)
    matching_err_exec_ids = []
    err_preds = [
        ErrorEvent.message.ilike(sterm),
        ErrorEvent.title.ilike(sterm),
        ErrorEvent.code.ilike(sterm),
        ErrorEvent.category.ilike(sterm),
        ErrorEvent.resolution.ilike(sterm),
    ]
    if category in ("all", "errors"):
        matching_err_exec_ids = [
            eid for (eid,) in db.execute(
                select(ErrorEvent.execution_id)
                .where(ErrorEvent.execution_id.isnot(None), or_(*err_preds))
                .distinct()
                .limit(300)
            ).all()
        ]

    # 7. Execution table predicates
    exec_preds: list[Any] = [
        Execution.id.ilike(sterm),
        Execution.source_connector.ilike(sterm),
        Execution.destination_connector.ilike(sterm),
        Execution.source_object.ilike(sterm),
        Execution.destination_object.ilike(sterm),
        Execution.trigger.ilike(sterm),
        Execution.status.ilike(sterm),
        Execution.api_endpoint.ilike(sterm),
        Execution.http_method.ilike(sterm),
        Execution.error_summary.ilike(sterm),
        Execution.error_code.ilike(sterm),
        Execution.error_type.ilike(sterm),
        Execution.correlation_id.ilike(sterm),
        Execution.parent_execution_id.ilike(sterm),
        Execution.search_text.ilike(sterm),
        cast(Execution.error, String).ilike(sterm),
        cast(Execution.trigger_data, String).ilike(sterm),
        cast(Execution.results, String).ilike(sterm),
        cast(Execution.trace, String).ilike(sterm),
        cast(Execution.workflow_data, String).ilike(sterm),
        cast(Execution.started_at, String).ilike(sterm),
        cast(Execution.finished_at, String).ilike(sterm),
    ]

    # Timestamp query matching
    if date_win:
        w_start, w_end = date_win
        exec_preds.append(Execution.started_at.between(w_start, w_end))
        exec_preds.append(Execution.finished_at.between(w_start, w_end))

    if parsed_date and parsed_date.get("dt"):
        iso_d = parsed_date["dt"].strftime("%Y-%m-%d")
        exec_preds.append(cast(Execution.started_at, String).ilike(f"%{iso_d}%"))
        exec_preds.append(cast(Execution.finished_at, String).ilike(f"%{iso_d}%"))

    if parsed_date and parsed_date.get("clean"):
        clean_date_term = f"%{parsed_date['clean']}%"
        exec_preds.append(Execution.search_text.ilike(clean_date_term))

    if term.isdigit() and len(term) == 3:
        try:
            exec_preds.append(Execution.http_status_code == int(term))
        except Exception:
            pass

    for w in words[:3]:
        exec_preds.append(Execution.search_text.ilike(f"%{w}%"))
        exec_preds.append(Execution.id.ilike(f"%{w}%"))
        exec_preds.append(Execution.status.ilike(f"%{w}%"))

    if matching_wf_ids:
        exec_preds.append(Execution.workflow_id.in_(matching_wf_ids))
    if matching_user_ids:
        exec_preds.append(Execution.user_id.in_(matching_user_ids))
    if matching_step_exec_ids:
        exec_preds.append(Execution.id.in_(matching_step_exec_ids))
    if matching_req_exec_ids:
        exec_preds.append(Execution.id.in_(matching_req_exec_ids))
    if matching_staged_exec_ids:
        exec_preds.append(Execution.id.in_(matching_staged_exec_ids))
    if matching_err_exec_ids:
        exec_preds.append(Execution.id.in_(matching_err_exec_ids))

    stmt = (
        select(Execution)
        .where(
            Execution.workflow_id.in_(accessible_wf_ids),
            or_(*exec_preds),
        )
    )

    if workflow_id:
        stmt = stmt.where(Execution.workflow_id == workflow_id)
    if status:
        stmt = stmt.where(Execution.status == status)
    if start_date:
        try:
            stmt = stmt.where(Execution.started_at >= datetime.fromisoformat(start_date.replace("Z", "+00:00")))
        except Exception:
            pass
    if end_date:
        try:
            stmt = stmt.where(Execution.started_at <= datetime.fromisoformat(end_date.replace("Z", "+00:00")))
        except Exception:
            pass

    stmt = stmt.order_by(Execution.started_at.desc()).limit(150)
    recs = db.scalars(stmt).all()

    # Pre-fetch workflow names and user emails
    wf_ids = {r.workflow_id for r in recs if r.workflow_id}
    names = {
        wid: name
        for wid, name in db.execute(
            select(WorkflowRecord.id, WorkflowRecord.name).where(
                WorkflowRecord.id.in_(wf_ids)
            )
        ).all()
    } if wf_ids else {}

    u_ids = {r.user_id for r in recs if r.user_id is not None}
    emails = {
        uid: email
        for uid, email in db.execute(
            select(User.id, User.email).where(
                User.id.in_(u_ids)
            )
        ).all()
    } if u_ids else {}

    # Bulk prefetch related staged records, API requests, and errors to prevent N+1 queries
    from collections import defaultdict

    rec_ids = [r.id for r in recs if r.id]
    staged_by_exec: dict[str, list[Any]] = defaultdict(list)
    api_by_exec: dict[str, list[Any]] = defaultdict(list)
    err_by_exec: dict[str, list[Any]] = defaultdict(list)
    steps_by_exec: dict[str, list[Any]] = defaultdict(list)

    if rec_ids:
        if category in ("all", "steps", "payloads"):
            try:
                from app.models.monitoring_telemetry import ExecutionStep
                step_rows = db.scalars(
                    select(ExecutionStep).where(
                        ExecutionStep.execution_id.in_(rec_ids),
                        or_(*step_preds),
                    ).limit(300)
                ).all()
                for st in step_rows:
                    if st.execution_id:
                        steps_by_exec[st.execution_id].append(st)
            except Exception:
                pass

        if category in ("all", "records"):
            try:
                staged_rows = db.scalars(
                    select(StagedContactRecord).where(
                        StagedContactRecord.execution_id.in_(rec_ids),
                        or_(*staged_preds),
                    ).limit(300)
                ).all()
                for s in staged_rows:
                    if s.execution_id:
                        staged_by_exec[s.execution_id].append(s)
            except Exception:
                pass

        if category in ("all", "api_requests"):
            try:
                req_rows = db.scalars(
                    select(ApiRequestTelemetry).where(
                        ApiRequestTelemetry.execution_id.in_(rec_ids),
                        or_(*api_preds),
                    ).limit(300)
                ).all()
                for r in req_rows:
                    if r.execution_id:
                        api_by_exec[r.execution_id].append(r)
            except Exception:
                pass

        if category in ("all", "errors"):
            try:
                err_rows = db.scalars(
                    select(ErrorEvent).where(
                        ErrorEvent.execution_id.in_(rec_ids),
                        or_(*err_preds),
                    ).limit(300)
                ).all()
                for e in err_rows:
                    if e.execution_id:
                        err_by_exec[e.execution_id].append(e)
            except Exception:
                pass

    all_occurrences = []
    category_counts = {
        "all": 0,
        "steps": 0,
        "errors": 0,
        "records": 0,
        "api_requests": 0,
        "payloads": 0,
        "metadata": 0,
    }

    for rec in recs:
        wf_name = names.get(rec.workflow_id, rec.workflow_id[:8] if rec.workflow_id else "Workflow")
        user_email = emails.get(rec.user_id)
        occ_list = extract_execution_search_matches(
            rec,
            term,
            workflow_name=wf_name,
            user_email=user_email,
            max_matches=12,
            preloaded_staged=staged_by_exec.get(rec.id, []),
            preloaded_api_reqs=api_by_exec.get(rec.id, []),
            preloaded_errors=err_by_exec.get(rec.id, []),
            preloaded_steps=steps_by_exec.get(rec.id, []),
        )

        for occ in occ_list:
            cat = occ.get("category") or "metadata"
            category_counts["all"] += 1
            if cat in category_counts:
                category_counts[cat] += 1
            else:
                category_counts["metadata"] += 1

            dur = rec.duration_ms
            if dur is None and rec.started_at:
                end = rec.finished_at or datetime.now(UTC)
                dur = round((end - rec.started_at).total_seconds() * 1000.0, 1)

            all_occurrences.append({
                "id": f"{rec.id}_{occ.get('type')}_{occ.get('node_id') or occ.get('request_id') or len(all_occurrences)}",
                "execution_id": rec.id,
                "workflow_id": rec.workflow_id,
                "workflow_name": wf_name,
                "status": rec.status,
                "started_at": rec.started_at.isoformat() if rec.started_at else None,
                "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
                "duration_ms": dur,
                "source_connector": rec.source_connector or rec.trigger or "flowsmith_trigger",
                "destination_connector": rec.destination_connector or "flowsmith_output",
                "category": cat,
                "location_badge": occ.get("label") or f"{cat.capitalize()}",
                "location_label": occ.get("label") or f"{cat.capitalize()}",
                "field": occ.get("field_name") or occ.get("type"),
                "matched_field": occ.get("field_name") or occ.get("type"),
                "matched_value": occ.get("field_value"),
                "snippet": occ.get("snippet") or "",
                "matched_text": term,
                "target_tab": occ.get("target") or "timeline",
                "target_node_id": occ.get("node_id"),
                "target_request_id": occ.get("request_id"),
                "target_record_id": occ.get("record_id"),
                "url": occ.get("url") or f"/executions/{rec.id}",
                "deep_link_url": occ.get("url") or f"/executions/{rec.id}",
            })

    # Filter by category if specified and not 'all'
    filtered_results = all_occurrences
    if category and category != "all":
        filtered_results = [o for o in all_occurrences if o.get("category") == category]

    total = len(filtered_results)
    start_idx = (page - 1) * page_size
    paged_results = filtered_results[start_idx : start_idx + page_size]

    return {
        "query": term,
        "category": category,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "results": paged_results,
        "facets": category_counts,
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

        # 2. Timing: separate queue wait from actual execution duration
        started_at = rec.started_at or datetime.now(UTC)
        finished_at = rec.finished_at or datetime.now(UTC)

        if hasattr(result, "duration_ms") and result.duration_ms is not None and result.duration_ms > 0:
            rec.duration_ms = round(float(result.duration_ms), 2)
        else:
            raw_duration_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000.0)
            if getattr(rec, "queue_wait_ms", None):
                rec.duration_ms = round(max(0.0, raw_duration_ms - rec.queue_wait_ms), 2)
            else:
                rec.duration_ms = round(raw_duration_ms, 2)

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
        data_source_read = 0
        first_step_read = 0
        max_batch_count = 0

        step_db_rows: list[ExecutionStep] = []
        node_step_map: dict[str, str] = {}

        for seq, step in enumerate(trace, 1):
            step_id = f"step_{execution_id[-8:]}_{seq}"
            nid = step.get("node_id", f"node_{seq}")
            node_step_map[nid] = step_id
            counts = extract_node_record_counts(step)
            ntype = str(step.get("node_type") or "").lower()

            if seq == 1:
                first_step_read = counts["input_record_count"] or counts["output_record_count"]

            if ntype in DATA_SOURCE_TYPES or "data_load" in ntype or "csv" in ntype:
                data_source_read = max(data_source_read, counts["output_record_count"], counts["input_record_count"])

            max_batch_count = max(max_batch_count, counts["output_record_count"], counts["input_record_count"])

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
        final_read = data_source_read if data_source_read > 0 else first_step_read
        if final_read == 0 and max_batch_count > 0:
            final_read = max_batch_count

        final_processed = total_created + total_updated
        if final_processed < max_batch_count and max_batch_count > 0:
            final_processed = max_batch_count
            total_created = max_batch_count

        rec.records_read = final_read
        rec.records_created = total_created
        rec.records_updated = total_updated
        rec.records_skipped = total_skipped
        rec.records_failed = total_failed
        rec.records_processed = final_processed

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

        # 9. Build consolidated search index
        wf_name = getattr(job, "workflow_name", None) or getattr(rec, "workflow_name", None)
        u_email = getattr(job, "user_email", None) or getattr(rec, "user_email", None)
        rec.search_text = build_execution_search_text(rec, workflow_name=wf_name, user_email=u_email)

        # 10. Batch add to session with layered fallback
        try:
            for s_row in step_db_rows:
                db.merge(s_row)
            for a_row in api_db_rows:
                db.merge(a_row)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(
                "Telemetry batch commit failed for execution %s (%s); retrying with core steps only",
                getattr(rec, "id", "unknown"),
                exc,
            )
            try:
                for s_row in step_db_rows:
                    db.merge(s_row)
                db.commit()
            except Exception as step_exc:
                db.rollback()
                logger.warning(
                    "Telemetry step commit failed for execution %s (%s); saving core execution status",
                    getattr(rec, "id", "unknown"),
                    step_exc,
                )
                try:
                    db.commit()
                except Exception:
                    db.rollback()
    except Exception as exc:
        logger.exception("Failed to finalize telemetry for execution %s: %s", getattr(rec, "id", "unknown"), exc)
        try:
            db.rollback()
        except Exception:
            pass



def backfill_execution_telemetry_metadata(db: Session | None = None) -> int:
    """One-time or startup backfill routine that updates executions missing integration metadata or search text."""
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
                Execution.search_text.is_(None),
                Execution.destination_connector.is_(None),
                Execution.destination_connector == "flowsmith_output",
                Execution.destination_connector.in_(["flowsmith.data_load", "data_load"]),
                Execution.http_status_code.is_(None),
                Execution.source_connector.is_(None),
                Execution.source_connector.in_(["schedule", "cron", "manual"]),
                Execution.source_object.in_(["payload", "trigger", "event", "data"]),
                Execution.records_read <= 1,
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
            if rec.destination_connector in ("flowsmith.data_load", "data_load"):
                rec.source_connector = "data_load"
                rec.destination_connector = meta["destination_connector"] or "flowsmith_output"
                modified = True
            elif not rec.destination_connector or (rec.destination_connector == "flowsmith_output" and meta["destination_connector"] != "flowsmith_output"):
                rec.destination_connector = meta["destination_connector"]
                modified = True

            if not rec.source_connector or (rec.source_connector in ("manual", "schedule", "cron", "flowsmith_trigger") and meta["source_connector"] == "data_load"):
                rec.source_connector = meta["source_connector"]
                modified = True

            if (not rec.source_object or rec.source_object in ("payload", "trigger", "event", "data")) and meta["source_object"]:
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

            # Record count backfill for batch and data load executions
            trace = rec.trace or []
            max_batch = 0
            ds_read = 0
            for s in trace:
                c = extract_node_record_counts(s)
                nt = str(s.get("node_type") or "").lower()
                if nt in DATA_SOURCE_TYPES or "data_load" in nt or "csv" in nt:
                    ds_read = max(ds_read, c["output_record_count"], c["input_record_count"])
                max_batch = max(max_batch, c["output_record_count"], c["input_record_count"])

            if max_batch > 1 and (rec.records_read <= 1 or rec.records_processed <= 3):
                rec.records_read = ds_read if ds_read > 0 else max_batch
                rec.records_processed = max_batch
                rec.records_created = max_batch
                modified = True

            if getattr(rec, "search_text", None) is None:
                rec.search_text = build_execution_search_text(rec, workflow_name=wf_name)
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

