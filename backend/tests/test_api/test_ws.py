"""WebSocket live execution stream tests (spec 10, 51.x)."""

from __future__ import annotations

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.test_api.conftest import SLOW_TYPE, auth_headers, make_workflow, register

pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_node")]

WF_OK = make_workflow()


def _setup(client):
    return auth_headers(register(client)["token"])


def _ws_url(execution_id: str, token: str) -> str:
    return f"/api/ws/executions/{execution_id}?token={token}"


def _wait_terminal(ws, timeout_s=15.0):
    """Receive events until execution.terminal; return (events, terminal)."""
    deadline = time.monotonic() + timeout_s
    events = []
    while time.monotonic() < deadline:
        ev = ws.receive_json()
        events.append(ev)
        if ev.get("type") == "execution.terminal":
            return events, ev
        if ev.get("event") in ("execution.completed", "execution.failed", "execution.cancelled"):
            ev = ws.receive_json()
            events.append(ev)
            assert ev.get("type") == "execution.terminal"
            return events, ev
    raise AssertionError("no terminal event received in time")


def test_ws_streams_live_events_to_success(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={"data": {"name": "Ada"}}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]

    token = headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(_ws_url(execution_id, token)) as ws:
        events, terminal = _wait_terminal(ws)

    types = [ev.get("event") for ev in events]
    assert "execution.started" in types
    assert "node.started" in types and "node.completed" in types
    assert "execution.completed" in types
    assert terminal == {"type": "execution.terminal", "status": "success", "error": None}


def test_ws_streams_cancellation(client):
    headers = _setup(client)
    wf = {
        "id": "wf_slow",
        "name": "Slow",
        "nodes": [{"id": "slow", "type": SLOW_TYPE, "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    run = client.post("/api/workflows/wf_slow/run", json={}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]

    token = headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(_ws_url(execution_id, token)) as ws:
        time.sleep(0.2)
        cancel = client.post(f"/api/executions/{execution_id}/cancel", json={}, headers=headers)
        assert cancel.status_code == 200
        events, terminal = _wait_terminal(ws)

    # Either the live event or the durable terminal fallback proves the
    # cancellation propagated end-to-end (spec 10 + 36).
    assert (
        any(ev.get("event") == "execution.cancelled" for ev in events)
        or terminal["status"] == "cancelled"
    )
    assert terminal["status"] == "cancelled"


def test_ws_rejects_bad_token(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(_ws_url("exec_abc", "not-a-token")):
            pass
    assert exc_info.value.code == 4401


def test_ws_rejects_missing_token(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/ws/executions/exec_abc"):
            pass
    assert exc_info.value.code == 4401


def test_ws_rejects_foreign_execution(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]

    token_b = register(client, email="b@b.com", password="Password123!")["token"]
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(_ws_url(execution_id, token_b)):
            pass
    assert exc_info.value.code == 4404


def test_ws_terminal_fallback_for_finished_execution(client):
    """Connecting after completion still delivers the terminal event (DB fallback)."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            break
        time.sleep(0.05)

    token = headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(_ws_url(execution_id, token)) as ws:
        _, terminal = _wait_terminal(ws)
    assert terminal["status"] == "success"
