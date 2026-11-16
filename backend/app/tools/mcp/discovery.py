"""MCP tool discovery and durable cache reconciliation.

Discovery is deliberately conservative: it never infers a read-only risk class
from untrusted server metadata. Every discovered tool defaults to ``write``
until a reviewer explicitly classifies it.

The service accepts an injected client so tests (and future transports) can run
without network access. When no client is supplied, the existing HTTP MCP
client is constructed lazily from the server record.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MCPToolCache, MCPServer
from app.platform.contracts import RiskClass
from app.tools.mcp.client_factory import build_mcp_client
from app.tools.mcp.registry import MCPServiceError
from app.tools.mcp.sandbox import SandboxError

DEFAULT_RISK_CLASS: str = RiskClass.WRITE.value
MAX_TOOL_NAME_LENGTH = 128
EMPTY_INPUT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


class MCPDiscoveryError(MCPServiceError):
    """Discovery failure with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message or code, code=code)
        if http_status is not None:
            self.http_status = http_status


def schema_hash(schema: dict[str, Any]) -> str:
    """Return the SHA-256 digest of a schema's canonical JSON form."""
    try:
        canonical = json.dumps(
            schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    except TypeError:
        # Defensive fallback for non-string mapping keys; normal JSON Schema
        # documents always take the deterministic path above.
        canonical = json.dumps(
            schema,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_tool(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str):
        return None
    clean_name = name.strip()
    if not clean_name or len(clean_name) > MAX_TOOL_NAME_LENGTH:
        return None

    description = raw.get("description")
    if not isinstance(description, str):
        description = ""

    raw_schema = raw.get("inputSchema")
    if not isinstance(raw_schema, dict):
        snake_schema = raw.get("input_schema")
        raw_schema = snake_schema if isinstance(snake_schema, dict) else None
    if isinstance(raw_schema, dict):
        input_schema = copy.deepcopy(raw_schema)
    else:
        input_schema = copy.deepcopy(EMPTY_INPUT_SCHEMA)

    return {
        "name": clean_name,
        "description": description,
        "input_schema": input_schema,
    }


def normalize_tools(tools: Any) -> list[dict[str, Any]]:
    """Normalize a ``tools/list`` response into cache-ready dictionaries.

    A non-list payload is a discovery failure. Individual malformed entries are
    skipped; duplicate tool names keep the last declaration.
    """
    if not isinstance(tools, list):
        raise MCPDiscoveryError(
            "MCP_DISCOVERY_FAILED", "MCP tools/list did not return a list."
        )
    normalized: dict[str, dict[str, Any]] = {}
    for raw in tools:
        tool = _normalize_tool(raw)
        if tool is not None:
            normalized[tool["name"]] = tool
    return list(normalized.values())


async def discover_and_cache(
    db: Session,
    server: MCPServer,
    *,
    client: Any = None,
    auth_token: str | None = None,
    timeout_s: float = 10.0,
) -> list[MCPToolCache]:
    """Discover tools, reconcile the cache, and return all cache rows.

    Rows for tools that are no longer advertised are disabled (never deleted)
    so approval/audit references remain valid. The returned list includes those
    disabled rows, ordered by tool name.
    """
    if not server.enabled:
        raise MCPDiscoveryError("MCP_SERVER_DISABLED")
    if (
        server.auth_type in ("bearer", "credential")
        and client is None
        and not auth_token
    ):
        raise MCPDiscoveryError("MCP_CREDENTIAL_REQUIRED")

    if client is None:
        try:
            client = build_mcp_client(server, auth_token=auth_token)
        except SandboxError as exc:
            raise MCPDiscoveryError(
                "MCP_DISCOVERY_FAILED",
                "MCP sandbox could not be configured.",
                http_status=502,
            ) from exc

    timeout = max(0.1, float(timeout_s))
    try:
        strict = getattr(client, "list_tools_strict", None)
        if strict is not None:
            tools = await strict(timeout_s=timeout)
        else:
            tools = await client.list_tools(timeout_s=timeout)
    except Exception as exc:  # noqa: BLE001 - normalize transport failures
        raise MCPDiscoveryError(
            "MCP_DISCOVERY_FAILED",
            f"MCP tool discovery failed: {exc}",
            http_status=502,
        ) from exc

    normalized = normalize_tools(tools)
    existing = {
        row.tool_name: row
        for row in db.scalars(
            select(MCPToolCache).where(MCPToolCache.server_id == server.id)
        ).all()
    }

    seen: set[str] = set()
    for tool in normalized:
        name = tool["name"]
        digest = schema_hash(tool["input_schema"])
        row = existing.get(name)
        if row is None:
            row = MCPToolCache(
                server_id=server.id,
                tool_name=name,
                description=tool["description"],
                input_schema=tool["input_schema"],
                risk_class=DEFAULT_RISK_CLASS,
                schema_hash=digest,
                enabled=True,
            )
            db.add(row)
            existing[name] = row
        else:
            row.description = tool["description"]
            row.input_schema = tool["input_schema"]
            row.risk_class = DEFAULT_RISK_CLASS
            row.schema_hash = digest
            row.enabled = True
        seen.add(name)

    for name, row in existing.items():
        if name not in seen:
            row.enabled = False

    db.flush()
    rows = list(
        db.scalars(
            select(MCPToolCache)
            .where(MCPToolCache.server_id == server.id)
            .order_by(MCPToolCache.tool_name)
        ).all()
    )
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def tool_to_dict(tool: MCPToolCache) -> dict[str, Any]:
    """Serialize a cache row for API responses."""
    return {
        "id": tool.id,
        "server_id": tool.server_id,
        "tool_name": tool.tool_name,
        "description": tool.description,
        "input_schema": tool.input_schema or {},
        "risk_class": tool.risk_class,
        "schema_hash": tool.schema_hash,
        "enabled": tool.enabled,
        "discovered_at": tool.discovered_at.isoformat() if tool.discovered_at else None,
        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
    }


def update_cached_tool(
    db: Session,
    server: MCPServer,
    tool_id: str,
    *,
    risk_class: str | None = None,
    enabled: bool | None = None,
) -> MCPToolCache:
    """Update reviewer-assigned risk/enabled state for a cached tool."""
    tool = db.get(MCPToolCache, tool_id)
    if tool is None or tool.server_id != server.id:
        raise MCPDiscoveryError(
            "MCP_TOOL_NOT_FOUND", "MCP tool not found for this server.", http_status=404
        )
    if risk_class is not None:
        try:
            normalized = RiskClass(str(risk_class)).value
        except ValueError as exc:
            raise MCPDiscoveryError(
                "MCP_RISK_INVALID",
                f"Unsupported risk class: {risk_class!r}",
                http_status=422,
            ) from exc
        tool.risk_class = normalized
    if enabled is not None:
        tool.enabled = bool(enabled)
    db.commit()
    db.refresh(tool)
    return tool
