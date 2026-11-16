"""Client factories for MCP transports.

Callers that create a stdio client own its lifetime and must ``close()`` it in
a ``finally`` block. HTTP/SSE clients are stateless per request. Resolved stdio
secrets are only ever placed in the child environment; they never appear in
argv, logs, or error messages. HTTP/SSE tokens continue to use the existing
Authorization header.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.config import Settings, get_settings
from app.tools.mcp.sandbox import (
    MCPSandbox,
    build_sandbox,
)
from app.tools.mcp.transport_stdio import StdioMCPClient


def build_stdio_client(
    server: Any,
    *,
    env: Mapping[str, str] | None = None,
    settings: Settings | None = None,
    sandbox: MCPSandbox | None = None,
) -> StdioMCPClient:
    """Build a stdio client from the server's effective sandbox policy.

    Per-server fields take precedence; empty fields fall back to the global
    ``MCP_STDIO_*`` settings inside :func:`build_sandbox`.
    """
    resolved = settings or get_settings()
    server_id = str(getattr(server, "id", "") or "")
    backend = getattr(server, "sandbox_backend", None)
    image = getattr(server, "sandbox_image", None)
    workspace_mode = getattr(server, "sandbox_workspace_mode", None)
    workspace_path = getattr(server, "sandbox_workspace_path", None)
    network = getattr(server, "sandbox_network", None)
    read_only = getattr(server, "sandbox_read_only", None)
    if sandbox is None:
        sandbox = build_sandbox(
            resolved,
            server_id=server_id,
            backend=backend,
            image=image,
            workspace_mode=workspace_mode,
            workspace_path=workspace_path,
            network=network,
            read_only=read_only,
        )
    return StdioMCPClient(
        command=getattr(server, "endpoint", ""),
        env=env,
        timeout_s=float(getattr(resolved, "mcp_stdio_timeout_s", 30.0)),
        close_timeout_s=float(
            getattr(resolved, "mcp_stdio_close_timeout_s", 5.0)
        ),
        max_memory_mb=int(
            getattr(resolved, "mcp_stdio_sandbox_memory_mb", 256)
        ),
        max_cpu_seconds=int(
            getattr(resolved, "mcp_stdio_sandbox_cpu_seconds", 60)
        ),
        sandbox=sandbox,
        server_id=server_id,
        sandbox_workspace_mode=str(workspace_mode or "none"),
        sandbox_workspace=workspace_path or None,
        sandbox_workspace_read_only=read_only,
        sandbox_image=str(image or ""),
        sandbox_network=str(network or "none"),
    )


def build_mcp_client(
    server: Any,
    *,
    auth_token: str | None = None,
    headers: dict[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build the client matching ``server.transport``.

    stdio servers receive the resolved token through ``MCP_AUTH_TOKEN`` in the
    child environment. HTTP/SSE servers receive it as a bearer header through
    the existing MCP client.
    """
    transport = str(getattr(server, "transport", "http") or "http").strip().lower()
    if transport == "stdio":
        stdio_env = {str(key): str(value) for key, value in (env or {}).items()}
        if auth_token:
            stdio_env.setdefault("MCP_AUTH_TOKEN", str(auth_token))
        return build_stdio_client(
            server,
            env=stdio_env or None,
            settings=settings,
        )

    from app.ai.mcp_client import MCPClient

    return MCPClient(
        server_url=str(getattr(server, "endpoint", "") or ""),
        headers=headers,
        auth_token=auth_token,
    )
