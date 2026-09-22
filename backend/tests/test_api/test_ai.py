"""Phase 8 API tests: AI error assistant + workflow generation with a
stubbed chat client (no network)."""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, make_workflow, register

LLM_CRED = {"name": "myllm", "type": "llm", "data": {"base_url": "http://localhost:9/v1", "model": "m", "api_key": "k"}}


class FakeLLM:
    """Mutable stub harness for app.api.ai.chat_completion."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list = []

        async def fake_chat(cred, messages, **kwargs):
            self.calls.append((cred, messages, kwargs))
            return self.response()

        self.response = lambda: {"content": "{}", "tool_calls": []}
        monkeypatch.setattr("app.api.ai.chat_completion", fake_chat)


@pytest.fixture
def fake_llm(monkeypatch):
    return FakeLLM(monkeypatch)


def _register_with_llm(client, email=None):
    reg = register(client, email)
    resp = client.post("/api/credentials", json=LLM_CRED, headers=auth_headers(reg["token"]))
    assert resp.status_code == 201
    return reg


def test_status_reflects_llm_credential(client):
    reg = register(client)
    assert client.get("/api/ai/status", headers=auth_headers(reg["token"])).json()["data"]["configured"] is False
    client.post("/api/credentials", json=LLM_CRED, headers=auth_headers(reg["token"]))
    assert client.get("/api/ai/status", headers=auth_headers(reg["token"])).json()["data"]["configured"] is True


def _await_finished(client, token, exec_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/executions/{exec_id}", headers=auth_headers(token)).json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return status
        time.sleep(0.1)
    raise AssertionError("execution did not finish")


def test_explain_failure(client, fake_llm):
    reg = _register_with_llm(client)
    wf = make_workflow("wf_ai")
    wf["nodes"].append({"id": "ai", "type": "ai", "parameters": {"prompt": "hi"}})
    wf["connections"].append({"source": "transform", "target": "ai"})
    assert client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"])).status_code == 201
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=auth_headers(reg["token"]))
    exec_id = run.json()["data"]["execution_id"]
    assert _await_finished(client, reg["token"], exec_id) == "failed"

    fake_llm.response = lambda: {"content": "The AI node needs a credential.", "tool_calls": []}
    resp = client.post("/api/ai/explain", json={"execution_id": exec_id}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 200
    assert "credential" in resp.json()["data"]["explanation"]


def test_explain_requires_failing_step(client, fake_llm):
    reg = _register_with_llm(client)
    wf = make_workflow()
    client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=auth_headers(reg["token"]))
    exec_id = run.json()["data"]["execution_id"]
    assert _await_finished(client, reg["token"], exec_id) == "success"
    resp = client.post("/api/ai/explain", json={"execution_id": exec_id}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 409


def test_explain_without_llm_credential(client, fake_llm):
    reg = register(client)
    wf = make_workflow("wf_fail_no_llm")
    wf["nodes"].append({"id": "ai", "type": "ai", "parameters": {"prompt": "hi"}})
    wf["connections"].append({"source": "transform", "target": "ai"})
    client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=auth_headers(reg["token"]))
    exec_id = run.json()["data"]["execution_id"]
    assert _await_finished(client, reg["token"], exec_id) == "failed"
    resp = client.post("/api/ai/explain", json={"execution_id": exec_id}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 422


def test_generate_workflow_valid(client, fake_llm):
    reg = _register_with_llm(client, "gen@x.com")
    generated = {
        "name": "HTTP Poller",
        "nodes": [
            {"id": "trigger", "type": "schedule", "parameters": {"cron": "*/5 * * * *"}},
            {"id": "fetch", "type": "http_request", "parameters": {"method": "GET", "url": "https://example.com"}},
            {"id": "store", "type": "database_query", "parameters": {"sql": "SELECT 1"}},
        ],
        "connections": [{"source": "trigger", "target": "fetch"}, {"source": "fetch", "target": "store"}],
        "settings": {},
    }
    fake_llm.response = lambda: {"content": __import__("json").dumps(generated), "tool_calls": []}
    resp = client.post("/api/ai/generate-workflow", json={"prompt": "poll every 5 min"}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    wf = data["workflow"]
    assert wf["name"] == "HTTP Poller"
    assert wf["id"].startswith("wf_")
    assert len(wf["nodes"]) == 3
    assert data["validation"]["ok"] is True
    # not saved yet: creating with the returned payload works
    created = client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
    assert created.status_code == 201


def test_generate_workflow_invalid_json(client, fake_llm):
    reg = _register_with_llm(client, "gen2@x.com")
    fake_llm.response = lambda: {"content": "sure, here you go", "tool_calls": []}
    resp = client.post("/api/ai/generate-workflow", json={"prompt": "make a workflow"}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 422


def test_generate_workflow_invalid_graph(client, fake_llm):
    reg = _register_with_llm(client, "gen3@x.com")
    bad = {"name": "Bad", "nodes": [{"id": "x", "type": "not_a_node", "parameters": {}}], "connections": [], "settings": {}}
    fake_llm.response = lambda: {"content": __import__("json").dumps(bad), "tool_calls": []}
    resp = client.post("/api/ai/generate-workflow", json={"prompt": "x"}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 422


def test_generate_requires_llm_credential(client, fake_llm):
    reg = register(client)
    resp = client.post("/api/ai/generate-workflow", json={"prompt": "x"}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 422


def test_generate_is_audited(client, fake_llm):
    reg = _register_with_llm(client, "gen4@x.com")
    ok_wf = {"name": "N", "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}], "connections": [], "settings": {}}
    fake_llm.response = lambda: {"content": __import__("json").dumps(ok_wf), "tool_calls": []}
    client.post("/api/ai/generate-workflow", json={"prompt": "a simple workflow"}, headers=auth_headers(reg["token"]))
    audit = client.get("/api/audit?action=ai.generate", headers=auth_headers(reg["token"])).json()["data"]
    assert len(audit) == 1


def test_provider_unreachable_is_502(client, monkeypatch):
    from app.ai.client import LLMError

    reg = _register_with_llm(client, "gen5@x.com")

    async def boom(cred, messages, **kwargs):
        raise LLMError("LLM provider unreachable: refused", code="LLM_NETWORK_ERROR")

    monkeypatch.setattr("app.api.ai.chat_completion", boom)
    resp = client.post("/api/ai/generate-workflow", json={"prompt": "make a simple workflow"}, headers=auth_headers(reg["token"]))
    assert resp.status_code == 502


def test_ai_memory_inspect_and_clear(client):
    """Verify GET /api/ai/memory/{session_id} and DELETE /api/ai/memory/{session_id}."""
    from app.ai.memory import get_memory_manager
    reg = register(client, "mem_user@x.com")
    headers = auth_headers(reg["token"])

    # Initially non-existent session
    resp = client.get("/api/ai/memory/session_test_99", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["exists"] is False

    # Seed messages into memory manager
    manager = get_memory_manager()
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        mem = loop.run_until_complete(manager.get_working_memory("session_test_99"))
        mem.add_message("user", "Hello agent!")
        mem.add_message("assistant", "Hello! How can I help?")
    finally:
        loop.close()

    # Verify inspection reflects populated memory
    resp = client.get("/api/ai/memory/session_test_99", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exists"] is True
    assert data["turns"] == 2
    assert data["type"] == "window"
    assert len(data["messages"]) == 2

    # Clear memory
    del_resp = client.delete("/api/ai/memory/session_test_99", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["data"]["cleared"] is True

    # Verify cleared
    resp_after = client.get("/api/ai/memory/session_test_99", headers=headers)
    assert resp_after.status_code == 200
    assert resp_after.json()["data"]["exists"] is False


def test_generate_workflow_with_history_and_existing_workflow(client, fake_llm):
    """Verify Copilot incorporates conversation history and existing canvas state."""
    import json
    reg = _register_with_llm(client, "copilot_mem@x.com")
    ok_wf = {
        "name": "Extended Flow",
        "nodes": [
            {"id": "node_1", "type": "manual_trigger", "parameters": {}},
            {"id": "node_2", "type": "slack", "parameters": {"channel": "#general", "text": "Hi"}},
        ],
        "connections": [{"source": "node_1", "target": "node_2"}],
        "settings": {},
    }
    fake_llm.response = lambda: {"content": json.dumps(ok_wf), "tool_calls": []}

    payload = {
        "prompt": "Now add a Slack notification to the existing workflow",
        "history": [
            {"role": "user", "content": "Create a manual trigger workflow"},
            {"role": "assistant", "content": "I generated a workflow with a manual trigger."},
        ],
        "existing_workflow": {
            "nodes": [{"id": "node_1", "type": "manual_trigger"}],
        },
    }

    resp = client.post("/api/ai/generate-workflow", json=payload, headers=auth_headers(reg["token"]))
    assert resp.status_code == 200
    res_data = resp.json()["data"]
    assert res_data["workflow"]["name"] == "Extended Flow"

    # Verify that the fake_llm received messages containing the history and existing workflow
    last_call = fake_llm.calls[-1]
    messages = last_call[1]
    history_roles = [m["role"] for m in messages]
    assert "user" in history_roles
    assert "assistant" in history_roles
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    assert any("Create a manual trigger workflow" in u for u in user_msgs)
    assert any("EXISTING WORKFLOW STATE TO MODIFY OR EXTEND" in u for u in user_msgs)
