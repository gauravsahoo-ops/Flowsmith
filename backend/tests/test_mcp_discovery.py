"""MCP tool discovery and cache tests (service-level, no network)."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import MCPToolCache, MCPServer, Organization, User, Workspace
from app.tools.mcp import discovery as mcp_discovery

from tests.test_api.conftest import auth_headers, register


class FakeClient:
    """In-memory stand-in for ``MCPClient``: no transport is touched."""

    def __init__(self, tools):
        self.tools = tools
        self.calls: list[float] = []

    async def list_tools(self, timeout_s: float = 10.0):
        self.calls.append(timeout_s)
        return self.tools


def _user(db: Session, email: str) -> User:
    user = User(email=email, password_hash="x", role="member", active=True)
    db.add(user)
    db.flush()
    return user


def _workspace(db: Session, user: User, suffix: str) -> Workspace:
    org = Organization(
        id=f"org_disc_{suffix}",
        name=f"Discovery Org {suffix}",
        founder_id=user.id,
        is_public=False,
    )
    db.add(org)
    db.flush()
    workspace = Workspace(
        id=f"ws_disc_{suffix}",
        name=f"Discovery Workspace {suffix}",
        organization_id=org.id,
        creator_id=user.id,
        is_private=True,
    )
    db.add(workspace)
    db.commit()
    return workspace


def _server(db: Session, email: str, suffix: str, **overrides) -> MCPServer:
    user = _user(db, email)
    workspace = _workspace(db, user, suffix)
    values = {
        "id": f"mcp_disc_{suffix}",
        "organization_id": workspace.organization_id,
        "workspace_id": workspace.id,
        "name": f"Discovery {suffix}",
        "endpoint": "https://mcp.example.com",
        "transport": "http",
        "auth_type": "none",
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


def test_discovery_creates_cache_rows_with_conservative_risk():
    with get_session() as db:
        server = _server(db, "discovery_create@example.com", "create")
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        client = FakeClient(
            [
                {
                    "name": "search",
                    "description": "Search issues",
                    "inputSchema": schema,
                    "risk_class": "read_only",
                    "annotations": {"readOnlyHint": True},
                },
                {
                    "name": "fetch",
                    "description": "Fetch a record",
                    "inputSchema": {"type": "object"},
                },
            ]
        )

        tools = asyncio.run(
            mcp_discovery.discover_and_cache(
                db, server, client=client, timeout_s=3.5
            )
        )

        assert client.calls == [3.5]
        by_name = {tool.tool_name: tool for tool in tools}
        assert set(by_name) == {"fetch", "search"}
        assert by_name["search"].enabled is True
        assert by_name["search"].description == "Search issues"
        assert by_name["search"].input_schema == schema
        assert by_name["search"].risk_class == "write"
        assert by_name["fetch"].risk_class == "write"
        assert by_name["search"].schema_hash == mcp_discovery.schema_hash(schema)


def test_discovery_upserts_changed_tools_and_disables_missing_ones():
    with get_session() as db:
        server = _server(db, "discovery_upsert@example.com", "upsert")
        original_schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}, "limit": {"type": "integer"}},
        }
        first = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [
                        {
                            "name": "search",
                            "description": "Search v1",
                            "inputSchema": original_schema,
                        },
                        {
                            "name": "fetch",
                            "description": "Fetch",
                            "inputSchema": {"type": "object"},
                        },
                    ]
                ),
            )
        )
        by_name = {tool.tool_name: tool for tool in first}
        search_id = by_name["search"].id
        original_hash = by_name["search"].schema_hash

        # Reordered keys are the same schema; a new property is a new schema.
        reordered_schema = {
            "properties": {"limit": {"type": "integer"}, "q": {"type": "string"}},
            "type": "object",
        }
        second = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [
                        {
                            "name": "search",
                            "description": "Search v2",
                            "inputSchema": reordered_schema,
                        },
                        {
                            "name": "new_tool",
                            "description": "New",
                            "inputSchema": {"type": "object"},
                        },
                    ]
                ),
            )
        )
        by_name = {tool.tool_name: tool for tool in second}
        assert set(by_name) == {"fetch", "new_tool", "search"}
        assert by_name["search"].id == search_id
        assert by_name["search"].description == "Search v2"
        assert by_name["search"].schema_hash == original_hash
        assert by_name["fetch"].enabled is False
        assert by_name["new_tool"].enabled is True

        changed_schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "limit": {"type": "integer"},
                "cursor": {"type": "string"},
            },
        }
        third = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [
                        {
                            "name": "search",
                            "description": "Search v3",
                            "inputSchema": changed_schema,
                        },
                        {"name": "new_tool", "inputSchema": {"type": "object"}},
                    ]
                ),
            )
        )
        by_name = {tool.tool_name: tool for tool in third}
        assert by_name["search"].schema_hash != original_hash
        assert by_name["fetch"].enabled is False


def test_schema_hash_matches_canonical_json_sha256():
    schema = {
        "type": "object",
        "properties": {"b": {"type": "integer"}, "a": {"type": "string"}},
    }
    expected = hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    reordered = {
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "type": "object",
    }

    assert mcp_discovery.schema_hash(schema) == expected
    assert mcp_discovery.schema_hash(reordered) == expected
    assert (
        mcp_discovery.schema_hash({**schema, "additionalProperties": False})
        != expected
    )


def test_discovery_requires_credential_when_no_client_or_token():
    with get_session() as db:
        server = _server(
            db,
            "discovery_auth@example.com",
            "auth",
            auth_type="bearer",
        )
        with pytest.raises(mcp_discovery.MCPDiscoveryError) as excinfo:
            asyncio.run(mcp_discovery.discover_and_cache(db, server))
        assert excinfo.value.code == "MCP_CREDENTIAL_REQUIRED"
        assert excinfo.value.http_status == 422

        # An injected client is an explicit credential boundary bypass.
        tools = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [{"name": "search", "inputSchema": {"type": "object"}}]
                ),
            )
        )
        assert [tool.tool_name for tool in tools] == ["search"]


def test_discovery_rejects_disabled_server_before_calling_client():
    with get_session() as db:
        server = _server(
            db,
            "discovery_disabled@example.com",
            "disabled",
            enabled=False,
        )
        client = FakeClient([{"name": "search", "inputSchema": {"type": "object"}}])

        with pytest.raises(mcp_discovery.MCPDiscoveryError) as excinfo:
            asyncio.run(
                mcp_discovery.discover_and_cache(db, server, client=client)
            )

        assert excinfo.value.code == "MCP_SERVER_DISABLED"
        assert client.calls == []


def test_discovery_normalizes_malformed_tool_entries():
    with get_session() as db:
        server = _server(db, "discovery_normalize@example.com", "normalize")
        tools = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [
                        "not-a-dict",
                        {"description": "missing name"},
                        {"name": "   "},
                        {
                            "name": "  search  ",
                            "description": "Search",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                            },
                        },
                        {"name": "no_schema"},
                        {
                            "name": "bad_schema",
                            "description": 123,
                            "inputSchema": ["not", "an", "object"],
                        },
                    ]
                ),
            )
        )
        by_name = {tool.tool_name: tool for tool in tools}
        assert set(by_name) == {"search", "no_schema", "bad_schema"}
        assert by_name["search"].tool_name == "search"
        assert by_name["search"].input_schema["properties"]["q"]["type"] == "string"
        assert by_name["no_schema"].input_schema == {
            "type": "object",
            "properties": {},
        }
        assert by_name["bad_schema"].description == ""
        assert by_name["bad_schema"].input_schema == {
            "type": "object",
            "properties": {},
        }

        with pytest.raises(mcp_discovery.MCPDiscoveryError) as excinfo:
            mcp_discovery.normalize_tools({"tools": []})
        assert excinfo.value.code == "MCP_DISCOVERY_FAILED"


def test_discover_api_returns_credential_code_without_network(client):
    registered = register(client, email="discovery_api@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]

    with get_session() as db:
        user = db.get(User, user_id)
        assert user is not None
        workspace = _workspace(db, user, "api")
        db.add(
            MCPServer(
                id="mcp_disc_api",
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                name="Bearer Discovery",
                endpoint="https://mcp.example.com",
                transport="http",
                auth_type="bearer",
                credential_id=None,
                trust_level="untrusted",
                allowed_tools=[],
                denied_tools=[],
                enabled=True,
            )
        )
        db.commit()

    response = client.post(
        "/api/mcp/servers/mcp_disc_api/discover", headers=headers
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "MCP_CREDENTIAL_REQUIRED"


def test_discovery_transport_failure_does_not_disable_cache():
    with get_session() as db:
        server = _server(db, "discovery_fail@example.com", "fail")
        asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [{"name": "search", "inputSchema": {"type": "object"}}]
                ),
            )
        )

        class FailingClient:
            async def list_tools_strict(self, timeout_s: float = 10.0):
                raise RuntimeError("transport down")

        with pytest.raises(mcp_discovery.MCPDiscoveryError) as exc_info:
            asyncio.run(
                mcp_discovery.discover_and_cache(db, server, client=FailingClient())
            )
        assert exc_info.value.code == "MCP_DISCOVERY_FAILED"
        cached = list(
            db.scalars(
                select(MCPToolCache).where(MCPToolCache.server_id == server.id)
            ).all()
        )
        assert cached[0].enabled is True

def test_update_cached_tool_risk_and_enabled():
    with get_session() as db:
        server = _server(db, "discovery_policy@example.com", "policy")
        rows = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [
                        {
                            "name": "search",
                            "description": "Search",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                ),
            )
        )
        tool = rows[0]
        updated = mcp_discovery.update_cached_tool(
            db,
            server,
            tool.id,
            risk_class="read_only",
            enabled=False,
        )
        assert updated.risk_class == "read_only"
        assert updated.enabled is False
        with pytest.raises(mcp_discovery.MCPDiscoveryError) as exc_info:
            mcp_discovery.update_cached_tool(
                db, server, tool.id, risk_class="not-a-risk"
            )
        assert exc_info.value.code == "MCP_RISK_INVALID"


def test_update_mcp_tool_api(client):
    registered = register(client, email="mcp_policy_api@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]

    with get_session() as db:
        user = db.get(User, user_id)
        assert user is not None
        workspace = _workspace(db, user, "policy_api")
        server = MCPServer(
            id="mcp_policy_api",
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            name="Policy API",
            endpoint="https://mcp.example.com",
            transport="http",
            auth_type="none",
            trust_level="untrusted",
            allowed_tools=[],
            denied_tools=[],
            enabled=True,
            created_by=user_id,
        )
        db.add(server)
        db.commit()
        tools = asyncio.run(
            mcp_discovery.discover_and_cache(
                db,
                server,
                client=FakeClient(
                    [{"name": "search", "description": "Search", "inputSchema": {"type": "object"}}]
                ),
            )
        )
        tool_id = tools[0].id

    response = client.patch(
        f"/api/mcp/servers/mcp_policy_api/tools/{tool_id}",
        json={"risk_class": "read_only", "enabled": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["risk_class"] == "read_only"
    assert data["enabled"] is False

    invalid = client.patch(
        f"/api/mcp/servers/mcp_policy_api/tools/{tool_id}",
        json={"risk_class": "bogus"},
        headers=headers,
    )
    assert invalid.status_code == 422, invalid.text
