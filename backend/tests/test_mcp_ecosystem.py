"""Tests for MCP Ecosystem Expansion (Phase 40G).

Verifies:
- MCP server registration and discovery
- MCP tools listing and schema ingestion
- MCP tool call execution with result normalization
- MCP security validation (blocking cloud metadata endpoints)
- Clear separation between MCP capabilities and native connectors
"""

import pytest
import respx
import httpx
from app.ai.mcp_client import MCPClient, MCPRegistry, MCPSecurityError


@pytest.mark.asyncio
async def test_mcp_client_tool_discovery_and_call():
    client = MCPClient("https://mcp.example.com")

    with respx.mock(base_url="https://mcp.example.com") as mock_server:
        # Mock tools/list
        mock_server.post("/").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "tools": [
                                {
                                    "name": "search_docs",
                                    "description": "Search documentation",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"query": {"type": "string"}},
                                        "required": ["query"],
                                    },
                                }
                            ]
                        },
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "content": [
                                {"type": "text", "text": "Results found: 5 documents matched query."}
                            ],
                            "isError": False,
                        },
                    },
                ),
            ]
        )

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "search_docs"

        # Execute call
        result = await client.call_tool("search_docs", {"query": "authentication"})
        assert result["tool"] == "search_docs"
        assert result["content"] == "Results found: 5 documents matched query."
        assert result["capability_type"] == "MCP_TOOL"
        assert result["is_error"] is False


@pytest.mark.asyncio
async def test_mcp_security_blocks_metadata():
    client = MCPClient("http://169.254.169.254/latest/meta-data")
    with pytest.raises(MCPSecurityError):
        await client.list_tools()


@pytest.mark.asyncio
async def test_mcp_registry():
    registry = MCPRegistry()
    registry.register_server(
        name="github_mcp",
        server_url="https://mcp-github.example.com",
        description="GitHub MCP Tools",
        category="developer",
    )

    servers = registry.list_servers()
    assert len(servers) == 1
    assert servers[0]["name"] == "github_mcp"

    srv = registry.get_server("github_mcp")
    assert srv is not None
    assert srv.server_url == "https://mcp-github.example.com"
