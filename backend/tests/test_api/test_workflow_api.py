"""Workflow-as-API tests: X-API-Key auth, async/sync execute, scope,
revocation. Keys are minted via /api/apikeys and consumed here.
"""

from __future__ import annotations

import pytest

from tests.test_api.conftest import auth_headers, make_workflow, register

pytestmark = [pytest.mark.timing]


def _setup(client):
    token = register(client)["token"]
    return auth_headers(token)


def _mint(client, headers, name="ci"):
    resp = client.post("/api/apikeys", json={"name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _wf():
    wf = make_workflow()
    wf["id"] = "wf_api"
    return wf


def test_async_execute_queues(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_wf(), headers=headers)
    key = _mint(client, headers)
    resp = client.post("/api/w/wf_api/execute", json={"name": "Ada"}, headers={"X-API-Key": key["key"]})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["execution_id"]


def test_sync_execute_returns_outputs(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_wf(), headers=headers)
    key = _mint(client, headers)
    resp = client.post(
        "/api/w/wf_api/execute?mode=sync&wait_seconds=30",
        json={"name": "Ada"}, headers={"X-API-Key": key["key"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "success"
    assert data["outputs"]["transform"]["main"] == [{"greeting": "hi", "name": "Ada"}]


def test_missing_and_bad_key_401(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_wf(), headers=headers)
    assert client.post("/api/w/wf_api/execute", json={}).status_code == 401
    assert client.post(
        "/api/w/wf_api/execute", json={}, headers={"X-API-Key": "bogus"},
    ).status_code == 401


def test_revoked_key_401(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_wf(), headers=headers)
    key = _mint(client, headers)
    assert client.delete(f"/api/apikeys/{key['id']}", headers=headers).status_code == 200
    assert client.post(
        "/api/w/wf_api/execute", json={}, headers={"X-API-Key": key["key"]},
    ).status_code == 401


def test_other_user_key_404(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_wf(), headers=headers)
    other = auth_headers(register(client, email="other@test.com")["token"])
    other_key = _mint(client, other)
    assert client.post(
        "/api/w/wf_api/execute", json={}, headers={"X-API-Key": other_key["key"]},
    ).status_code == 404


def test_last_used_stamped(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_wf(), headers=headers)
    key = _mint(client, headers)
    client.post("/api/w/wf_api/execute", json={}, headers={"X-API-Key": key["key"]})
    listed = client.get("/api/apikeys", headers=headers).json()["data"]
    row = next(k for k in listed if k["id"] == key["id"])
    assert row["last_used_at"] is not None
