"""MCP registry package."""

from app.tools.mcp.registry import (
    AUTH_TYPES,
    TRANSPORTS,
    TRUST_LEVELS,
    MCPConflict,
    MCPNotFound,
    MCPServiceError,
    create_server,
    delete_server,
    get_server,
    list_servers,
    to_dict,
    update_server,
)
from app.tools.mcp.policy import (
    descriptor_from_tool,
    descriptors_from_tools,
    evaluate_tool_policy,
)
from app.tools.mcp.client_factory import build_mcp_client, build_stdio_client
from app.tools.mcp.executor import invoke_tool
from app.tools.mcp.discovery import (
    DEFAULT_RISK_CLASS,
    MCPDiscoveryError,
    discover_and_cache,
    normalize_tools,
    schema_hash,
    tool_to_dict,
)
from app.tools.mcp.credentials import resolve_mcp_auth_token
from app.tools.mcp.transport_stdio import (
    MCPProtocolError,
    MCPTransportError,
    StdioMCPClient,
)

__all__ = [
    "AUTH_TYPES",
    "DEFAULT_RISK_CLASS",
    "TRANSPORTS",
    "TRUST_LEVELS",
    "MCPConflict",
    "MCPDiscoveryError",
    "MCPNotFound",
    "MCPProtocolError",
    "MCPServiceError",
    "MCPTransportError",
    "StdioMCPClient",
    "build_mcp_client",
    "build_stdio_client",
    "create_server",
    "delete_server",
    "descriptor_from_tool",
    "descriptors_from_tools",
    "discover_and_cache",
    "evaluate_tool_policy",
    "get_server",
    "invoke_tool",
    "list_servers",
    "normalize_tools",
    "resolve_mcp_auth_token",
    "schema_hash",
    "to_dict",
    "tool_to_dict",
    "update_server",
]
