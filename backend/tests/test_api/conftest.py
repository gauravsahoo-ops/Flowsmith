"""Shared fixtures for API tests: isolated Postgres DB + TestClient per test."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.engine.errors import NodeCancelledError
from app.engine.node_base import BaseNode, EmptyParams, NodeContext, NodeResult
from app.main import app
from app.nodes.registry import NODE_REGISTRY

SLOW_TYPE = "slow_test_node"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset auth rate limiters between tests to prevent cross-test exhaustion."""
    from app.api.auth import _register_limiter, _forgot_password_limiter, login_throttle
    _register_limiter.reset()
    _forgot_password_limiter.reset()
    login_throttle.reset()
    yield
    _register_limiter.reset()
    _forgot_password_limiter.reset()
    login_throttle.reset()


@pytest.fixture
def client():
    """Empty Postgres DB per test (root conftest truncates before each test)."""
    return TestClient(app)


@pytest.fixture
def slow_node():
    """Register a node that sleeps until cancelled (stream/cancel tests)."""

    class SlowNode(BaseNode[EmptyParams]):
        node_type = SLOW_TYPE
        display_name = "Slow (test)"
        version = 1
        description = "Hangs until cancelled."
        category = "Test"
        icon = "🐌"
        parameters_schema = EmptyParams

        async def run(self, ctx: NodeContext, params: EmptyParams, input_items: list[dict[str, Any]]) -> NodeResult:
            for _ in range(200):
                if ctx.is_cancelled():
                    raise NodeCancelledError()
                await asyncio.sleep(0.05)
            return NodeResult(output_items=[{"done": True}])

    NODE_REGISTRY[SLOW_TYPE] = SlowNode
    yield SLOW_TYPE
    NODE_REGISTRY.pop(SLOW_TYPE, None)


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