"""Phase 15 — generation endpoint, full stack.

The API returns a validated PREVIEW and persists NOTHING; approval is
the client's explicit create call. Uses a monkeypatched chat_completion
(deterministic — no real LLM).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import WorkflowRecord
from tests.test_api.conftest import auth_headers, register

PLAN = {
    "name": "AI built",
    "nodes": [
        {"id": "t", "type": "manual_trigger", "parameters": {}},
        {"id": "s", "type": "set_data",
         "parameters": {"fields": {"hi": "{{ $json.name | upper }}"}}},
    ],
    "connections": [{"source": "t", "target": "s"}],
    "settings": {},
}

HALLUCINATION = {
    "name": "bad",
    "nodes": [
        {"id": "t", "type": "manual_trigger", "parameters": {}},
        {"id": "x", "type": "magic_node", "parameters": {}},
    ],
    "connections": [{"source": "t", "target": "x"}],
    "settings": {},
}


def _setup(client: TestClient):
    token = auth_headers(register(client)["token"])
    cred = client.post(
        "/api/credentials",
        json={"name": "test-llm", "type": "llm",
              "data": {"base_url": "http://127.0.0.1:9", "api_key": "k", "model": "m"}},
        headers=token,
    )
    assert cred.status_code in (200, 201), cred.text
    return token


def _patch_chat(monkeypatch, responses: list[str], calls: list):
    from app.api import ai as ai_module

    async def fake_chat(llm, messages, **kwargs):
        calls.append(messages)
        return {"content": responses.pop(0)}

    monkeypatch.setattr(ai_module, "chat_completion", fake_chat)


def test_generate_returns_preview_and_persists_nothing(client, monkeypatch):
    token = _setup(client)
    calls: list = []
    _patch_chat(monkeypatch, [json.dumps(PLAN)], calls)

    resp = client.post("/api/ai/generate-workflow",
                       json={"prompt": "upper case names"}, headers=token)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["created"] is False
    assert data["validation"]["ok"] is True
    assert data["workflow"]["status"] == "draft"
    # Nothing persisted.
    from app.db import get_session

    db = get_session()
    try:
        count = db.scalar(select(func.count()).select_from(WorkflowRecord))
    finally:
        db.close()
    assert count == 0


def test_generate_repairs_hallucinated_candidate(client, monkeypatch):
    token = _setup(client)
    calls: list = []
    fixed = {**HALLUCINATION, "nodes": HALLUCINATION["nodes"][:-1] + [
        {"id": "x", "type": "database_query", "parameters": {"sql": "SELECT 1"}}]}
    _patch_chat(monkeypatch, [json.dumps(HALLUCINATION), json.dumps(fixed)], calls)

    resp = client.post("/api/ai/generate-workflow",
                       json={"prompt": "query the db"}, headers=token)
    assert resp.status_code == 200
    assert len(calls) == 2  # repair loop ran exactly once more
    feedback = calls[1][-1]["content"]
    assert "UNKNOWN_NODE_TYPE" in feedback


def test_generate_422_with_report_when_validation_never_passes(client, monkeypatch):
    token = _setup(client)
    _patch_chat(monkeypatch, [json.dumps(HALLUCINATION), json.dumps(HALLUCINATION)], [])

    resp = client.post("/api/ai/generate-workflow",
                       json={"prompt": "magic"}, headers=token)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    codes = {e["code"] for e in detail["validation"]["errors"]}
    assert "UNKNOWN_NODE_TYPE" in codes


def test_generate_rejects_prose_and_requires_auth(client, monkeypatch):
    token = _setup(client)
    _patch_chat(monkeypatch, ["no json here at all", "still not json"], [])
    resp = client.post("/api/ai/generate-workflow",
                       json={"prompt": "leads"}, headers=token)
    assert resp.status_code == 422

    anon = client.post("/api/ai/generate-workflow", json={"prompt": "leads"})
    assert anon.status_code in (401, 403)


def test_generate_reports_missing_credentials_as_warnings(client, monkeypatch):
    token = _setup(client)  # user has ONLY the llm credential
    plan = {
        "name": "sf flow",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "sf", "type": "salesforce",
             "parameters": {"operation": "query", "soql": "SELECT Id FROM Lead"}},
        ],
        "connections": [{"source": "t", "target": "sf"}],
        "settings": {},
    }
    _patch_chat(monkeypatch, [json.dumps(plan)], [])

    resp = client.post("/api/ai/generate-workflow",
                       json={"prompt": "new sf leads"}, headers=token)
    assert resp.status_code == 200
    validation = resp.json()["data"]["validation"]
    assert validation["ok"] is True
    assert any(w["code"] == "MISSING_CREDENTIAL" for w in validation["warnings"])
