"""Phase 16 — assistant endpoints, full stack.

Every surface is read-only: responses carry validated suggestions and
the workflow record must be byte-identical afterwards. Uses a
monkeypatched chat_completion (deterministic, no real LLM).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.test_api.conftest import auth_headers, register


def _setup(client: TestClient):
    token = auth_headers(register(client)["token"])
    resp = client.post("/api/credentials", json={
        "name": "llm", "type": "llm",
        "data": {"base_url": "http://127.0.0.1:9", "api_key": "k", "model": "m"},
    }, headers=token)
    assert resp.status_code in (200, 201)
    wf = {
        "id": "wf_assist",
        "name": "Assist me",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "set", "type": "set_data", "parameters": {"fields": {"greeting": ""}}},
            {"id": "h", "type": "http_request",
             "parameters": {"method": "GET", "url": "https://api.example.com/x"}},
        ],
        "connections": [{"source": "t", "target": "set"}, {"source": "set", "target": "h"}],
        "settings": {},
    }
    created = client.post("/api/workflows", json=wf, headers=token)
    assert created.status_code == 201, created.text
    return token


def _patch_chat(monkeypatch, payload):
    from app.api import ai as ai_module

    async def fake_chat(llm, messages, **kwargs):
        return {"content": json.dumps(payload) if not isinstance(payload, str) else payload}

    monkeypatch.setattr(ai_module, "chat_completion", fake_chat)


def test_suggest_mapping_returns_validated_mapping(client, monkeypatch):
    token = _setup(client)
    _patch_chat(monkeypatch, {
        "mapping": {"greeting": "{{ $json.name | upper }}"},
        "explanation": "uses name",
    })
    resp = client.post("/api/ai/suggest-mapping", json={
        "workflow_id": "wf_assist", "node_id": "set"}, headers=token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["mapping"]["greeting"] == "{{ $json.name | upper }}"


def test_suggest_expression_endpoint_validates(client, monkeypatch):
    token = _setup(client)
    _patch_chat(monkeypatch, {"expression": "{{ $json.name | upper }}", "explanation": "up"})
    resp = client.post("/api/ai/suggest-expression", json={
        "description": "uppercase name", "sample_item": {"name": "ada"}}, headers=token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["preview_value"] == "ADA"

    # Unsafe model output is flagged, never silently passed through.
    _patch_chat(monkeypatch, {"expression": "{{ $json.__class__ }}"})
    bad = client.post("/api/ai/suggest-expression", json={
        "description": "cheat", "sample_item": {}}, headers=token)
    assert bad.json()["data"]["ok"] is False


def test_suggest_node_config_rejects_schema_violations(client, monkeypatch):
    token = _setup(client)
    _patch_chat(monkeypatch, {"parameters": {"method": "TELEPORT", "url": "https://x"}})
    resp = client.post("/api/ai/suggest-node-config", json={
        "node_type": "http_request", "intent": "call api"}, headers=token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is False
    assert any(i["code"] == "INVALID_PARAMETER" for i in data["issues"])


def test_optimize_reports_deterministic_findings_and_advisory(client, monkeypatch):
    token = _setup(client)  # workflow has GET http node without timeout/retry
    _patch_chat(monkeypatch, {"suggestions": [
        {"title": "Add timeout", "detail": "Set timeout_seconds on the HTTP node."}]})
    resp = client.post("/api/ai/optimize-workflow",
                       json={"workflow_id": "wf_assist"}, headers=token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    codes = {f["code"] for f in data["findings"]}
    assert {"NO_TIMEOUT", "NO_RETRY_ON_IDEMPOTENT"} <= codes
    assert data["suggestions"][0]["title"] == "Add timeout"


def test_document_works_even_without_llm_credential(client):
    token = auth_headers(register(client, email="nodoc@d.com")["token"])
    client.post("/api/workflows", json={
        "id": "wf_doc", "name": "Doc'd",
        "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
        "connections": [], "settings": {},
    }, headers=token)
    # No llm credential on this account: the skeleton still comes back.
    resp = client.post("/api/ai/document-workflow",
                       json={"workflow_id": "wf_doc"}, headers=token)
    assert resp.status_code == 200
    md = resp.json()["data"]["markdown"]
    assert "# Doc'd" in md and "## Triggers" in md


def test_assist_is_read_only_workflow_untouched(client, monkeypatch):
    token = _setup(client)
    before = client.get("/api/workflows/wf_assist", headers=token).json()["data"]
    _patch_chat(monkeypatch, {"mapping": {"greeting": "{{ $json.x }}"}})
    client.post("/api/ai/suggest-mapping", json={
        "workflow_id": "wf_assist", "node_id": "set"}, headers=token)
    client.post("/api/ai/optimize-workflow", json={"workflow_id": "wf_assist"}, headers=token)
    after = client.get("/api/workflows/wf_assist", headers=token).json()["data"]
    assert after == before


def test_assist_requires_access(client):
    token = _setup(client)
    other = auth_headers(register(client, email="intruder@e.com")["token"])
    for path, body in [
        ("/api/ai/suggest-mapping", {"workflow_id": "wf_assist", "node_id": "set"}),
        ("/api/ai/optimize-workflow", {"workflow_id": "wf_assist"}),
        ("/api/ai/explain-workflow", {"workflow_id": "wf_assist"}),
        ("/api/ai/auto-fix", {"workflow_id": "wf_assist", "node_id": "h", "error_message": "Invalid URL"}),
    ]:
        assert client.post(path, json=body, headers=other).status_code == 404, path


def test_document_generates_mermaid_diagram(client):
    token = _setup(client)
    resp = client.post("/api/ai/document-workflow",
                       json={"workflow_id": "wf_assist"}, headers=token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "mermaid" in data
    assert "graph TD" in data["mermaid"]
    assert "t --> set" in data["mermaid"]
    assert "set --> h" in data["mermaid"]


def test_auto_fix_node_recovers_malformed_url(client):
    token = _setup(client)
    # Patch the node url in the workflow to be malformed (missing scheme)
    client.put("/api/workflows/wf_assist", json={
        "id": "wf_assist",
        "name": "Assist me",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "h", "type": "http_request",
             "parameters": {"method": "GET", "url": "api.example.com/v1/users"}},
        ],
        "connections": [{"source": "t", "target": "h"}],
        "settings": {},
    }, headers=token)

    resp = client.post("/api/ai/auto-fix", json={
        "workflow_id": "wf_assist",
        "node_id": "h",
        "error_message": "Invalid URL: missing schema http:// or https://",
    }, headers=token)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["suggested_parameters"]["url"].startswith("https://")
    assert "scheme" in data["root_cause"].lower() or "url" in data["root_cause"].lower()

