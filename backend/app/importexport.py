"""Workflow import/export (native + external JSON interchange).

``build_export`` wraps a workflow document in a self-describing envelope
(``format: opencode-workflow``) so round-trips are unambiguous.

``parse_import`` accepts three shapes and returns a native workflow
document (dict) ready for the normal ``validate_workflow_payload`` path:

1. The export envelope (``{"format": "opencode-workflow", "workflow": {...}}``)
2. A bare native document (``nodes`` is a list, ``connections`` a list)
3. An external workflow export (``connections`` is a dict keyed by source
   node, positions are ``[x, y]`` arrays).

Conversion is best-effort for the node types this platform ships;
unknown node types are rejected with a readable error listing exactly
what was not understood.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

EXPORT_FORMAT = "opencode-workflow"
EXPORT_VERSION = 1

SENSITIVE_PARAM_KEYS = {
    "auth_token",
    "auth_password",
    "token",
    "password",
    "api_key",
    "secret",
    "client_secret",
    "private_key",
    "access_token",
    "refresh_token",
    "service_account_key",
    "connection_string",
    "database_url",
    "webhook_secret",
    "signing_secret",
    "session_token",
    "oauth_token",
    "api_token",
    "secret_key",
    "bearer_token",
    "security_token",
    "app_secret",
}

SENSITIVE_HEADER_KEYS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "api-key",
}


class WorkflowImportError(ValueError):
    """Raised when an import payload cannot be understood."""


def _sanitize_params(params: dict[str, Any]) -> None:
    """Recursively sanitize sensitive parameter keys and auth headers."""
    for key in list(params.keys()):
        key_lower = key.lower()
        if (
            key_lower in SENSITIVE_PARAM_KEYS
            or key_lower.endswith(("_secret", "_password", "_token", "_key"))
            or ("password" in key_lower and "policy" not in key_lower)
        ):
            params.pop(key, None)
            continue

        val = params[key]
        if isinstance(val, dict):
            if key_lower == "headers":
                for hk in list(val.keys()):
                    if str(hk).lower() in SENSITIVE_HEADER_KEYS:
                        val.pop(hk, None)
            else:
                _sanitize_params(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    if "name" in item and str(item.get("name")).lower() in SENSITIVE_HEADER_KEYS:
                        item["value"] = ""
                    else:
                        _sanitize_params(item)


def sanitize_workflow_data(
    workflow: dict[str, Any],
    *,
    strip_credentials: bool = True,
    strip_secrets: bool = True,
) -> dict[str, Any]:
    """Sanitize a workflow dictionary for safe export, duplication, template save, or import.

    1. Removes all live credential references or replaces them with empty dicts.
    2. Removes passwords, tokens, API keys, secrets, and auth headers from node parameters.
    3. Strips runtime/execution state, active jobs, traces, and execution IDs.
    4. Enforces inactive status (`active = False`, `status = "draft"`).
    """
    import copy

    doc = copy.deepcopy(workflow)

    # 1. Enforce lifecycle safety
    doc["active"] = False
    doc["status"] = "draft"

    # 2. Exclude runtime execution state
    for run_key in (
        "execution_id",
        "executionId",
        "active_execution_id",
        "runtime_state",
        "job_id",
        "results",
        "trace",
        "last_run",
        "history",
        "pending_jobs",
        "run_preview",
        "runPreview",
        "node_statuses",
        "nodeStatuses",
    ):
        doc.pop(run_key, None)

    # 3. Sanitize nodes
    nodes = doc.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue

            if strip_credentials:
                node["credentials"] = {}

            params = node.get("parameters")
            if isinstance(params, dict) and strip_secrets:
                _sanitize_params(params)

            for nk in ("last_run", "runPreview", "execution_status", "status_message", "error"):
                node.pop(nk, None)

    return doc


def build_export(workflow: dict[str, Any]) -> dict[str, Any]:
    """Wrap a native workflow document for download, strictly excluding secrets and runtime state."""
    sanitized = sanitize_workflow_data(workflow, strip_credentials=True, strip_secrets=True)
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workflow": sanitized,
    }


def parse_import(payload: Any) -> dict[str, Any]:
    """Normalize an import payload to a native workflow document.

    Guarantees that:
    1. The payload conforms to a supported format and version.
    2. Node and connection structures are normalized.
    3. Credentials and secret parameters are sanitized.
    4. Lifecycle is set to Draft / Inactive (`active = False`, `status = "draft"`).
    """
    if not isinstance(payload, dict):
        raise WorkflowImportError("Import payload must be a JSON object.")

    fmt = payload.get("format")
    ver = payload.get("version")
    if fmt == EXPORT_FORMAT and ver is not None:
        try:
            parsed_ver = int(ver)
        except (ValueError, TypeError):
            raise WorkflowImportError(f"Invalid export version: {ver}")
        if parsed_ver > EXPORT_VERSION:
            raise WorkflowImportError(
                f"Unsupported workflow export version: {ver}. Supported up to version {EXPORT_VERSION}."
            )

    wrapped = payload.get("workflow")
    inner: dict[str, Any] = wrapped if isinstance(wrapped, dict) else payload
    connections = inner.get("connections")
    if isinstance(connections, dict):
        out = _from_external(inner)
    elif not isinstance(inner.get("nodes"), list):
        raise WorkflowImportError(
            "Unrecognized workflow document: expected a 'nodes' array "
            "(native, opencode-workflow envelope, or standard export)."
        )
    else:
        out = dict(inner)

    return sanitize_workflow_data(out, strip_credentials=True, strip_secrets=True)


# ----------------------------------------------------------------------
# External -> native conversion
# ----------------------------------------------------------------------


def _external_schedule_params(p: dict[str, Any]) -> dict[str, Any]:
    rule = p.get("rule") or {}
    cron = p.get("cron") or rule.get("cronExpression")
    if not cron:
        raise WorkflowImportError(
            "scheduleTrigger: no cron expression found "
            "(expected parameters.rule.cronExpression)."
        )
    tz = p.get("timezone") or rule.get("timezone") or "UTC"
    return {"cron": cron, "timezone": tz}


def _external_set_params(p: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for item in p.get("assignments") or []:
        if isinstance(item, dict) and item.get("name"):
            fields[str(item["name"])] = item.get("value")
    return {"mode": "merge", "fields": fields}


_IF_OPERATOR_MAP = {
    "equals": "equals",
    "equal": "equals",
    "notEquals": "not_equals",
    "notEqual": "not_equals",
    "contains": "contains",
    "startsWith": "starts_with",
    "greaterThan": "greater_than",
    "greater": "greater_than",
    "lessThan": "less_than",
    "less": "less_than",
}


def _compat_if_params(p: dict[str, Any]) -> dict[str, Any]:
    conditions = (p.get("conditions") or {}).get("conditions") or []
    if not conditions:
        raise WorkflowImportError("if node: no conditions found.")
    first = conditions[0]
    op = str(first.get("operator", "string:equals"))
    suffix = op.split(":")[-1]
    native_op = _IF_OPERATOR_MAP.get(suffix)
    if native_op is None:
        raise WorkflowImportError(f"if node: unsupported operator '{op}'.")
    return {
        "condition": {
            "left": first.get("leftValue"),
            "operator": native_op,
            "right": first.get("rightValue"),
        }
    }


def _compat_http_params(p: dict[str, Any]) -> dict[str, Any]:
    method = str(p.get("method", "GET")).upper()
    url = p.get("url")
    if not url:
        raise WorkflowImportError("httpRequest: no url found.")
    headers: dict[str, str] = {}
    if p.get("sendHeaders"):
        for item in (p.get("headerParameters") or {}).get("parameters") or []:
            if isinstance(item, dict) and item.get("name"):
                headers[str(item["name"])] = str(item.get("value", ""))
    params: dict[str, Any] = {"method": method, "url": url, "headers": headers}
    body = p.get("jsonBody")
    if p.get("sendBody") and body is not None:
        params["body"] = body
    return params


def _compat_webhook_params(p: dict[str, Any]) -> dict[str, Any]:
    path = p.get("path")
    if not path:
        raise WorkflowImportError("webhook: no path found.")
    return {"path": str(path), "method": str(p.get("httpMethod", "POST")).upper()}


def _compat_salesforce_params(p: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = dict(p)
    resource = params.pop("resource", None)
    operation = params.pop("operation", None)
    if operation:
        params["operation"] = operation
    if resource:
        params["resource"] = resource
    return params


_COMPAT_TYPE_MAP: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "manualTrigger": ("manual_trigger", lambda p: {}),
    "errorTrigger": ("error_trigger", lambda p: {}),
    "scheduleTrigger": ("schedule", _external_schedule_params),
    "set": ("set_data", _external_set_params),
    "if": ("if_condition", _compat_if_params),
    "httpRequest": ("http_request", _compat_http_params),
    "webhook": ("webhook", _compat_webhook_params),
    "salesforce": ("salesforce", _compat_salesforce_params),
}


_KNOWN_NATIVE_TYPES = {
    "manual_trigger",
    "error_trigger",
    "schedule_trigger",
    "schedule",
    "webhook",
    "http_request",
    "code",
    "data_table",
    "human_approval",
    "rag_pipeline",
    "set_data",
    "if_condition",
    "salesforce",
    "send_email",
    "slack",
    "telegram",
    "database_query",
    "file_io",
    "filter",
    "graphql",
    "aggregate",
    "ai",
    "ai_agent",
    "csv_json_transform",
    "loop",
    "loop_over_items",
    "loop_while",
    "merge",
    "pagination",
    "split",
    "sub_workflow",
    "switch",
    "wait",
    "websocket",
    "salesforce_trigger",
}


def _from_external(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert an external workflow export or template to the native document shape."""
    unknown: list[str] = []
    nodes: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}

    for i, n in enumerate(payload.get("nodes") or []):
        raw_type = str(n.get("type", ""))
        short_type = raw_type.split(".")[-1] if "." in raw_type else raw_type
        mapped = _COMPAT_TYPE_MAP.get(raw_type) or _COMPAT_TYPE_MAP.get(short_type)
        if mapped is not None:
            native_type, params_fn = mapped
            try:
                native_params = params_fn(n.get("parameters") or {})
            except WorkflowImportError as exc:
                raise WorkflowImportError(
                    f"node '{n.get('name', raw_type)}' ({raw_type}): {exc}"
                ) from exc
        elif raw_type in _KNOWN_NATIVE_TYPES or short_type in _KNOWN_NATIVE_TYPES:
            matched = raw_type if raw_type in _KNOWN_NATIVE_TYPES else short_type
            native_type = "schedule" if matched == "schedule_trigger" else matched
            native_params = n.get("parameters") or {}
        else:
            unknown.append(raw_type)
            continue

        new_id = f"n{i + 1}"
        id_map[str(n.get("id", new_id))] = new_id
        position = n.get("position")
        if isinstance(position, list) and len(position) >= 2:
            position = {"x": float(position[0]), "y": float(position[1])}
        elif isinstance(position, dict) and "x" in position and "y" in position:
            position = {"x": float(position["x"]), "y": float(position["y"])}
        else:
            position = {"x": 0, "y": 0}
        nodes.append(
            {
                "id": new_id,
                "type": native_type,
                "version": 1,
                "position": position,
                "parameters": native_params,
                "settings": n.get("settings") or {},
                "credentials": n.get("credentials") or {},
                "name": n.get("name", ""),  # preserve node name for $('Name') expressions
            }
        )

    if unknown:
        raise WorkflowImportError(
            "Unsupported node type(s): "
            + ", ".join(sorted(set(unknown)))
            + ". Supported: manualTrigger, scheduleTrigger, set, if, "
            "httpRequest, webhook, salesforce."
        )

    connections: list[dict[str, Any]] = []
    raw_conns = payload.get("connections")
    if isinstance(raw_conns, list):
        connections = raw_conns
    elif isinstance(raw_conns, dict):
        for source, handles in raw_conns.items():
            src_id = id_map.get(source, source)
            if src_id not in id_map.values():
                continue  # dangling source (node was filtered out) -> drop
            for handle_name, output_lists in (handles or {}).items():
                if isinstance(output_lists, list):
                    for output_list in output_lists or []:
                        if isinstance(output_list, list):
                            for item in output_list or []:
                                if isinstance(item, dict) and "node" in item:
                                    target = id_map.get(str(item.get("node")))
                                    if target is None:
                                        continue  # dangling edge -> drop
                                    connections.append(
                                        {
                                            "source": src_id,
                                            "sourceHandle": str(handle_name),
                                            "target": target,
                                            "targetHandle": str(item.get("type", "main")),
                                        }
                                    )

    return {
        "id": f"wf_import_{uuid.uuid4().hex[:12]}",
        "name": str(payload.get("name") or "Imported Workflow"),
        "version": 1,
        "status": "draft",
        "nodes": nodes,
        "connections": connections,
        "settings": payload.get("settings") or {},
    }
