"""MCP server registry API tests for per-server sandbox policy."""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.db import get_session
from app.models import Credential, Organization, User, Workspace
from app.security.crypto import encrypt_text
from app.tools.mcp import registry as mcp_registry

from tests.test_api.conftest import auth_headers, register

SANDBOX_IMAGE = "ghcr.io/flowsmith/mcp-runtime@sha256:" + "a" * 64


def _workspace(client, email: str) -> tuple[dict, str]:
    registered = register(client, email=email)
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    with get_session() as db:
        org = Organization(
            id=f"org_mcp_sandbox_{user_id}",
            name="MCP sandbox API Org",
            founder_id=user_id,
            is_public=False,
        )
        db.add(org)
        db.flush()
        workspace = Workspace(
            id=f"ws_mcp_sandbox_{user_id}",
            name="MCP sandbox API Workspace",
            organization_id=org.id,
            creator_id=user_id,
            is_private=True,
        )
        db.add(workspace)
        db.commit()
    return headers, workspace.id


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _stdio_payload(workspace_id: str, **overrides) -> dict:
    payload = {
        "workspace_id": workspace_id,
        "name": "Sandbox MCP",
        "endpoint": "python -m mcp_server",
        "transport": "stdio",
    }
    payload.update(overrides)
    return payload


def test_create_returns_sandbox_defaults(client):
    headers, workspace_id = _workspace(client, "mcp_sandbox_defaults@example.com")
    response = client.post(
        "/api/mcp/servers",
        json=_stdio_payload(workspace_id),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["sandbox_backend"] == "subprocess"
    assert data["sandbox_image"] is None
    assert data["sandbox_workspace_mode"] == "none"
    assert data["sandbox_workspace_path"] is None
    assert data["sandbox_network"] == "none"
    assert data["sandbox_read_only"] is True


def test_create_update_and_get_sandbox_fields(client, tmp_path):
    headers, workspace_id = _workspace(client, "mcp_sandbox_roundtrip@example.com")
    created = client.post(
        "/api/mcp/servers",
        json=_stdio_payload(
            workspace_id,
            sandbox_backend="docker",
            sandbox_image=SANDBOX_IMAGE,
            sandbox_workspace_mode="configured",
            sandbox_workspace_path=str(tmp_path),
            sandbox_network="none",
            sandbox_read_only=False,
        ),
        headers=headers,
    )
    assert created.status_code == 200, created.text
    server_id = created.json()["data"]["id"]
    data = created.json()["data"]
    assert data["sandbox_backend"] == "docker"
    assert data["sandbox_image"] == SANDBOX_IMAGE
    assert data["sandbox_workspace_mode"] == "configured"
    assert data["sandbox_workspace_path"] == str(tmp_path)
    assert data["sandbox_network"] == "none"
    assert data["sandbox_read_only"] is False

    patched = client.patch(
        f"/api/mcp/servers/{server_id}",
        json={
            "sandbox_workspace_mode": "ephemeral",
            "sandbox_workspace_path": "",
            "sandbox_read_only": True,
        },
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    patched_data = patched.json()["data"]
    assert patched_data["sandbox_workspace_mode"] == "ephemeral"
    assert patched_data["sandbox_workspace_path"] is None
    assert patched_data["sandbox_read_only"] is True

    fetched = client.get(f"/api/mcp/servers/{server_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["sandbox_image"] == SANDBOX_IMAGE
    assert fetched.json()["data"]["sandbox_workspace_mode"] == "ephemeral"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"sandbox_backend": "firecracker"}, "MCP_SANDBOX_BACKEND_INVALID"),
        (
            {"sandbox_workspace_mode": "shared"},
            "MCP_SANDBOX_WORKSPACE_MODE_INVALID",
        ),
        ({"sandbox_network": "host"}, "MCP_SANDBOX_POLICY"),
        ({"sandbox_network": "container:other"}, "MCP_SANDBOX_POLICY"),
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
def test_create_rejects_invalid_sandbox_policy(
    client, monkeypatch, overrides, code
):
    monkeypatch.setattr(mcp_registry, "get_settings", lambda: _settings())
    headers, workspace_id = _workspace(
        client, f"mcp_sandbox_invalid_{code.lower()}@example.com"
    )
    response = client.post(
        "/api/mcp/servers",
        json=_stdio_payload(workspace_id, **overrides),
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code


def test_update_rejects_invalid_sandbox_policy(client, monkeypatch):
    monkeypatch.setattr(mcp_registry, "get_settings", lambda: _settings())
    headers, workspace_id = _workspace(client, "mcp_sandbox_update_invalid@example.com")
    created = client.post(
        "/api/mcp/servers",
        json=_stdio_payload(workspace_id),
        headers=headers,
    )
    assert created.status_code == 200, created.text
    server_id = created.json()["data"]["id"]

    docker_missing_image = client.patch(
        f"/api/mcp/servers/{server_id}",
        json={"sandbox_backend": "docker"},
        headers=headers,
    )
    assert docker_missing_image.status_code == 422, docker_missing_image.text
    assert (
        docker_missing_image.json()["detail"]["code"]
        == "MCP_SANDBOX_IMAGE_REQUIRED"
    )

    configured_missing_path = client.patch(
        f"/api/mcp/servers/{server_id}",
        json={"sandbox_workspace_mode": "configured"},
        headers=headers,
    )
    assert configured_missing_path.status_code == 422, configured_missing_path.text
    assert (
        configured_missing_path.json()["detail"]["code"]
        == "MCP_SANDBOX_WORKSPACE_REQUIRED"
    )

    unchanged = client.get(f"/api/mcp/servers/{server_id}", headers=headers)
    assert unchanged.json()["data"]["sandbox_backend"] == "subprocess"
    assert unchanged.json()["data"]["sandbox_workspace_mode"] == "none"


def test_sandbox_response_never_includes_secrets(client):
    headers, workspace_id = _workspace(client, "mcp_sandbox_secret@example.com")
    with get_session() as db:
        owner = db.query(User).filter_by(
            email="mcp_sandbox_secret@example.com"
        ).one()
        credential = Credential(
            id="cred_mcp_sandbox_secret",
            user_id=owner.id,
            name="MCP sandbox secret",
            type="bearer_auth",
            data=encrypt_text(json.dumps({"token": "super-secret-token"})),
        )
        db.add(credential)
        db.commit()

    created = client.post(
        "/api/mcp/servers",
        json=_stdio_payload(
            workspace_id,
            auth_type="bearer",
            credential_id="cred_mcp_sandbox_secret",
            sandbox_backend="docker",
            sandbox_image=SANDBOX_IMAGE,
        ),
        headers=headers,
    )
    assert created.status_code == 200, created.text
    body = created.text
    assert "super-secret-token" not in body
    assert "MCP_AUTH_TOKEN" not in body
