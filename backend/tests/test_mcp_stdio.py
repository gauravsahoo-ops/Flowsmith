"""MCP stdio transport and credential resolution tests.

Credential tests are service-level: they use the real encrypted credential
store but never touch the network. The stdio test spawns a tiny inline Python
JSON-RPC server via ``sys.executable`` so it exercises the real pipes without
depending on an external MCP server.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from app.db import get_session
from app.models import Credential, MCPServer, Organization, User, Workspace
from app.security.crypto import encrypt_text
from app.tools.mcp import credentials as mcp_credentials
from app.tools.mcp.discovery import MCPDiscoveryError
from app.tools.mcp.transport_stdio import (
    MCPProtocolError,
    StdioMCPClient,
    parse_stdio_command,
)

STDIO_SERVER = r"""
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        # Notification (notifications/initialized) has no response.
        continue
    if method == "initialize":
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test-stdio", "version": "1.0.0"},
            },
        }
    elif method == "ping":
        response = {"jsonrpc": "2.0", "id": request_id, "result": {}}
    elif method == "tools/list":
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }
                ]
            },
        }
    elif method == "tools/call":
        params = request.get("params") or {}
        text = (params.get("arguments") or {}).get("text", "")
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(text)}],
                "isError": False,
            },
        }
    else:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
