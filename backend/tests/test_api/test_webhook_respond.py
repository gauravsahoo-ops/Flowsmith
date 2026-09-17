"""Synchronous webhook responses (Respond to Webhook node + ?respond=true).

The default stays async-202; only deliveries that opt in with
?respond=true wait for the execution and return the respond node's
output with its status code.
"""

from __future__ import annotations

import pytest

from tests.test_api.conftest import auth_headers, register
from tests.test_api.test_webhook_trigger import _create_and_activate, _poll

pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_node")]

PATH = "hook-respond-secure-path-abcdefgh"


def _respond_workflow(workflow_id="wf_hook_respond"):
    return {
        "id": workflow_id,
        "name": "HookRespond",
        "nodes": [
            {"id": "trigger", "type": "webhook", "parameters": {"path": PATH, "method": "POST"}},
            {"id": "echo", "type": "set_data", "parameters": {"mode": "replace", "fields": {"msg": "{{ $json.body.msg }}"}}},
            {"id": "reply", "type": "respond_to_webhook",
             "parameters": {"status_code": 201, "respond_with": "first"}},
        ],
        "connections": [
            {"source": "trigger", "target": "echo"},
            {"source": "echo", "target": "reply"},
        ],
        "settings": {},
    }


def test_respond_true_returns_node_body_with_status(client):
    headers = auth_headers(register(client)["token"])
    _create_and_activate(client, headers, _respond_workflow())
    resp = client.post(f"/api/webhooks/{PATH}?respond=true", json={"msg": "hi"})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"msg": "hi"}


def test_default_stays_async_202(client):
    headers = auth_headers(register(client)["token"])
    _create_and_activate(client, headers, _respond_workflow("wf_hook_respond2"))
    resp = client.post(f"/api/webhooks/{PATH}", json={"msg": "hi"})
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    assert data["execution_id"]
    assert data.get("skipped") is False
    exec_data = _poll(client, data["execution_id"], headers)
    assert exec_data["status"] == "success"


def test_respond_without_node_falls_back_to_202(client):
    from tests.test_api.test_webhook_trigger import _webhook_workflow

    headers = auth_headers(register(client)["token"])
    wf = _webhook_workflow("wf_hook_norespond", PATH)
    _create_and_activate(client, headers, wf)
    resp = client.post(f"/api/webhooks/{PATH}?respond=true", json={"msg": "hi"})
    assert resp.status_code == 202, resp.text
    assert resp.json()["data"]["execution_id"]


def test_respond_failed_execution_returns_500(client):
    headers = auth_headers(register(client)["token"])
    wf = {
        "id": "wf_hook_respond_fail",
        "name": "HookRespondFail",
        "nodes": [
            {"id": "trigger", "type": "webhook",
             "parameters": {"path": PATH, "method": "POST"}},
            {"id": "boom", "type": "stop_and_error",
             "parameters": {"error_message": "kaboom-test"}},
            {"id": "reply", "type": "respond_to_webhook", "parameters": {}},
        ],
        "connections": [
            {"source": "trigger", "target": "boom"},
            {"source": "boom", "target": "reply"},
        ],
        "settings": {},
    }
    _create_and_activate(client, headers, wf)
    resp = client.post(f"/api/webhooks/{PATH}?respond=true", json={})
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["execution_id"]
