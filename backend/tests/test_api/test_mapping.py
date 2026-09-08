"""Visual data mapping endpoints (Phase 5)."""

from __future__ import annotations

import time

from tests.test_api.conftest import auth_headers, register


def _setup(client):
    headers = auth_headers(register(client)["token"])
    wf = {
        "id": "wf_map",
        "name": "Mapping flow",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "set",
                "type": "set_data",
                "parameters": {"fields": {"email": "{{ $json.email }}", "nested": "{{ $json.customer.id }}"}},
            },
        ],
        "connections": [{"source": "trigger", "target": "set"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201
    return headers


def test_upstream_fields_flattens_last_execution(client):
    headers = _setup(client)
    run = client.post(
        "/api/workflows/wf_map/run",
        json={"data": {"email": "ada@x.io", "customer": {"id": "C-1"}, "name": "Ada"}},
        headers=headers,
    ).json()["data"]
    eid = run["execution_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        d = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
        if d["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert d["status"] == "success"

    resp = client.get("/api/workflows/wf_map/upstream-fields?node_id=set", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["upstream_nodes"] == ["trigger"]
    paths = {f["path"]: f for f in data["fields"]}
    assert paths["email"]["type"] == "str" or paths["email"]["type"] == "string"
    assert paths["email"]["sample"] == "ada@x.io"
    assert "customer.id" in paths
    assert paths["customer.id"]["sample"] == "C-1"


def test_upstream_fields_empty_before_any_run(client):
    headers = auth_headers(register(client, email="map2@x.com")["token"])
    client.post("/api/workflows", json={
        "id": "wf_map2",
        "name": "No runs",
        "nodes": [
            {"id": "a", "type": "manual_trigger", "parameters": {}},
            {"id": "b", "type": "set_data", "parameters": {}},
        ],
        "connections": [{"source": "a", "target": "b"}],
        "settings": {},
    }, headers=headers)
    resp = client.get("/api/workflows/wf_map2/upstream-fields?node_id=b", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["has_execution_data"] is False


def test_preview_resolves_and_detects_missing(client):
    headers = auth_headers(register(client, email="map3@x.com")["token"])
    # seed one execution so upstream context exists
    wf = {
        "id": "wf_prev",
        "name": "Preview",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "down", "type": "set_data", "parameters": {"fields": {"x": "1"}}},
        ],
        "connections": [{"source": "trigger", "target": "down"}],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    run = client.post("/api/workflows/wf_prev/run", json={"data": {"email": "p@q.io"}}, headers=headers).json()["data"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        d = client.get(f"/api/executions/{run['execution_id']}", headers=headers).json()["data"]
        if d["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)

    ok = client.post(
        "/api/workflows/wf_prev/preview-expression",
        json={"expression": "{{ $json.email }}", "node_id": "down"},
        headers=headers,
    )
    body = ok.json()["data"]
    assert body["missing"] is False
    assert body["value"] == "p@q.io"
    assert body["type"] == "string"

    miss = client.post(
        "/api/workflows/wf_prev/preview-expression",
        json={"expression": "{{ $json.nonexistent_field }}", "node_id": "down"},
        headers=headers,
    )
    mbody = miss.json()["data"]
    assert mbody["missing"] is True
    assert mbody["value"] is None


def test_preview_never_leaks_secret_env_values(client):
    """Secret env vars are excluded from the preview context even when the
    user has workspace read access — only non-secret values resolve."""
    from tests.test_api.test_env_execution import _create_env, _setup_ws

    headers, ws_id = _setup_ws(client, "prevsec@x.com")
    _create_env(client, headers, ws_id, "PUBLIC_URL", "https://ok.example")
    _create_env(client, headers, ws_id, "SECRET_TOKEN", "TOPSECRET-ZZZ", secret=True)

    wf = {
        "id": "wf_prevsec",
        "name": "Sec preview",
        "workspace_id": ws_id,
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "s", "type": "set_data", "parameters": {"fields": {"k": "v"}}},
        ],
        "connections": [{"source": "t", "target": "s"}],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)

    pub = client.post(
        "/api/workflows/wf_prevsec/preview-expression",
        json={"expression": "{{ $env.PUBLIC_URL }}", "node_id": "s"},
        headers=headers,
    ).json()["data"]
    assert pub["missing"] is False and pub["value"] == "https://ok.example"

    sec = client.post(
        "/api/workflows/wf_prevsec/preview-expression",
        json={"expression": "{{ $env.SECRET_TOKEN }}", "node_id": "s"},
        headers=headers,
    ).json()["data"]
    assert sec["missing"] is True  # secret key not in preview context
