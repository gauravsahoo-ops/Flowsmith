"""Tenant/workspace-scoped MCP server registry API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.access import workspace_can_edit, workspace_can_view
from app.api.auth import get_current_user
from app.api.common import ok
from app.db import get_db
from app.models import User, Workspace
from app.tools.mcp import discovery as mcp_discovery
from app.tools.mcp import registry as mcp_registry
from app.tools.mcp.client_factory import build_stdio_client
from app.tools.mcp.credentials import resolve_mcp_auth_token
from app.tools.mcp.sandbox import SandboxError
from app.tools.mcp.transport_stdio import MCPTransportError

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp"])


class MCPServerCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=2000)
    transport: str = Field(default="http", max_length=16)
    auth_type: str = Field(default="none", max_length=16)
    credential_id: str | None = None
    description: str = Field(default="", max_length=2000)
    trust_level: str = Field(default="untrusted", max_length=16)
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    enabled: bool = True
    sandbox_backend: str = Field(default="subprocess", max_length=16)
    sandbox_image: str | None = Field(default=None, max_length=255)
    sandbox_workspace_mode: str = Field(default="none", max_length=16)
    sandbox_workspace_path: str | None = Field(default=None, max_length=2000)
    sandbox_network: str = Field(default="none", max_length=64)
    sandbox_read_only: bool = True


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    endpoint: str | None = Field(default=None, min_length=1, max_length=2000)
    transport: str | None = Field(default=None, max_length=16)
    auth_type: str | None = Field(default=None, max_length=16)
    credential_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    trust_level: str | None = Field(default=None, max_length=16)
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    enabled: bool | None = None
    sandbox_backend: str | None = Field(default=None, max_length=16)
    sandbox_image: str | None = Field(default=None, max_length=255)
    sandbox_workspace_mode: str | None = Field(default=None, max_length=16)
    sandbox_workspace_path: str | None = Field(default=None, max_length=2000)
    sandbox_network: str | None = Field(default=None, max_length=64)
    sandbox_read_only: bool | None = None


class MCPToolUpdate(BaseModel):
    risk_class: str | None = Field(default=None, max_length=32)
    enabled: bool | None = None


def _workspace(db: Session, workspace_id: str) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return workspace


def _require_view(db: Session, workspace_id: str, user: User) -> None:
    if not workspace_can_view(db, workspace_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


def _require_edit(db: Session, workspace_id: str, user: User) -> None:
    if not workspace_can_edit(db, workspace_id, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace edit access required.")


def _service_error(exc: mcp_registry.MCPServiceError) -> HTTPException:
    return HTTPException(
        exc.http_status,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("")
def list_mcp_servers(
    workspace_id: str = Query(...),
    include_disabled: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_view(db, workspace_id, user)
    rows = mcp_registry.list_servers(
        db, workspace_id=workspace_id, include_disabled=include_disabled
    )
    return ok([mcp_registry.to_dict(row) for row in rows])


@router.post("")
def create_mcp_server(
    body: MCPServerCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    workspace = _workspace(db, body.workspace_id)
    _require_edit(db, workspace.id, user)
    try:
        server = mcp_registry.create_server(
            db,
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            name=body.name,
            endpoint=body.endpoint,
            transport=body.transport,
            auth_type=body.auth_type,
            credential_id=body.credential_id,
            description=body.description,
            trust_level=body.trust_level,
            allowed_tools=body.allowed_tools,
            denied_tools=body.denied_tools,
            enabled=body.enabled,
            sandbox_backend=body.sandbox_backend,
            sandbox_image=body.sandbox_image,
            sandbox_workspace_mode=body.sandbox_workspace_mode,
            sandbox_workspace_path=body.sandbox_workspace_path,
            sandbox_network=body.sandbox_network,
            sandbox_read_only=body.sandbox_read_only,
            created_by=user.id,
        )
    except mcp_registry.MCPServiceError as exc:
        raise _service_error(exc) from exc
    return ok(mcp_registry.to_dict(server))


@router.get("/{server_id}")
def get_mcp_server(
    server_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        server = mcp_registry.get_server(db, server_id)
    except mcp_registry.MCPNotFound as exc:
        raise _service_error(exc) from exc
    _require_view(db, server.workspace_id, user)
    return ok(mcp_registry.to_dict(server))


@router.post("/{server_id}/discover")
async def discover_mcp_server_tools(
    server_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        server = mcp_registry.get_server(db, server_id)
    except mcp_registry.MCPNotFound as exc:
        raise _service_error(exc) from exc
    _require_edit(db, server.workspace_id, user)
    try:
        auth_token = resolve_mcp_auth_token(db, server, user.id)
    except mcp_registry.MCPServiceError as exc:
        raise _service_error(exc) from exc

    client: Any = None
    try:
        if server.transport == "stdio":
            # stdio servers receive the resolved secret through the child
            # environment; it is never placed in argv or logs. The sandbox
            # backend is selected by configuration and fails closed.
            env = {"MCP_AUTH_TOKEN": auth_token} if auth_token else None
            client = build_stdio_client(server, env=env)
        else:
            from app.ai.mcp_client import MCPClient

            client = MCPClient(server_url=server.endpoint, auth_token=auth_token)
        tools = await mcp_discovery.discover_and_cache(
            db,
            server,
            client=client,
            auth_token=auth_token,
        )
    except (MCPTransportError, SandboxError) as exc:
        raise _service_error(
            mcp_discovery.MCPDiscoveryError(
                "MCP_DISCOVERY_FAILED",
                "MCP transport could not be configured.",
                http_status=422,
            )
        ) from exc
    except mcp_discovery.MCPDiscoveryError as exc:
        raise _service_error(exc) from exc
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001 - cleanup must not mask discovery
                pass
    return ok([mcp_discovery.tool_to_dict(tool) for tool in tools])


@router.patch("/{server_id}/tools/{tool_id}")
def update_mcp_tool(
    server_id: str,
    tool_id: str,
    body: MCPToolUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        server = mcp_registry.get_server(db, server_id)
    except mcp_registry.MCPNotFound as exc:
        raise _service_error(exc) from exc
    _require_edit(db, server.workspace_id, user)
    try:
        tool = mcp_discovery.update_cached_tool(
            db,
            server,
            tool_id,
            risk_class=body.risk_class,
            enabled=body.enabled,
        )
    except mcp_discovery.MCPDiscoveryError as exc:
        raise _service_error(exc) from exc
    return ok(mcp_discovery.tool_to_dict(tool))


@router.patch("/{server_id}")
def update_mcp_server(
    server_id: str,
    body: MCPServerUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        existing = mcp_registry.get_server(db, server_id)
    except mcp_registry.MCPNotFound as exc:
        raise _service_error(exc) from exc
    _require_edit(db, existing.workspace_id, user)
    try:
        server = mcp_registry.update_server(
            db,
            server_id,
            name=body.name,
            endpoint=body.endpoint,
            transport=body.transport,
            auth_type=body.auth_type,
            credential_id=body.credential_id,
            description=body.description,
            trust_level=body.trust_level,
            allowed_tools=body.allowed_tools,
            denied_tools=body.denied_tools,
            enabled=body.enabled,
            sandbox_backend=body.sandbox_backend,
            sandbox_image=body.sandbox_image,
            sandbox_workspace_mode=body.sandbox_workspace_mode,
            sandbox_workspace_path=body.sandbox_workspace_path,
            sandbox_network=body.sandbox_network,
            sandbox_read_only=body.sandbox_read_only,
        )
    except mcp_registry.MCPServiceError as exc:
        raise _service_error(exc) from exc
    return ok(mcp_registry.to_dict(server))


@router.delete("/{server_id}")
def delete_mcp_server(
    server_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        existing = mcp_registry.get_server(db, server_id)
    except mcp_registry.MCPNotFound as exc:
        raise _service_error(exc) from exc
    _require_edit(db, existing.workspace_id, user)
    mcp_registry.delete_server(db, server_id)
    return ok({"deleted": True, "id": server_id})
