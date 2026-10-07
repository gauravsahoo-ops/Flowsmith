"""Connector discovery endpoints (spec 37+).

Provides backend APIs for connector discovery as defined in the
Connector Framework v2 specification.

Required conceptual endpoints:

GET /api/connectors
GET /api/connectors/{connector_key}
GET /api/connectors/{connector_key}/operations
GET /api/connectors/{connector_key}/triggers
GET /api/connectors/{connector_key}/credential-types

Protect endpoints appropriately - read access for authenticated users,
writable operations require proper authorization.
"""

from __future__ import annotations

import ast

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.api.common import ok
from app.models import User
from app.connectors.registry import ConnectorRegistry
from app.connectors import get_registry as _get_registry

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def get_registry() -> ConnectorRegistry:
    """FastAPI dependency: get the global connector registry."""
    return _get_registry()


@router.get("")
def list_connectors(
    user: User = Depends(get_current_user),
) -> dict:
    """List all registered connectors (public discovery)."""
    registry = get_registry()
    definitions = registry.list_definitions()
    return ok(
        [
            {
                "connector_key": d.connector_key,
                "display_name": d.display_name,
                "description": d.description,
                "category": d.category,
                "connector_version": d.connector_version,
                "lifecycle_status": d.lifecycle_status,
                "icon": d.icon,
                "operations": list(d.operations.keys()),
                "triggers": list(d.triggers.keys()),
                "credential_types": list(d.credential_types.keys()),
                "metadata": d.metadata,
            }
            for d in definitions
        ]
    )


@router.get("/{connector_key}")
def get_connector(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get connector definition by key."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": definition.connector_key,
            "display_name": definition.display_name,
            "description": definition.description,
            "category": definition.category,
            "connector_version": definition.connector_version,
            "lifecycle_status": definition.lifecycle_status,
            "icon": definition.icon,
            "operations": {
                k: {
                    "operation_key": op.operation_key,
                    "operation_version": op.operation_version,
                    "display_name": op.display_name,
                    "description": op.description,
                    "credential_require": op.credential_require,
                    "retryable": op.retryable,
                    "idempotency": op.idempotency,
                }
                for k, op in definition.operations.items()
            },
            "triggers": {
                k: {
                    "trigger_key": t.trigger_key,
                    "trigger_version": t.trigger_version,
                    "trigger_type": t.trigger_type,
                    "configuration_schema": t.configuration_schema,
                    "credential_require": t.credential_require,
                }
                for k, t in definition.triggers.items()
            },
            "credential_types": {
                k: {
                    "type_key": ct.type_key,
                    "display_name": ct.display_name,
                    "description": ct.description,
                    "secret_fields": ct.secret_fields,
                    "validation_schema": ct.validation_schema,
                    "encryption_required": ct.encryption_required,
                }
                for k, ct in definition.credential_types.items()
            },
            "metadata": definition.metadata,
        }
    )


@router.get("/{connector_key}/operations")
def get_connector_operations(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get operation definitions for a connector."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": connector_key,
            "operations": {
                op_key: {
                    "operation_key": op.operation_key,
                    "operation_version": op.operation_version,
                    "display_name": op.display_name,
                    "description": op.description,
                    "input_schema": op.input_schema,
                    "output_schema": op.output_schema,
                    "credential_require": op.credential_require,
                    "retryable": op.retryable,
                    "idempotency": op.idempotency,
                }
                for op_key, op in definition.operations.items()
            },
        }
    )


@router.get("/{connector_key}/triggers")
def get_connector_triggers(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get trigger definitions for a connector."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": connector_key,
            "triggers": {
                trigger_key: {
                    "trigger_key": t.trigger_key,
                    "trigger_version": t.trigger_version,
                    "trigger_type": t.trigger_type,
                    "configuration_schema": t.configuration_schema,
                    "credential_require": t.credential_require,
                }
                for trigger_key, t in definition.triggers.items()
            },
        }
    )


@router.get("/{connector_key}/credential-types")
def get_connector_credential_types(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get credential type definitions for a connector."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": connector_key,
            "credential_types": {
                ct_type: {
                    "type_key": ct.type_key,
                    "display_name": ct.display_name,
                    "description": ct.description,
                    "secret_fields": ct.secret_fields,
                    "validation_schema": ct.validation_schema,
                    "encryption_required": ct.encryption_required,
                }
                for ct_type, ct in definition.credential_types.items()
            },
        }
    )


