"""MCP server registry service and API tests."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db import get_session
from app.models import MCPServer, Organization, User, Workspace
from app.platform.contracts import PolicyOutcome, RiskClass
from app.tools.mcp import policy as mcp_policy
from app.tools.mcp import registry as mcp_registry
from app.tools.mcp.executor import invoke_tool

from tests.test_api.conftest import auth_headers, register


def _owner(db, email: str) -> User:
    user = User(email=email, password_hash="x", role="member", active=True)
    db.add(user)
    db.flush()
    return user


def _workspace(db, user: User, suffix: str) -> tuple[Organization, Workspace]:
    org = Organization(
        id=f"org_mcp_{suffix}",
        name=f"MCP Org {suffix}",
        founder_id=user.id,
        is_public=False,
    )
    db.add(org)
    db.flush()
    workspace = Workspace(
        id=f"ws_mcp_{suffix}",
        name=f"MCP Workspace {suffix}",
        organization_id=org.id,
        creator_id=user.id,
        is_private=True,
    )
    db.add(workspace)
    db.commit()
    return org, workspace


def test_create_update_list_delete_server():
    with get_session() as db:
        user = _owner(db, "mcp_owner@example.com")
        org, workspace = _workspace(db, user, "service")
        server = mcp_registry.create_server(
            db,
            organization_id=org.id,
            workspace_id=workspace.id,
            name="GitHub MCP",
            endpoint="https://mcp.example.com",
            allowed_tools=["search", "get_file"],
            created_by=user.id,
        )
        assert server.trust_level == "untrusted"
        assert server.allowed_tools == ["get_file", "search"]

        listed = mcp_registry.list_servers(db, workspace_id=workspace.id)
        assert [item.id for item in listed] == [server.id]

        updated = mcp_registry.update_server(
            db,
            server.id,
            enabled=False,
            allowed_tools=["search"],
            trust_level="verified",
        )
        assert updated.enabled is False
        assert updated.trust_level == "verified"
        assert updated.allowed_tools == ["search"]

        mcp_registry.delete_server(db, server.id)
        assert mcp_registry.list_servers(db, workspace_id=workspace.id) == []


def test_validation_and_duplicate_name():
    with get_session() as db:
        user = _owner(db, "mcp_validation@example.com")
        org, workspace = _workspace(db, user, "validation")
        with pytest.raises(mcp_registry.MCPServiceError):
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Bad transport",
                endpoint="https://mcp.example.com",
                transport="carrier-pigeon",
            )
        with pytest.raises(mcp_registry.MCPServiceError):
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Bad endpoint",
                endpoint="mcp.example.com",
                transport="http",
            )
        with pytest.raises(mcp_registry.MCPServiceError):
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Missing credential",
                endpoint="https://mcp.example.com",
                auth_type="bearer",
            )

        mcp_registry.create_server(
            db,
            organization_id=org.id,
            workspace_id=workspace.id,
            name="Unique",
            endpoint="https://mcp.example.com",
        )
        with pytest.raises(mcp_registry.MCPConflict):
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Unique",
                endpoint="https://other.example.com",
            )


def test_mcp_server_api_crud(client):
    registered = register(client, email="mcp_api@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]

    with get_session() as db:
        org = Organization(
            id="org_mcp_api",
            name="MCP API Org",
            founder_id=user_id,
            is_public=False,
        )
        db.add(org)
        db.flush()
        db.add(
            Workspace(
                id="ws_mcp_api",
                name="MCP API Workspace",
                organization_id=org.id,
                creator_id=user_id,
                is_private=True,
            )
        )
        db.commit()

    created = client.post(
        "/api/mcp/servers",
        json={
            "workspace_id": "ws_mcp_api",
            "name": "Filesystem MCP",
            "endpoint": "https://mcp.example.com",
            "transport": "http",
            "allowed_tools": ["read_file"],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    server_id = created.json()["data"]["id"]

    listed = client.get("/api/mcp/servers?workspace_id=ws_mcp_api", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["data"]] == [server_id]

    patched = client.patch(
        f"/api/mcp/servers/{server_id}",
        json={"enabled": False, "denied_tools": ["delete_file"]},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["enabled"] is False
    assert patched.json()["data"]["denied_tools"] == ["delete_file"]

    deleted = client.delete(f"/api/mcp/servers/{server_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["deleted"] is True


def test_mcp_server_api_requires_auth(client):
    assert client.get("/api/mcp/servers?workspace_id=ws_mcp_api").status_code == 401


SANDBOX_IMAGE = "ghcr.io/flowsmith/mcp-runtime@sha256:" + "a" * 64


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_sandbox_fields_persist_and_update(tmp_path):
    with get_session() as db:
        user = _owner(db, "mcp_sandbox@example.com")
        org, workspace = _workspace(db, user, "sandbox")
        server = mcp_registry.create_server(
            db,
            organization_id=org.id,
            workspace_id=workspace.id,
            name="Docker MCP",
            endpoint="python -m mcp_server",
            transport="stdio",
            sandbox_backend="docker",
            sandbox_image=SANDBOX_IMAGE,
            sandbox_workspace_mode="configured",
            sandbox_workspace_path=str(tmp_path),
            sandbox_network="none",
            sandbox_read_only=True,
        )
        assert server.sandbox_backend == "docker"
        assert server.sandbox_image == SANDBOX_IMAGE
        assert server.sandbox_workspace_mode == "configured"
        assert server.sandbox_workspace_path == str(tmp_path)
        assert server.sandbox_network == "none"
        assert server.sandbox_read_only is True

        updated = mcp_registry.update_server(
            db,
            server.id,
            sandbox_workspace_mode="ephemeral",
            sandbox_workspace_path="",
            sandbox_read_only=False,
        )
        assert updated.sandbox_backend == "docker"
        assert updated.sandbox_workspace_mode == "ephemeral"
        assert updated.sandbox_workspace_path is None
        assert updated.sandbox_read_only is False

        payload = mcp_registry.to_dict(updated)
        assert payload["sandbox_backend"] == "docker"
        assert payload["sandbox_image"] == SANDBOX_IMAGE
        assert payload["sandbox_workspace_mode"] == "ephemeral"
        assert payload["sandbox_network"] == "none"
        assert payload["sandbox_read_only"] is False


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"sandbox_backend": "firecracker"}, "MCP_SANDBOX_BACKEND_INVALID"),
        (
            {"sandbox_workspace_mode": "shared"},
            "MCP_SANDBOX_WORKSPACE_MODE_INVALID",
        ),
        ({"sandbox_network": "host"}, "MCP_SANDBOX_POLICY"),
        (
            {"sandbox_backend": "docker", "sandbox_image": None},
            "MCP_SANDBOX_IMAGE_REQUIRED",
        ),
        (
            {
                "sandbox_backend": "docker",
                "sandbox_image": SANDBOX_IMAGE,
                "sandbox_workspace_mode": "configured",
                "sandbox_workspace_path": None,
            },
            "MCP_SANDBOX_WORKSPACE_REQUIRED",
        ),
    ],
)
def test_sandbox_policy_validation(monkeypatch, overrides, code):
    monkeypatch.setattr(mcp_registry, "get_settings", lambda: _settings())
    with get_session() as db:
        user = _owner(db, f"mcp_sandbox_invalid_{code.lower()}@example.com")
        org, workspace = _workspace(db, user, f"invalid_{code.lower()}")
        with pytest.raises(mcp_registry.MCPServiceError) as excinfo:
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Invalid sandbox",
                endpoint="python -m mcp_server",
                transport="stdio",
                **overrides,
            )
        assert excinfo.value.code == code


def test_sandbox_network_must_be_allowlisted(monkeypatch):
    settings = _settings(
        mcp_stdio_docker_network="mcp-net",
        mcp_stdio_docker_networks="mcp-net",
    )
    monkeypatch.setattr(mcp_registry, "get_settings", lambda: settings)
    with get_session() as db:
        user = _owner(db, "mcp_sandbox_net@example.com")
        org, workspace = _workspace(db, user, "sandbox_net")
        allowed = mcp_registry.create_server(
            db,
            organization_id=org.id,
            workspace_id=workspace.id,
            name="Allowlisted network",
            endpoint="python -m mcp_server",
            transport="stdio",
            sandbox_backend="docker",
            sandbox_image=SANDBOX_IMAGE,
            sandbox_network="mcp-net",
        )
        assert allowed.sandbox_network == "mcp-net"

        with pytest.raises(mcp_registry.MCPServiceError) as excinfo:
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Other network",
                endpoint="python -m mcp_server",
                transport="stdio",
                sandbox_backend="docker",
                sandbox_image=SANDBOX_IMAGE,
                sandbox_network="other-net",
            )
        assert excinfo.value.code == "MCP_SANDBOX_POLICY"


def test_production_subprocess_gate_uses_per_server_backend(monkeypatch):
    settings = _settings(
        app_env="production",
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=SANDBOX_IMAGE,
    )
    monkeypatch.setattr(mcp_registry, "get_settings", lambda: settings)
    with get_session() as db:
        user = _owner(db, "mcp_sandbox_prod@example.com")
        org, workspace = _workspace(db, user, "sandbox_prod")
        with pytest.raises(mcp_registry.MCPServiceError) as excinfo:
            mcp_registry.create_server(
                db,
                organization_id=org.id,
                workspace_id=workspace.id,
                name="Production subprocess",
                endpoint="python -m mcp_server",
                transport="stdio",
                sandbox_backend="subprocess",
            )
        assert excinfo.value.code == "MCP_SANDBOX_REQUIRED"

        allowed = mcp_registry.create_server(
            db,
            organization_id=org.id,
            workspace_id=workspace.id,
            name="Production docker",
            endpoint="python -m mcp_server",
            transport="stdio",
            sandbox_backend="docker",
            sandbox_image=SANDBOX_IMAGE,
        )
        assert allowed.sandbox_backend == "docker"


def test_docker_image_falls_back_to_global_default(monkeypatch):
    settings = _settings(mcp_stdio_docker_image=SANDBOX_IMAGE)
    monkeypatch.setattr(mcp_registry, "get_settings", lambda: settings)
    with get_session() as db:
        user = _owner(db, "mcp_sandbox_global_image@example.com")
        org, workspace = _workspace(db, user, "sandbox_global_image")
        server = mcp_registry.create_server(
            db,
            organization_id=org.id,
            workspace_id=workspace.id,
            name="Global image",
            endpoint="python -m mcp_server",
            transport="stdio",
            sandbox_backend="docker",
        )
        assert server.sandbox_image is None


def _server(**overrides) -> MCPServer:
    values = {
        "id": "mcp_srv_1",
        "organization_id": "org_1",
        "workspace_id": "ws_1",
        "name": "GitHub MCP",
        "endpoint": "https://mcp.example.com",
        "transport": "http",
        "auth_type": "none",
        "trust_level": "untrusted",
        "allowed_tools": ["search"],
        "denied_tools": ["delete_file"],
        "enabled": True,
    }
    values.update(overrides)
    return MCPServer(**values)


def test_mcp_policy_denies_disabled_denied_and_non_allowlisted_tools():
    assert mcp_policy.evaluate_tool_policy(
        _server(enabled=False), "search"
    ).outcome is PolicyOutcome.DENY
    assert mcp_policy.evaluate_tool_policy(
        _server(), "delete_file"
    ).outcome is PolicyOutcome.DENY
    assert mcp_policy.evaluate_tool_policy(
        _server(), "write_file"
    ).outcome is PolicyOutcome.DENY


def test_mcp_policy_requires_approval_for_untrusted_or_high_risk():
    untrusted = mcp_policy.evaluate_tool_policy(_server(), "search")
    assert untrusted.outcome is PolicyOutcome.APPROVAL_REQUIRED
    assert untrusted.reason_code == "MCP_UNTRUSTED_SERVER"

    verified_write = mcp_policy.evaluate_tool_policy(
        _server(trust_level="verified"), "search", risk_class=RiskClass.WRITE
    )
    assert verified_write.outcome is PolicyOutcome.APPROVAL_REQUIRED
    assert verified_write.reason_code == "MCP_RISK_TIER_REQUIRES_APPROVAL"

    verified_read = mcp_policy.evaluate_tool_policy(
        _server(trust_level="verified"), "search", risk_class=RiskClass.READ_ONLY
    )
    assert verified_read.outcome is PolicyOutcome.ALLOW

    granted = mcp_policy.evaluate_tool_policy(
        _server(), "search", risk_class=RiskClass.WRITE, approval_granted=True
    )
    assert granted.outcome is PolicyOutcome.ALLOW


def test_mcp_tool_descriptor_is_namespaced_and_carries_schema():
    descriptor = mcp_policy.descriptor_from_tool(
        _server(),
        {
            "name": "search",
            "description": "Search issues",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    )
    assert descriptor.name == "mcp.GitHub_MCP.search"
    assert descriptor.source == "mcp"
    assert descriptor.source_id == "mcp_srv_1"
    assert descriptor.input_schema["properties"]["q"]["type"] == "string"

    descriptors = mcp_policy.descriptors_from_tools(
        _server(),
        [{"name": "search"}, {"name": ""}, {"description": "missing name"}],
    )
    assert [item.name for item in descriptors] == ["mcp.GitHub_MCP.search"]


def test_mcp_executor_policy_and_success():
    import asyncio

    from app.platform.contracts import ToolResultStatus

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, arguments, timeout_s=30.0):
            self.calls.append((name, arguments, timeout_s))
            return {"content": "ok", "tool": name}

    denied = asyncio.run(
        invoke_tool(_server(enabled=False), "search", {}, client=FakeClient())
    )
    assert denied.status is ToolResultStatus.DENIED

    untrusted = asyncio.run(invoke_tool(_server(), "search", {}, client=FakeClient()))
    assert untrusted.status is ToolResultStatus.APPROVAL_REQUIRED

    fake = FakeClient()
    ok = asyncio.run(
        invoke_tool(
            _server(trust_level="verified"),
            "search",
            {"q": "bug"},
            risk_class=RiskClass.READ_ONLY,
            client=fake,
        )
    )
    assert ok.status is ToolResultStatus.SUCCESS
    assert ok.output["content"] == "ok"
    assert fake.calls == [("search", {"q": "bug"}, 30.0)]

    missing_cred = asyncio.run(
        invoke_tool(
            _server(trust_level="verified", auth_type="bearer"),
            "search",
            {},
            risk_class=RiskClass.READ_ONLY,
        )
    )
    assert missing_cred.status is ToolResultStatus.ERROR
    assert missing_cred.error_code == "MCP_CREDENTIAL_REQUIRED"

    class BrokenClient:
        async def call_tool(self, name, arguments, timeout_s=30.0):
            raise RuntimeError("provider down")

    failed = asyncio.run(
        invoke_tool(
            _server(trust_level="verified"),
            "search",
            {},
            risk_class=RiskClass.READ_ONLY,
            client=BrokenClient(),
        )
    )
    assert failed.status is ToolResultStatus.ERROR
    assert failed.error_code == "RuntimeError"
