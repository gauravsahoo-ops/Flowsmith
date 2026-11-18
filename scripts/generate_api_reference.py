#!/usr/bin/env python3
"""Generate the committed API reference from the FastAPI OpenAPI schema.

Usage (from the repository root):

    .venv/Scripts/python.exe scripts/generate_api_reference.py

Outputs:
    docs/API_REFERENCE.md
    docs/openapi.json

The generated markdown is intentionally descriptive rather than a substitute
for the hand-written conventions in docs/API_GUIDE.md. It gives reviewers a
complete, reproducible inventory of every route exposed by the application.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
OUT_MD = ROOT / "docs" / "API_REFERENCE.md"
OUT_JSON = ROOT / "docs" / "openapi.json"


def schema_label(schema: Any) -> str:
    """Return a compact, human-readable label for an OpenAPI schema."""
    if not isinstance(schema, dict):
        return "any"
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if "anyOf" in schema:
        return " | ".join(schema_label(item) for item in schema["anyOf"])
    if "oneOf" in schema:
        return " | ".join(schema_label(item) for item in schema["oneOf"])
    if "allOf" in schema:
        return " & ".join(schema_label(item) for item in schema["allOf"])
    kind = schema.get("type", "object")
    if kind == "array":
        return f"array<{schema_label(schema.get('items', {}))}>"
    if kind == "object" and schema.get("additionalProperties"):
        return f"map<{schema_label(schema['additionalProperties'])}>"
    return kind


def escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def resolve_ref(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def field_rows(spec: dict[str, Any], schema: dict[str, Any], limit: int = 40) -> list[str]:
    """Render the top-level fields of a request/response object."""
    schema = resolve_ref(spec, schema)
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        return []
    required = set(schema.get("required", []))
    rows = []
    for name, prop in list(props.items())[:limit]:
        if not isinstance(prop, dict):
            continue
        flags = []
        if name in required:
            flags.append("required")
        if prop.get("readOnly"):
            flags.append("read-only")
        if prop.get("writeOnly"):
            flags.append("write-only")
        desc = prop.get("description", "")
        rows.append(
            f"| `{escape(name)}` | {escape(schema_label(prop))} | {escape(', '.join(flags))} | {escape(desc)} |"
        )
    return rows


def operation_sort_key(item: tuple[str, str, dict[str, Any]]) -> tuple[str, str, int]:
    path, method, operation = item
    tag = (operation.get("tags") or ["untagged"])[0]
    return tag, path, HTTP_METHODS.index(method)


def main() -> None:
    spec = app.openapi()
    paths = spec.get("paths", {})
    operations = []
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if method in HTTP_METHODS and isinstance(operation, dict):
                operations.append((path, method, operation))
    operations.sort(key=operation_sort_key)

    tags = sorted({(op.get("tags") or ["untagged"])[0] for _, _, op in operations})
    today = date.today().isoformat()
    version = spec.get("info", {}).get("version", "unknown")
    schemas = spec.get("components", {}).get("schemas", {})

    lines: list[str] = [
        "# Flowsmith Generated API Reference",
        "",
        f"> **Generated:** {today} from the FastAPI application schema (version `{version}`).  ",
        "> **Regenerate:** `.venv/Scripts/python.exe scripts/generate_api_reference.py`  ",
        f"> **Machine-readable schema:** [`openapi.json`](openapi.json)  ",
        f"> **Coverage:** {len(paths)} paths, {len(operations)} operations, {len(schemas)} component schemas.",
        "",
        "This file is a complete route inventory generated directly from the running",
        "application. It complements, but does not replace, the authentication,",
        "envelope, websocket, and error conventions in [`API_GUIDE.md`](API_GUIDE.md).",
        "",
        "## Conventions",
        "",
        "- All application routes are mounted under `/api` unless the generated path says otherwise.",
        "- Private routes require a bearer JWT or the configured API-key header. Authentication",
        "  requirements are enforced through FastAPI dependencies and are therefore not fully",
        "  represented in the generated OpenAPI security metadata; use `API_GUIDE.md` for the",
        "  authoritative authentication contract.",
        "- Successful responses normally use `{\"data\": ...}`; errors use FastAPI's `{\"detail\": ...}` shape.",
        "- Request and response schema names refer to the component definitions in `openapi.json`.",
        "- This document is generated from code, so it cannot silently drift from the route table.",
        "",
        "## Endpoint summary",
        "",
        "| Tag | Operations |",
        "| :--- | ---: |",
    ]
    for tag in tags:
        count = sum(1 for _, _, op in operations if (op.get("tags") or ["untagged"])[0] == tag)
        lines.append(f"| [`{escape(tag)}`](#{tag.lower().replace(' ', '-')}) | {count} |")
    lines.extend(["", f"| **Total** | **{len(operations)}** |", "", "---", ""])

    current_tag = None
    for path, method, operation in operations:
        tag = (operation.get("tags") or ["untagged"])[0]
        if tag != current_tag:
            current_tag = tag
            lines.extend(["", f"## {tag}", ""])
        summary = operation.get("summary") or "(no summary)"
        lines.append(f"### `{method.upper()} {path}`")
        lines.append("")
        lines.append(f"**{escape(summary)}**")
        lines.append("")
        if operation.get("description"):
            lines.append(escape(operation["description"]))
            lines.append("")
        op_id = operation.get("operationId")
        deprecated = " **Deprecated.**" if operation.get("deprecated") else ""
        if op_id:
            lines.append(f"- Operation ID: `{op_id}`{deprecated}")
        lines.append(f"- Auth: see [API_GUIDE.md](API_GUIDE.md#2-authentication--authorization)")
        lines.append("")

        parameters = operation.get("parameters") or []
        if parameters:
            lines.extend(
                [
                    "| Parameter | In | Required | Type | Description |",
                    "| :--- | :--- | :---: | :--- | :--- |",
                ]
            )
            for param in parameters:
                lines.append(
                    "| `{}` | {} | {} | {} | {} |".format(
                        escape(param.get("name")),
                        escape(param.get("in")),
                        "yes" if param.get("required") else "no",
                        escape(schema_label(param.get("schema", {}))),
                        escape(param.get("description")),
                    )
                )
            lines.append("")

        body = operation.get("requestBody")
        if body:
            content = body.get("content", {})
            media_types = ", ".join(f"`{escape(k)}`" for k in content)
            required = "required" if body.get("required") else "optional"
            lines.append(f"**Request body** ({required}): {media_types or 'unspecified'}")
            lines.append("")
            for media_type, media in content.items():
                schema = media.get("schema", {})
                lines.append(f"Schema: `{escape(schema_label(schema))}`")
                rows = field_rows(spec, schema)
                if rows:
                    lines.extend(
                        [
                            "",
                            "| Field | Type | Flags | Description |",
                            "| :--- | :--- | :--- | :--- |",
                            *rows,
                        ]
                    )
                lines.append("")

        responses = operation.get("responses") or {}
        if responses:
            lines.extend(
                [
                    "| Status | Description | Schema |",
                    "| :--- | :--- | :--- |",
                ]
            )
            for status, response in sorted(responses.items(), key=lambda item: str(item[0])):
                schema = (
                    response.get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                lines.append(
                    f"| `{escape(status)}` | {escape(response.get('description'))} | `{escape(schema_label(schema))}` |"
                )
            lines.append("")
        lines.append("---")
        lines.append("")

    OUT_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    OUT_JSON.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_MD.relative_to(ROOT)} ({len(lines)} lines, {len(operations)} operations)")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)} ({len(schemas)} schemas)")


if __name__ == "__main__":
    main()
