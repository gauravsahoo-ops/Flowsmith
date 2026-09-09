"""Shared fixtures for API tests: isolated Postgres DB + TestClient per test."""

from __future__ import annotations

from fastapi.testclient import TestClient

# Fixtures (client, slow_node, _reset_rate_limiters) live in
# tests/conftest.py (root Package never duplicates; see note there).
# SLOW_TYPE is re-exported for `from tests.test_api.conftest import ...`.
from tests.conftest import SLOW_TYPE


def register(client: TestClient, email: str | None = None, password: str = "Password123!") -> dict:
    import uuid
    if email is None:
        email = f"u_{uuid.uuid4().hex[:8]}@test.com"
    resp = client.post("/api/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_workflow(workflow_id: str = "wf_1", name: str = "My Workflow") -> dict:
    return {
        "id": workflow_id,
        "name": name,
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "transform", "type": "set_data", "parameters": {"fields": {"greeting": "hi"}}},
        ],
        "connections": [{"source": "trigger", "target": "transform"}],
        "settings": {},
    }