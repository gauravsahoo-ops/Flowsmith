"""Public chat trigger tests (Batch D): definition, sync round-trip reply,
validation, 404s, activation semantics. Mirrors the form suite.
"""

from __future__ import annotations

import pytest

from app.db import get_session
from app.models import WebhookTrigger
from tests.test_api.conftest import auth_headers, register

pytestmark = [pytest.mark.timing]

CHAT_PATH = "chat/support-abcdefgh12345678"


def _setup(client):
    return auth_headers(register(client)["token"])


def _chat_workflow(workflow_id="wf_chat"):
    return {
        "id": workflow_id,
        "name": "ChatFlow",
        "nodes": [
            {"id": "trigger", "type": "chat_trigger",
             "parameters": {"path": CHAT_PATH, "title": "Support", "greeting": "Hi!"}},
            {"id": "answer", "type": "set_data",
             "parameters": {"fields": {"reply": "echo: {{ $json.message }}"}}},
        ],
        "connections": [{"source": "trigger", "target": "answer"}],
        "settings": {},
    }


def _create_and_activate(client, headers, workflow):
    client.post("/api/workflows", json=workflow, headers=headers)
    resp = client.patch(f"/api/workflows/{workflow['id']}/active", json={"active": True}, headers=headers)
    assert resp.status_code == 200, resp.text


def test_chat_definition_public(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _chat_workflow())
    resp = client.get(f"/api/webhooks/{CHAT_PATH}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["title"] == "Support"
    assert data["greeting"] == "Hi!"


def test_chat_round_trip_reply(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _chat_workflow())
    resp = client.post(
        f"/api/webhooks/{CHAT_PATH}",
        json={"message": "hello", "session_id": "s1", "history": []},
        timeout=120,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "success"
    assert data["reply"] == "echo: hello"
    assert data["session_id"] == "s1"
    assert data["execution_id"]


def test_chat_empty_message_422(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _chat_workflow())
    assert client.post(f"/api/webhooks/{CHAT_PATH}", json={"message": "  "}).status_code == 422
    assert client.post(f"/api/webhooks/{CHAT_PATH}", json={}).status_code == 422


def test_chat_unknown_slug_404(client):
    assert client.get("/api/webhooks/chat/nope-abcdefgh12345678").status_code == 404
    assert client.post("/api/webhooks/chat/nope-abcdefgh12345678", json={"message": "hi"}).status_code == 404


def test_chat_inactive_workflow_404(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_chat_workflow(), headers=headers)
    assert client.post(f"/api/webhooks/{CHAT_PATH}", json={"message": "hi"}).status_code == 404


def test_chat_deactivate_removes_definition(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _chat_workflow())
    assert client.get(f"/api/webhooks/{CHAT_PATH}").status_code == 200
    client.patch("/api/workflows/wf_chat/active", json={"active": False}, headers=headers)
    assert client.get(f"/api/webhooks/{CHAT_PATH}").status_code == 404

    db = get_session()
    try:
        assert db.query(WebhookTrigger).count() == 0
    finally:
        db.close()
