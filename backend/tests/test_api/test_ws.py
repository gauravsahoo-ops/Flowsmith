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


# ----------------------------------------------------------------------
# Connection caps / idle + lifetime limits
# ----------------------------------------------------------------------

def test_ws_enforces_per_user_connection_cap(client, monkeypatch):
    from app.api import ws as ws_module

    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]

    monkeypatch.setattr(ws_module, "_MAX_WS_PER_USER", 0)
    token = headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(_ws_url(execution_id, token)) as ws:
        msg = ws.receive_json()
        assert msg.get("error") == "Connection limit reached."
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == 4429


def _run_slow_execution(client) -> tuple[str, dict]:
    headers = _setup(client)
    wf = {
        "id": "wf_slow2",
        "name": "Slow2",
        "nodes": [{"id": "slow", "type": SLOW_TYPE, "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    run = client.post("/api/workflows/wf_slow2/run", json={}, headers=headers)
    return run.json()["data"]["execution_id"], headers


def _drain_until_disconnect(ws, timeout_s=10.0) -> list[dict]:
    """Receive until the server closes; return all messages seen."""
    deadline = time.monotonic() + timeout_s
    msgs: list[dict] = []
    while time.monotonic() < deadline:
        try:
            msgs.append(ws.receive_json())
        except WebSocketDisconnect:
            return msgs
    raise AssertionError("connection was not closed in time")


def test_ws_idle_timeout_closes_quiet_connection(client, monkeypatch):
    from app.api import ws as ws_module

    execution_id, headers = _run_slow_execution(client)
    monkeypatch.setattr(ws_module, "_WS_IDLE_TIMEOUT_S", 0.2)
    token = headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(_ws_url(execution_id, token)) as ws:
        msgs = _drain_until_disconnect(ws)
    assert any(m.get("error") == "Idle timeout." for m in msgs)


def test_ws_max_lifetime_closes_connection(client, monkeypatch):
    from app.api import ws as ws_module

    execution_id, headers = _run_slow_execution(client)
    monkeypatch.setattr(ws_module, "_WS_MAX_LIFETIME_S", 0.5)
    token = headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(_ws_url(execution_id, token)) as ws:
        msgs = _drain_until_disconnect(ws)
    assert any(m.get("error") == "Connection lifetime limit reached." for m in msgs)


# ----------------------------------------------------------------------
# One-time WS tickets (?ticket= keeps bearer JWTs out of URLs/logs)
# ----------------------------------------------------------------------

def test_ws_ticket_endpoint_and_socket_auth(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]

    resp = client.post("/api/auth/ws-ticket", headers=headers)
    assert resp.status_code == 200
    ticket = resp.json()["data"]["ticket"]
    assert ticket

    with client.websocket_connect(f"/api/ws/executions/{execution_id}?ticket={ticket}") as ws:
        _, terminal = _wait_terminal(ws)
    assert terminal["status"] == "success"


def test_ws_ticket_endpoint_requires_auth(client):
    assert client.post("/api/auth/ws-ticket").status_code == 401


def test_ws_ticket_is_single_use_and_validates():
    from app.security.ws_ticket import consume_ws_ticket, issue_ws_ticket

    ticket = issue_ws_ticket(42)
    assert consume_ws_ticket(ticket) == 42
    assert consume_ws_ticket(ticket) is None  # replay blocked
    assert consume_ws_ticket("not-a-ticket") is None
    assert consume_ws_ticket("") is None


def test_ws_rejects_invalid_ticket(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers)
    execution_id = run.json()["data"]["execution_id"]
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/ws/executions/{execution_id}?ticket=bogus"):
            pass
    assert exc_info.value.code == 4401
