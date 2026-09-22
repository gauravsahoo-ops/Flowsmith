"""Model Context Protocol (MCP) Client for Flowsmith.

Allows Flowsmith AI Agents to connect to external MCP servers (stdio, SSE, HTTP),
discover their tools dynamically, and execute them as standard workflow tools.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.ai.tools import ToolSpec

logger = logging.getLogger("ai.mcp_client")


class MCPClient:
    """Client for communicating with external MCP (Model Context Protocol) servers."""

    def __init__(self, server_url: str, headers: dict[str, str] | None = None) -> None:
        self.server_url = server_url.rstrip("/")
        self.headers = headers or {"Content-Type": "application/json"}
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def list_tools(self, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        """Query the MCP server for declared tools (`tools/list`)."""
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
                logger.error("MCP server %s error (%d): %s", self.server_url, resp.status_code, resp.text[:200])
                return []
            body = resp.json()
            result = body.get("result") or {}
            return result.get("tools") or []
        except Exception as exc:
            logger.warning("Failed to list tools from MCP server %s: %s", self.server_url, exc)
            return []

    async def call_tool(self, name: str, arguments: dict[str, Any], timeout_s: float = 30.0) -> Any:
        """Call a specific tool on the MCP server (`tools/call`)."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(self.server_url, headers=self.headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"MCP tool '{name}' call failed ({resp.status_code}): {resp.text[:300]}")
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"MCP tool '{name}' error: {body['error']}")
        result = body.get("result") or {}
        content = result.get("content") or []
        # Return aggregated text from content items
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(text_parts) if text_parts else result

    def convert_to_tool_specs(self, mcp_tools: list[dict[str, Any]]) -> list[ToolSpec]:
        """Convert MCP tool declarations into Flowsmith ToolSpec objects."""
        specs = []
        for t in mcp_tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}

            async def _handler(ctx: Any, args: dict[str, Any], tool_name: str = name) -> Any:
                return await self.call_tool(tool_name, args)

            specs.append(ToolSpec(
                name=f"mcp_{name}",
                description=f"[MCP] {desc}",
                parameters=schema,
                handler=_handler,
                category="mcp",
            ))
        return specs
