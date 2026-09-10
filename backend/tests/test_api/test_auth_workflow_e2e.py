"""Auth fetch/store branch workflow end-to-end (auth feature).

Manual -> Auth Fetch -> IF requiresAuthentication -> (true) mock
login -> Auth Store -> done; (false) done directly. Proves the
documented lifecycle through the real stack: first run logs in and
stores, second run reuses without touching login.
"""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, register

pytestmark = [pytest.mark.timing]


def _workflow(workflow_id="wf_auth_e2e"):
    return {
        "id": workflow_id,
        "name": "Auth E2E",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "fetch", "type": "auth_fetch", "parameters": {"provider": "custom"}},
            {"id": "needs_auth", "type": "if_condition", "parameters": {
                "condition": {"left": "$json.requiresAuthentication", "operator": "equals", "right": True},
            }},
            {"id": "login", "type": "set_data", "parameters": {
                "fields": {"access_token": "tok-live-1", "refresh_token": "ref-live-1"},
            }},
            {"id": "store", "type": "auth_store", "parameters": {
                "provider": "custom",
                "access_token": "{{ $json.access_token }}",
                "refresh_token": "{{ $json.refresh_token }}",
            }},
            {"id": "done", "type": "set_data", "parameters": {"fields": {"done": True}}},
        ],
        "connections": [
            {"source": "trigger", "target": "fetch"},
            {"source": "fetch", "target": "needs_auth"},
            {"source": "needs_auth", "target": "login", "sourceHandle": "true"},
            {"source": "login", "target": "store"},
            {"source": "store", "target": "done"},
            {"source": "needs_auth", "target": "done", "sourceHandle": "false"},
        ],
        "settings": {},
    }


def _setup(client):
    return auth_headers(register(client)["token"])


def _poll(client, execution_id, headers, timeout_s=20.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError("execution did not finish")


def test_auth_branch_first_run_logs_in_and_stores(client):
    headers = _setup(client)
    assert client.post("/api/workflows", json=_workflow(), headers=headers).status_code == 201
    run = client.post("/api/workflows/wf_auth_e2e/run", json={}, headers=headers).json()["data"]
    data = _poll(client, run["execution_id"], headers)
    assert data["status"] == "success", data
    outputs = data["results"]["outputs"]
    assert outputs["fetch"]["main"][0]["status"] == "MISSING"
    assert outputs["store"]["main"][0]["saved"] is True
    assert outputs["done"]["main"]


def test_auth_branch_second_run_skips_login(client):
    headers = _setup(client)
    assert client.post("/api/workflows", json=_workflow(), headers=headers).status_code == 201
    first = client.post("/api/workflows/wf_auth_e2e/run", json={}, headers=headers).json()["data"]
    _poll(client, first["execution_id"], headers)

    second = client.post("/api/workflows/wf_auth_e2e/run", json={}, headers=headers).json()["data"]
    data = _poll(client, second["execution_id"], headers)
    assert data["status"] == "success", data
    outputs = data["results"]["outputs"]
    assert outputs["fetch"]["main"][0]["status"] == "VALID"
    assert outputs["fetch"]["main"][0]["accessToken"] == "tok-live-1"
    assert "login" not in outputs  # login branch never executed
    assert "store" not in outputs
