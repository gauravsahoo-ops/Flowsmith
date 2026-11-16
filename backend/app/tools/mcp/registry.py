"""MCP server registry service (tenant/workspace scoped)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MCPServer
from app.tools.mcp.sandbox import (
    SANDBOX_BACKENDS,
    SANDBOX_WORKSPACE_MODES,
    SandboxError,
    assert_stdio_sandbox_allowed,
    docker_config_for_server,
    validate_stdio_command,
)

TRANSPORTS = frozenset({"http", "sse", "stdio"})
AUTH_TYPES = frozenset({"none", "bearer", "credential"})
TRUST_LEVELS = frozenset({"untrusted", "verified"})
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class MCPServiceError(ValueError):
    http_status = 422

    def __init__(self, message: str, *, code: str = "MCP_INVALID") -> None:
        super().__init__(message)
        self.code = code


class MCPNotFound(MCPServiceError):
    http_status = 404

    def __init__(self, message: str = "MCP server not found.") -> None:
        super().__init__(message, code="MCP_NOT_FOUND")


class MCPConflict(MCPServiceError):
    http_status = 409

    def __init__(self, message: str) -> None:
        super().__init__(message, code="MCP_CONFLICT")


def _tool_list(value: list[str] | None, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MCPServiceError(f"{label} must be a list of tool names.")
    cleaned = [item.strip() for item in value if item.strip()]
    if len(cleaned) > 200:
        raise MCPServiceError(f"{label} supports at most 200 entries.")
    invalid = [item for item in cleaned if not _TOOL_NAME_RE.fullmatch(item)]
    if invalid:
        raise MCPServiceError(f"{label} contains invalid tool name: {invalid[0]!r}")
    return sorted(set(cleaned))


def _optional_sandbox_text(
    value: str | None, label: str, max_length: int
) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    if len(clean) > max_length:
        raise MCPServiceError(
            f"{label} must be at most {max_length} characters."
        )
    return clean


def _sandbox_values(
    *,
    sandbox_backend: str | None,
    sandbox_image: str | None,
    sandbox_workspace_mode: str | None,
    sandbox_workspace_path: str | None,
    sandbox_network: str | None,
    sandbox_read_only: bool | None,
) -> tuple[str, str | None, str, str | None, str, bool]:
    backend = str(sandbox_backend or "subprocess").strip().lower()
    if backend not in SANDBOX_BACKENDS:
        raise MCPServiceError(
            "sandbox_backend must be 'subprocess' or 'docker'.",
            code="MCP_SANDBOX_BACKEND_INVALID",
        )
    mode = str(sandbox_workspace_mode or "none").strip().lower()
    if mode not in SANDBOX_WORKSPACE_MODES:
        raise MCPServiceError(
            "sandbox_workspace_mode must be one of none, ephemeral, "
            "configured, or inherit.",
            code="MCP_SANDBOX_WORKSPACE_MODE_INVALID",
        )
    image = _optional_sandbox_text(sandbox_image, "sandbox_image", 255)
    workspace_path = _optional_sandbox_text(
        sandbox_workspace_path, "sandbox_workspace_path", 2000
    )
    network = str(sandbox_network or "none").strip().lower() or "none"
    read_only = True if sandbox_read_only is None else bool(sandbox_read_only)

    settings = get_settings()
    global_image = str(getattr(settings, "mcp_stdio_docker_image", "") or "").strip()
    if backend == "docker" and not (image or global_image):
        raise MCPServiceError(
            "Docker MCP sandboxes require sandbox_image or "
            "MCP_STDIO_DOCKER_IMAGE.",
            code="MCP_SANDBOX_IMAGE_REQUIRED",
        )
    if mode == "configured" and not workspace_path:
        raise MCPServiceError(
            "Configured MCP sandboxes require sandbox_workspace_path.",
            code="MCP_SANDBOX_WORKSPACE_REQUIRED",
        )
    try:
        # Reuse the Docker policy (network allowlist, image syntax/digest,
        # workspace path) even when the effective backend is subprocess so
        # invalid policy cannot be persisted and later activated.
        docker_config_for_server(
            settings,
            image=image,
            workspace_mode=mode,
            workspace_path=workspace_path,
            network=network,
            read_only=read_only,
        )
    except SandboxError as exc:
        raise MCPServiceError(str(exc), code=exc.code) from exc
    return backend, image, mode, workspace_path, network, read_only


def _validate(
    transport: str,
    endpoint: str,
    auth_type: str,
    credential_id: str | None,
    trust_level: str,
    *,
    sandbox_backend: str | None = "subprocess",
    sandbox_image: str | None = None,
    sandbox_workspace_mode: str | None = "none",
    sandbox_workspace_path: str | None = None,
    sandbox_network: str | None = "none",
    sandbox_read_only: bool | None = True,
) -> tuple[str, str | None, str, str | None, str, bool]:
    if transport not in TRANSPORTS:
        raise MCPServiceError(f"Unsupported MCP transport: {transport!r}")
    if not endpoint.strip():
        raise MCPServiceError("MCP endpoint is required.")
    sandbox = _sandbox_values(
        sandbox_backend=sandbox_backend,
        sandbox_image=sandbox_image,
        sandbox_workspace_mode=sandbox_workspace_mode,
        sandbox_workspace_path=sandbox_workspace_path,
        sandbox_network=sandbox_network,
        sandbox_read_only=sandbox_read_only,
    )
    if transport in ("http", "sse"):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise MCPServiceError("HTTP/SSE MCP endpoints must be absolute http(s) URLs.")
    elif transport == "stdio":
        settings = get_settings()
        try:
            validate_stdio_command(
                endpoint,
                max_args=settings.mcp_stdio_max_command_args,
                max_arg_length=settings.mcp_stdio_max_command_arg_length,
            )
            assert_stdio_sandbox_allowed(settings, backend=sandbox[0])
        except SandboxError as exc:
            raise MCPServiceError(str(exc), code=exc.code) from exc
    if auth_type not in AUTH_TYPES:
        raise MCPServiceError(f"Unsupported MCP auth type: {auth_type!r}")
    if auth_type in ("bearer", "credential") and not credential_id:
        raise MCPServiceError("bearer/credential MCP servers require credential_id.")
    if trust_level not in TRUST_LEVELS:
        raise MCPServiceError(f"Unsupported trust level: {trust_level!r}")
    return sandbox


def create_server(
    db: Session,
    *,
    organization_id: str,
    workspace_id: str,
    name: str,
    endpoint: str,
    transport: str = "http",
    auth_type: str = "none",
    credential_id: str | None = None,
    description: str = "",
    trust_level: str = "untrusted",
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    enabled: bool = True,
    sandbox_backend: str = "subprocess",
    sandbox_image: str | None = None,
    sandbox_workspace_mode: str = "none",
    sandbox_workspace_path: str | None = None,
    sandbox_network: str = "none",
    sandbox_read_only: bool = True,
    created_by: int | None = None,
) -> MCPServer:
    clean_name = str(name or "").strip()
    if not clean_name or len(clean_name) > 128:
        raise MCPServiceError("MCP server name is required (max 128 characters).")
    (
        next_backend,
        next_image,
        next_mode,
        next_path,
        next_network,
        next_read_only,
    ) = _validate(
        transport,
        endpoint,
        auth_type,
        credential_id,
        trust_level,
        sandbox_backend=sandbox_backend,
        sandbox_image=sandbox_image,
        sandbox_workspace_mode=sandbox_workspace_mode,
        sandbox_workspace_path=sandbox_workspace_path,
        sandbox_network=sandbox_network,
        sandbox_read_only=sandbox_read_only,
    )
    if not organization_id or not workspace_id:
        raise MCPServiceError("organization_id and workspace_id are required.")

    existing = db.scalar(
        select(MCPServer).where(
            MCPServer.workspace_id == workspace_id,
            MCPServer.name == clean_name,
        )
    )
    if existing is not None:
        raise MCPConflict(f"An MCP server named {clean_name!r} already exists in this workspace.")

    server = MCPServer(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=clean_name,
        description=str(description or "")[:2000],
        transport=transport,
        endpoint=endpoint.strip(),
        auth_type=auth_type,
        credential_id=credential_id,
        trust_level=trust_level,
        allowed_tools=_tool_list(allowed_tools, "allowed_tools"),
        denied_tools=_tool_list(denied_tools, "denied_tools"),
        enabled=bool(enabled),
        sandbox_backend=next_backend,
        sandbox_image=next_image,
        sandbox_workspace_mode=next_mode,
        sandbox_workspace_path=next_path,
        sandbox_network=next_network,
        sandbox_read_only=next_read_only,
        created_by=created_by,
    )
    db.add(server)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise MCPConflict("MCP server name must be unique within a workspace.") from exc
    db.refresh(server)
    return server


def get_server(db: Session, server_id: str) -> MCPServer:
    server = db.get(MCPServer, server_id)
    if server is None:
        raise MCPNotFound()
    return server


def list_servers(
    db: Session,
    *,
    workspace_id: str,
    include_disabled: bool = True,
) -> list[MCPServer]:
    stmt = select(MCPServer).where(MCPServer.workspace_id == workspace_id)
    if not include_disabled:
        stmt = stmt.where(MCPServer.enabled.is_(True))
    return list(db.scalars(stmt.order_by(MCPServer.name)).all())


def update_server(
    db: Session,
    server_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    endpoint: str | None = None,
    transport: str | None = None,
    auth_type: str | None = None,
    credential_id: str | None = None,
    trust_level: str | None = None,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    enabled: bool | None = None,
    sandbox_backend: str | None = None,
    sandbox_image: str | None = None,
    sandbox_workspace_mode: str | None = None,
    sandbox_workspace_path: str | None = None,
    sandbox_network: str | None = None,
    sandbox_read_only: bool | None = None,
) -> MCPServer:
    server = get_server(db, server_id)
    next_name = str(name).strip() if name is not None else server.name
    next_endpoint = str(endpoint).strip() if endpoint is not None else server.endpoint
    next_transport = transport or server.transport
    next_auth = auth_type or server.auth_type
    next_credential = credential_id if credential_id is not None else server.credential_id
    next_trust = trust_level or server.trust_level

    if not next_name or len(next_name) > 128:
        raise MCPServiceError("MCP server name is required (max 128 characters).")
    (
        next_backend,
        next_image,
        next_mode,
        next_path,
        next_network,
        next_read_only,
    ) = _validate(
        next_transport,
        next_endpoint,
        next_auth,
        next_credential,
        next_trust,
        sandbox_backend=(
            sandbox_backend
            if sandbox_backend is not None
            else server.sandbox_backend
        ),
        sandbox_image=(
            sandbox_image if sandbox_image is not None else server.sandbox_image
        ),
        sandbox_workspace_mode=(
            sandbox_workspace_mode
            if sandbox_workspace_mode is not None
            else server.sandbox_workspace_mode
        ),
        sandbox_workspace_path=(
            sandbox_workspace_path
            if sandbox_workspace_path is not None
            else server.sandbox_workspace_path
        ),
        sandbox_network=(
            sandbox_network
            if sandbox_network is not None
            else server.sandbox_network
        ),
        sandbox_read_only=(
            sandbox_read_only
            if sandbox_read_only is not None
            else server.sandbox_read_only
        ),
    )
    if next_name != server.name:
        duplicate = db.scalar(
            select(MCPServer).where(
                MCPServer.workspace_id == server.workspace_id,
                MCPServer.name == next_name,
                MCPServer.id != server.id,
            )
        )
        if duplicate is not None:
            raise MCPConflict(f"An MCP server named {next_name!r} already exists in this workspace.")

    server.name = next_name
    server.endpoint = next_endpoint
    server.transport = next_transport
    server.auth_type = next_auth
    server.credential_id = next_credential
    server.trust_level = next_trust
    server.sandbox_backend = next_backend
    server.sandbox_image = next_image
    server.sandbox_workspace_mode = next_mode
    server.sandbox_workspace_path = next_path
    server.sandbox_network = next_network
    server.sandbox_read_only = next_read_only
    if description is not None:
        server.description = str(description)[:2000]
    if allowed_tools is not None:
        server.allowed_tools = _tool_list(allowed_tools, "allowed_tools")
    if denied_tools is not None:
        server.denied_tools = _tool_list(denied_tools, "denied_tools")
    if enabled is not None:
        server.enabled = bool(enabled)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise MCPConflict("MCP server name must be unique within a workspace.") from exc
    db.refresh(server)
    return server


def delete_server(db: Session, server_id: str) -> None:
    server = get_server(db, server_id)
    db.delete(server)
    db.commit()


def to_dict(server: MCPServer) -> dict[str, Any]:
    return {
        "id": server.id,
        "organization_id": server.organization_id,
        "workspace_id": server.workspace_id,
        "name": server.name,
        "description": server.description,
        "transport": server.transport,
        "endpoint": server.endpoint,
        "auth_type": server.auth_type,
        "credential_id": server.credential_id,
        "trust_level": server.trust_level,
        "allowed_tools": server.allowed_tools or [],
        "denied_tools": server.denied_tools or [],
        "enabled": server.enabled,
        "sandbox_backend": server.sandbox_backend,
        "sandbox_image": server.sandbox_image,
        "sandbox_workspace_mode": server.sandbox_workspace_mode,
        "sandbox_workspace_path": server.sandbox_workspace_path,
        "sandbox_network": server.sandbox_network,
        "sandbox_read_only": server.sandbox_read_only,
        "created_by": server.created_by,
        "created_at": server.created_at.isoformat() if server.created_at else None,
        "updated_at": server.updated_at.isoformat() if server.updated_at else None,
    }
