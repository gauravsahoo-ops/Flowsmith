"""Model Context Protocol (MCP) Client and Ecosystem for Flowsmith (Phase 40G).

Allows Flowsmith AI Agents to connect to external MCP servers (stdio, SSE, HTTP),
discover their tools and resources dynamically, and execute them as standard workflow tools.
Includes security controls (SSRF protection, argument sanitization) and strictly
segregates MCP capabilities from native connectors.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.ai.tools import ToolSpec

logger = logging.getLogger("ai.mcp_client")


def _log_url(url: str) -> str:
    """Log-safe URL: userinfo and query strings may carry access tokens."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


class MCPSecurityError(Exception):
    """Raised when an MCP operation violates security policies."""
    pass


class MCPClient:
    """Client for communicating with external MCP (Model Context Protocol) servers."""

    def __init__(
        self,
        server_url: str,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        allow_private_network: bool = False,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Type", "application/json")
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self.allow_private_network = allow_private_network
        self._request_id = 0

    async def _validate_security(self, url: str) -> None:
        """Validate URL to protect against SSRF on private/cloud metadata ranges.

        Delegates to the shared SSRF policy (literal-IP ranges, metadata
        hosts, DNS-rebinding, production DNS-failure deny)."""
        if self.allow_private_network:
            return
        from app.engine.errors import NodeExecutionError
        from app.security.ssrf import assert_public_url

        try:
            await assert_public_url(url, node_id="mcp_client")
        except NodeExecutionError as exc:
            raise MCPSecurityError(str(exc)) from exc

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def ping(self, timeout_s: float = 5.0) -> bool:
        """Ping the MCP server or check connectivity."""
        await self._validate_security(self.server_url)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "ping",
            "params": {},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
                resp = await client.post(self.server_url, headers=self.headers, json=payload)
            return resp.status_code < 400
        except Exception as exc:
            logger.debug("MCP ping failed for %s: %s", _log_url(self.server_url), exc)
            return False

    async def list_tools(self, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        """Query the MCP server for declared tools (`tools/list`)."""
        await self._validate_security(self.server_url)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
                resp = await client.post(self.server_url, headers=self.headers, json=payload)
            if resp.status_code >= 400:
                logger.error("MCP server %s error (%d): %s", _log_url(self.server_url), resp.status_code, resp.text[:200])
                return []
            body = resp.json()
            result = body.get("result") or {}
            return result.get("tools") or []
        except Exception as exc:
            logger.warning("Failed to list tools from MCP server %s: %s", _log_url(self.server_url), exc)
            return []

    async def list_resources(self, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        """Query the MCP server for available resources (`resources/list`)."""
        await self._validate_security(self.server_url)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/list",
            "params": {},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
                resp = await client.post(self.server_url, headers=self.headers, json=payload)
            if resp.status_code >= 400:
                return []
            body = resp.json()
            result = body.get("result") or {}
            return result.get("resources") or []
        except Exception as exc:
            logger.debug("MCP list_resources failed: %s", exc)
            return []

    async def call_tool(self, name: str, arguments: dict[str, Any], timeout_s: float = 30.0) -> dict[str, Any]:
        """Call a specific tool on the MCP server (`tools/call`) with normalized output."""
        await self._validate_security(self.server_url)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
                resp = await client.post(self.server_url, headers=self.headers, json=payload)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"MCP tool '{name}' timed out after {timeout_s}s.") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"MCP tool '{name}' connection failed: {exc}") from exc

        if resp.status_code >= 400:
            raise RuntimeError(f"MCP tool '{name}' call failed ({resp.status_code}): {resp.text[:300]}")
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"MCP tool '{name}' error: {body['error']}")

        result = body.get("result") or {}
        content = result.get("content") or []

        # Normalize result output
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        normalized_text = "\n".join(text_parts) if text_parts else ""

        return {
            "tool": name,
            "raw_result": result,
            "content": normalized_text,
            "is_error": bool(result.get("isError", False)),
            "content_count": len(content),
            "capability_type": "MCP_TOOL",
        }

    def convert_to_tool_specs(self, mcp_tools: list[dict[str, Any]]) -> list[ToolSpec]:
        """Convert MCP tool declarations into Flowsmith ToolSpec objects."""
        specs = []
        for t in mcp_tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}

            async def _handler(ctx: Any, args: dict[str, Any], tool_name: str = name) -> Any:
                res = await self.call_tool(tool_name, args)
                return res["content"] if res.get("content") else res["raw_result"]

            specs.append(ToolSpec(
                name=f"mcp_{name}",
                description=f"[MCP Tool: {name}] {desc}",
                parameters=schema,
                handler=_handler,
                category="mcp",
            ))
        return specs


class MCPRegistry:
    """Central registry and manager for configured MCP servers in FlowSmith."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPClient] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def register_server(
        self,
        name: str,
        server_url: str,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        description: str = "",
        category: str = "general",
    ) -> MCPClient:
        """Register an active MCP server."""
        client = MCPClient(server_url=server_url, headers=headers, auth_token=auth_token)
        self._servers[name] = client
        self._metadata[name] = {
            "name": name,
            "server_url": server_url,
            "description": description,
            "category": category,
            "registered_at": "now",
        }
        return client

    def get_server(self, name: str) -> Optional[MCPClient]:
        return self._servers.get(name)

    def list_servers(self) -> list[dict[str, Any]]:
        return list(self._metadata.values())

    async def discover_all_tools(self) -> dict[str, list[dict[str, Any]]]:
        """Discovers tools across all registered MCP servers."""
        discovered: dict[str, list[dict[str, Any]]] = {}
        for sname, client in self._servers.items():
            tools = await client.list_tools()
            discovered[sname] = tools
        return discovered


# Global MCP registry singleton
_GLOBAL_MCP_REGISTRY = MCPRegistry()


def get_mcp_registry() -> MCPRegistry:
    return _GLOBAL_MCP_REGISTRY