async def _load_source_text(spec: Any) -> str | dict[str, Any]:
    """Fetch spec from HTTP/HTTPS URL (SSRF-safe, size-capped) or return raw text/dict."""
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, str) and spec.strip().startswith(("http://", "https://")):
        from app.security.safe_http_client import get_safe_http_client

        async with get_safe_http_client() as client:
            resp = await client.get(
                spec.strip(),
                headers={"User-Agent": "Flowsmith-Connector-Importer/1.0"},
                timeout=30.0,
                max_response_bytes=5 * 1024 * 1024,
            )
        return resp.text
    return spec


class PreviewOpenApiRequest(BaseModel):
    spec: Any


class ImportOpenApiRequest(BaseModel):
    spec: Any
    name: str
    title: str = ""
    category: str = "api"
    base_url: str = ""


@router.post("/preview-openapi")
async def preview_openapi(
    body: PreviewOpenApiRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Preview an OpenAPI/Swagger spec before importing."""
    from app.connectors.openapi_import import parse_spec

    if not body.spec:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Spec URL, raw content, or schema object is required.")

    try:
        raw = await _load_source_text(body.spec)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to load spec: {exc}")

    try:
        api_spec = parse_spec(raw)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to parse OpenAPI spec: {exc}")

    return ok({
        "title": api_spec.title,
        "base_url": api_spec.base_url,
        "auth": {
            "kind": api_spec.auth.kind,
            "name": api_spec.auth.name,
        },
        "operations": [
            {
                "operation_key": op.operation_key,
                "method": op.method,
                "path": op.path,
                "summary": op.summary,
            }
            for op in api_spec.operations
        ],
        "operations_count": len(api_spec.operations),
    })


@router.post("/import-openapi")
async def import_openapi(
    body: ImportOpenApiRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Generate and register a first-class Flowsmith connector from an OpenAPI/Swagger spec."""
    from pathlib import Path
    from app.connectors.openapi_import import parse_spec
    from app.connectors.openapi_emit import (
        connector_key_for,
        emit_connector_files,
        register_generated,
    )

    name = body.name.strip()
    if not body.spec or not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Spec and connector name are required.")

    try:
        raw = await _load_source_text(body.spec)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to load spec: {exc}")

    try:
        api_spec = parse_spec(raw)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to parse OpenAPI spec: {exc}")

    if body.base_url.strip():
        api_spec.base_url = body.base_url.strip().rstrip("/")

    if not api_spec.base_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No server URL declared in spec; please specify a Base URL override.",
        )

    if not api_spec.operations:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No operations found in OpenAPI spec.")

    key = connector_key_for(name)
    display = body.title.strip() or api_spec.title or name
    files = emit_connector_files(key, display, api_spec, body.category or "api")

    for filename, source in files.items():
        try:
            tree = ast.parse(source, filename=f"<gen_{key}>")
        except SyntaxError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Generated code syntax error: {exc}")
        # Generated modules must be exactly: module docstring, then
        # `from __future__ import annotations`. Anything between them means a
        # user-controlled docstring breakout tried to inject statements
        # (defense-in-depth against RCE via info.title / servers.url).
        nodes = tree.body
        if (
            nodes
            and isinstance(nodes[0], ast.Expr)
            and isinstance(nodes[0].value, ast.Constant)
            and isinstance(nodes[0].value.value, str)
        ):
            nodes = nodes[1:]
        if not (nodes and isinstance(nodes[0], ast.ImportFrom) and nodes[0].module == "__future__"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Generated code rejected: unexpected statements before the future import in {filename}",
            )

    gen_dir = Path(__file__).resolve().parent.parent / "connectors" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)

    for filename, source in files.items():
        (gen_dir / filename).write_text(source, encoding="utf-8")

    registry = get_registry()
    count = register_generated(registry, str(gen_dir))

    return ok({
        "success": True,
        "connector_key": key,
        "display_name": display,
        "operations_count": len(api_spec.operations),
        "auth_kind": api_spec.auth.kind,
        "registered_count": count,
    })