"""


def _user(db, suffix: str) -> User:
    user = User(
        email=f"mcp_stdio_{suffix}@example.com",
        password_hash="x",
        role="member",
        active=True,
    )
    db.add(user)
    db.flush()
    return user


def _workspace(db, user: User, suffix: str) -> Workspace:
    org = Organization(
        id=f"org_stdio_{suffix}",
        name=f"Stdio Org {suffix}",
        founder_id=user.id,
        is_public=False,
    )
    db.add(org)
    db.flush()
    workspace = Workspace(
        id=f"ws_stdio_{suffix}",
        name=f"Stdio Workspace {suffix}",
        organization_id=org.id,
        creator_id=user.id,
        is_private=True,
    )
    db.add(workspace)
    db.commit()
    return workspace


def _credential(
    db,
    user: User,
    suffix: str,
    cred_type: str,
    payload: dict,
) -> Credential:
    credential = Credential(
        id=f"cred_mcp_{suffix}",
        user_id=user.id,
        name=f"MCP credential {suffix}",
        type=cred_type,
        data=encrypt_text(json.dumps(payload)),
    )
    db.add(credential)
    db.commit()
    return credential


def _server(
    db,
    workspace: Workspace,
    suffix: str,
    **overrides,
) -> MCPServer:
    values = {
        "id": f"mcp_stdio_{suffix}",
        "organization_id": workspace.organization_id,
        "workspace_id": workspace.id,
        "name": f"Stdio {suffix}",
        "endpoint": "https://mcp.example.com",
        "transport": "http",
        "auth_type": "none",
        "credential_id": None,
        "trust_level": "untrusted",
        "allowed_tools": [],
        "denied_tools": [],
        "enabled": True,
    }
    values.update(overrides)
    server = MCPServer(**values)
    db.add(server)
    db.commit()
    return server


def test_parse_stdio_command_splits_quoted_arguments():
    assert parse_stdio_command('python -m "my server" --flag') == [
        "python",
        "-m",
        "my server",
        "--flag",
    ]
    assert parse_stdio_command(["python", "-m", "my server"]) == [
        "python",
        "-m",
        "my server",
    ]


def test_stdio_client_round_trip_and_normalization():
    async def scenario() -> None:
        client = StdioMCPClient(
            [sys.executable, "-c", STDIO_SERVER],
            timeout_s=10.0,
        )
        try:
            assert await client.ping() is True

            tools = await client.list_tools(timeout_s=10.0)
            assert [tool["name"] for tool in tools] == ["echo"]
            assert tools[0]["inputSchema"]["properties"]["text"]["type"] == "string"

            result = await client.call_tool(
                "echo",
                {"text": "hello"},
                timeout_s=10.0,
            )
            assert result["tool"] == "echo"
            assert result["content"] == "hello"
            assert result["is_error"] is False
            assert result["content_count"] == 1
            assert result["raw_result"]["content"][0]["text"] == "hello"
            assert result["capability_type"] == "MCP_TOOL"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stdio_client_raises_on_invalid_protocol_response():
    script = "import sys; sys.stdout.write('not-json\\n'); sys.stdout.flush(); sys.stdin.read()"

    async def scenario() -> None:
        client = StdioMCPClient([sys.executable, "-c", script], timeout_s=10.0)
        try:
            with pytest.raises(MCPProtocolError):
                await client.list_tools(timeout_s=10.0)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stdio_timeout_kills_child_process():
    script = "import time; time.sleep(30)"

    async def scenario() -> None:
        client = StdioMCPClient([sys.executable, "-c", script], timeout_s=0.25)
        try:
            with pytest.raises(TimeoutError):
                await client.list_tools(timeout_s=0.25)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_resolve_mcp_auth_token_none_needs_no_credential():
    with get_session() as db:
        user = _user(db, "none")
        workspace = _workspace(db, user, "none")
        server = _server(db, workspace, "none")

        assert mcp_credentials.resolve_mcp_auth_token(db, server, user.id) is None


@pytest.mark.parametrize(
    ("key", "cred_type"),
    [
        ("token", "bearer_auth"),
        ("api_key", "api_key"),
        ("access_token", "github"),
        ("private_token", "hubspot"),
        ("bearer_token", "elasticsearch"),
    ],
)
def test_resolve_mcp_auth_token_extracts_supported_fields(key: str, cred_type: str):
    with get_session() as db:
        user = _user(db, key)
        workspace = _workspace(db, user, key)
        credential = _credential(
            db,
            user,
            key,
            cred_type,
            {key: f"secret-{key}"},
        )
        server = _server(
            db,
            workspace,
            key,
            auth_type="credential",
            credential_id=credential.id,
        )

        assert (
            mcp_credentials.resolve_mcp_auth_token(db, server, user.id)
            == f"secret-{key}"
        )


def test_resolve_mcp_auth_token_prefers_first_supported_key():
    with get_session() as db:
        user = _user(db, "precedence")
        workspace = _workspace(db, user, "precedence")
        credential = _credential(
            db,
            user,
            "precedence",
            "bearer_auth",
            {
                "bearer_token": "last",
                "private_token": "fourth",
                "access_token": "third",
                "api_key": "second",
                "token": "first",
            },
        )
        server = _server(
            db,
            workspace,
            "precedence",
            auth_type="bearer",
            credential_id=credential.id,
        )

        assert (
            mcp_credentials.resolve_mcp_auth_token(db, server, user.id) == "first"
        )


def test_resolve_mcp_auth_token_requires_configured_credential():
    with get_session() as db:
        user = _user(db, "missing_ref")
        workspace = _workspace(db, user, "missing_ref")
        server = _server(db, workspace, "missing_ref", auth_type="bearer")

        with pytest.raises(MCPDiscoveryError) as excinfo:
            mcp_credentials.resolve_mcp_auth_token(db, server, user.id)

        assert excinfo.value.code == "MCP_CREDENTIAL_REQUIRED"
        assert excinfo.value.http_status == 422


def test_resolve_mcp_auth_token_rejects_foreign_credential():
    with get_session() as db:
        owner = _user(db, "owner")
        intruder = _user(db, "intruder")
        workspace = _workspace(db, owner, "foreign")
        credential = _credential(
            db,
            owner,
            "foreign",
            "bearer_auth",
            {"token": "owner-secret"},
        )
        server = _server(
            db,
            workspace,
            "foreign",
            auth_type="bearer",
            credential_id=credential.id,
        )

        with pytest.raises(MCPDiscoveryError) as excinfo:
            mcp_credentials.resolve_mcp_auth_token(db, server, intruder.id)

        assert excinfo.value.code == "MCP_CREDENTIAL_REQUIRED"
        assert "owner-secret" not in str(excinfo.value)


def test_resolve_mcp_auth_token_rejects_credential_without_token():
    with get_session() as db:
        user = _user(db, "no_token")
        workspace = _workspace(db, user, "no_token")
        credential = _credential(
            db,
            user,
            "no_token",
            "github",
            {"login": "octocat", "password": "super-secret"},
        )
        server = _server(
            db,
            workspace,
            "no_token",
            auth_type="credential",
            credential_id=credential.id,
        )

        with pytest.raises(MCPDiscoveryError) as excinfo:
            mcp_credentials.resolve_mcp_auth_token(db, server, user.id)

        assert excinfo.value.code == "MCP_CREDENTIAL_REQUIRED"
        assert "super-secret" not in str(excinfo.value)
