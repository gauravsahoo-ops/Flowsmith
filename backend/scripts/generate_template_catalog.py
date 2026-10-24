"""Generate schema-derived starter templates for native connector operations.

Curated templates live in ``library.py``. This script appends one starter per
unused native operation until the requested count is reached, deriving required
parameters from each operation's JSON input schema. It is deterministic and is
meant to be rerun when connector definitions change.
"""

from __future__ import annotations

import pprint
import re
from pathlib import Path
from typing import Any

from app.connectors import get_registry, register_builtin_connectors
from app.templates.generated import GENERATED_TEMPLATES as EXISTING_GENERATED
from app.templates.library import CONNECTOR_TEMPLATES

TARGET = 200
OUTPUT = Path(__file__).resolve().parents[1] / "app" / "templates" / "generated.py"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]


def _value(connector: str, field: str, schema: dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    typ = schema.get("type")
    if typ == "integer":
        return 1
    if typ == "number":
        return 1
    if typ == "boolean":
        return False
    if typ == "array":
        return []
    if typ == "object":
        return {}
    if typ == "string":
        fmt = schema.get("format")
        if fmt == "uri":
            return "https://example.com"
        if fmt == "email":
            return "user@example.com"
        return "{{ $env.%s_%s }}" % (connector.upper(), field.upper())
    return "{{ $json.%s }}" % field


def _parameters(schema: dict[str, Any], connector: str) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    result: dict[str, Any] = {}
    for name, prop in properties.items():
        if name in required:
            result[name] = _value(connector, name, prop)
        elif "default" in prop:
            result[name] = prop["default"]
    return result


def _template(
    name: str,
    description: str,
    category: str,
    node_type: str,
    operation: str,
    parameters: dict[str, Any],
    trigger: str,
) -> dict[str, Any]:
    if trigger == "webhook":
        trigger_params = {"path": f"template-{_slug(name)}", "http_method": "POST"}
    elif trigger == "schedule":
        trigger_params = {"cron": "0 9 * * *", "timezone": "UTC"}
    else:
        trigger_params = {}
    return {
        "name": name,
        "description": description,
        "category": category,
        "workflow_data": {
            "name": name,
            "nodes": [
                {
                    "id": "trigger", "type": trigger, "name": "Start",
                    "position": {"x": 100, "y": 200}, "parameters": trigger_params,
                },
                {
                    "id": "action", "type": node_type, "name": name,
                    "position": {"x": 380, "y": 200},
                    "parameters": {"operation": operation, **parameters},
                },
                {
                    "id": "result", "type": "set_data", "name": "Return Result",
                    "position": {"x": 660, "y": 200},
                    "parameters": {"fields": {"ok": True, "result": "{{ $node.action.json }}"}},
                },
            ],
            "connections": [
                {"source": "trigger", "sourceHandle": "main", "target": "action", "targetHandle": "main"},
                {"source": "action", "sourceHandle": "main", "target": "result", "targetHandle": "main"},
            ],
            "settings": {},
        },
    }


def main() -> None:
    register_builtin_connectors()
    generated_names = {template["name"] for template in EXISTING_GENERATED}
    curated = [
        template for template in CONNECTOR_TEMPLATES
        if template["name"] not in generated_names
    ]
    used = {
        (node["type"], node["parameters"].get("operation"))
        for template in curated
        for node in template["workflow_data"]["nodes"]
        if node["id"] == "action"
    }
    names = {template["name"] for template in curated}
    groups: list[tuple[str, Any, list[tuple[str, Any]]]] = []
    for definition in sorted(get_registry().list_definitions(), key=lambda d: d.connector_key):
        candidates: list[tuple[str, Any]] = []
        for op_key, op in sorted(definition.operations.items()):
            node_type = next((value for value in op.node_types if value), None)
            if node_type and (node_type, op_key) not in used:
                candidates.append((op_key, op))
        if candidates:
            groups.append((definition.connector_key, definition, candidates))

    generated: list[dict[str, Any]] = []
    indexes = [0] * len(groups)
    while len(generated) < TARGET:
        progressed = False
        for group_index, (connector_key, definition, candidates) in enumerate(groups):
            if len(generated) >= TARGET:
                break
            index = indexes[group_index]
            if index >= len(candidates):
                continue
            progressed = True
            op_key, op = candidates[index]
            indexes[group_index] += 1
            node_type = next((value for value in op.node_types if value), None)
            if not node_type:
                continue
            name = f"{definition.display_name} {op.display_name}"
            if name in names:
                name = f"{name} ({op_key})"
            if name in names:
                continue
            names.add(name)
            lowered = op_key.lower()
            if any(token in lowered for token in ("list", "search", "get", "find", "profile")):
                trigger = "schedule"
            elif any(token in lowered for token in ("create", "send", "update", "delete", "upload", "insert", "run")):
                trigger = "webhook"
            else:
                trigger = "manual_trigger"
            generated.append(_template(
                name,
                f"Starter workflow for {definition.display_name} {op.display_name}. "
                "Attach credentials and fill the generated environment placeholders before running.",
                definition.category,
                node_type,
                op_key,
                _parameters(op.input_schema, connector_key),
                trigger,
            ))
        if not progressed:
            break

    OUTPUT.write_text(
        '"""Generated schema-derived starter templates. Do not edit by hand."""\n\n'
        "GENERATED_TEMPLATES: list[dict] = "
        + pprint.pformat(generated, width=118, sort_dicts=False)
        + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(generated)} templates -> {OUTPUT}")


if __name__ == "__main__":
    main()
