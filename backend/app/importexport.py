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


class WorkflowImportError(ValueError):
    """Raised when an import payload cannot be understood."""


def build_export(workflow: dict[str, Any]) -> dict[str, Any]:
    """Wrap a native workflow document for download."""
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workflow": workflow,
    }


def parse_import(payload: Any) -> dict[str, Any]:
    """Normalize an import payload to a native workflow document."""
    if not isinstance(payload, dict):
        raise WorkflowImportError("Import payload must be a JSON object.")
    wrapped = payload.get("workflow")
    inner: dict[str, Any] = wrapped if isinstance(wrapped, dict) else payload
    connections = inner.get("connections")
    if isinstance(connections, dict):
        return _from_external(inner)
    if not isinstance(inner.get("nodes"), list):
        raise WorkflowImportError(
            "Unrecognized workflow document: expected a 'nodes' array "
            "(native, opencode-workflow envelope, or standard export)."
        )
    return inner


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
