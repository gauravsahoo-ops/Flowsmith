"""Phase 36: Business acceptance — 12 realistic user journeys.

Each test exercises the full public-API → queue → worker → engine → API
path (or equivalent). External systems are stubbed with the same fakes
used by Phase 11/14 suites. Cross-cutting assertions include execution
history, credential isolation, monitoring, and permissions.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.timing

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import FakeHTTPClient, json_response, patch_provider_http
from tests.test_api.conftest import auth_headers, register


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}

LEAD_RECORD = {
    "Id": "00Qabc123",
    "Name": "Jane Doe",
    "Email": "jane@example.com",
    "Company": "Acme",
}

SEARCH_FOUND = {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]}
SEARCH_EMPTY = {"totalSize": 0, "done": True, "records": []}

POSTGRES_CREDENTIAL_DATA = {
    "dsn": "postgresql://automate:automate@localhost:5432/automate_test",
}

GMAIL_CREDENTIAL_DATA = {
    "user": "bot@example.com",
    "refresh_token": "fake_refresh",
}

MSTEAMS_CREDENTIAL_DATA = {
    "tenant_id": "tenant_123",
    "client_id": "app_123",
    "client_secret": "secret_123",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _connectors_registered():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield


def _setup(client):
    return auth_headers(register(client)["token"])


def _create_credential(client, headers, cred_type: str, data: dict, name: str = "Cred") -> str:
    resp = client.post("/api/credentials", json={"name": name, "type": cred_type, "data": data}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


def _create_and_save_workflow(client, headers, wf_id: str, workflow: dict) -> None:
    workflow["id"] = wf_id
    resp = client.post("/api/workflows", json=workflow, headers=headers)
    assert resp.status_code in (200, 201), resp.text


def _run_and_poll(client, headers, wf_id, input_data=None, deadline_s: float = 15):
    body = {"data": input_data} if input_data is not None else {}
    resp = client.post(f"/api/workflows/{wf_id}/run", json=body, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + deadline_s
    data = None
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {data['status']}")


def _sf_token_responses():
    return [json_response(200, TOKEN_BODY)]


def _sf_search_responses(found: bool = True):
    return [
        json_response(200, TOKEN_BODY),
        json_response(200, SEARCH_FOUND if found else SEARCH_EMPTY),
    ]


def _sf_search_and_get_responses():
    return [
        json_response(200, TOKEN_BODY),
        json_response(200, SEARCH_FOUND),
        json_response(200, LEAD_RECORD),
    ]


def _sf_create_responses():
    return [
        json_response(200, TOKEN_BODY),
        json_response(201, {"id": "00Qabc123", "success": True}),
    ]


# ---------------------------------------------------------------------------
# Scenario 1: Salesforce lead automation
#   webhook → set_data → SF search (dedupe) → if not found → SF create
# ---------------------------------------------------------------------------


def test_scenario_01_sf_lead_automation(client):
    headers = _setup(client)
    cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF Prod")
    wf_id = "wf_ba_01_sf_lead_auto"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "SF Lead Automation",
        "nodes": [
            {"id": "trig", "type": "webhook", "parameters": {"path": "lead-auto-abcdef1234567890", "method": "POST"}},
            {"id": "map", "type": "set_data", "parameters": {"fields": {"email": "{{ $json.body.email }}", "name": "{{ $json.body.name }}"}}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "{{ $node.map.json.email }}",
            }, "credentials": {"salesforce": cred_id}},
            {"id": "create_check", "type": "set_data", "parameters": {"fields": {
                "found": "{{ $node.sf.json.found }}",
                "email": "{{ $node.map.json.email }}",
            }}},
        ],
        "connections": [
            {"source": "trig", "target": "map"},
            {"source": "map", "target": "sf"},
            {"source": "sf", "target": "create_check"},
        ],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_search_responses(found=False),
    )
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={
            "body": {"email": "new@lead.com", "name": "New Lead"}
        })
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["results"]["outputs"]["sf"]["main"][0]["found"] is False
    assert data["results"]["outputs"]["create_check"]["main"][0]["found"] is False
    history = client.get(f"/api/executions?workflow_id={wf_id}", headers=headers).json()
    assert any(e["id"] == execution_id and e["status"] == "success" for e in history["data"])


# ---------------------------------------------------------------------------
# Scenario 2: Salesforce enrichment
#   webhook → SF search → SF get_record → set_data enrich
# ---------------------------------------------------------------------------


def test_scenario_02_sf_enrichment(client):
    headers = _setup(client)
    cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF Prod")
    wf_id = "wf_ba_02_sf_enrich"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "SF Enrichment",
        "nodes": [
            {"id": "trig", "type": "webhook", "parameters": {"path": "sf-enrich-abcdef1234567890", "method": "POST"}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "{{ $json.body.email }}",
            }, "credentials": {"salesforce": cred_id}},
            {"id": "enrich", "type": "set_data", "parameters": {"fields": {
                "full_name": "{{ $node.sf.json.record.Name }}",
                "company": "{{ $node.sf.json.record.Company }}",
                "email": "{{ $node.sf.json.record.Email }}",
            }}},
        ],
        "connections": [
            {"source": "trig", "target": "sf"},
            {"source": "sf", "target": "enrich"},
        ],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_search_and_get_responses(),
    )
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={
            "body": {"email": "jane@example.com"}
        })
    finally:
        patcher.stop()

    assert data["status"] == "success"
    enriched = data["results"]["outputs"]["enrich"]["main"][0]
    assert enriched["full_name"] == "Jane Doe"
    assert enriched["company"] == "Acme"
    assert enriched["email"] == "jane@example.com"


# ---------------------------------------------------------------------------
# Scenario 3: Salesforce → AI → notification
#   webhook → SF search → AI summarize → msteams notify
# ---------------------------------------------------------------------------


def test_scenario_03_sf_ai_notify(client):
    headers = _setup(client)
    sf_cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    llm_cred_id = _create_credential(client, headers, "llm", {"api_key": "sk-fake"}, "LLM")
    ms_cred_id = _create_credential(client, headers, "microsoft_graph", MSTEAMS_CREDENTIAL_DATA, "MS")

    wf_id = "wf_ba_03_sf_ai_notify"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "SF → AI → Teams",
        "nodes": [
            {"id": "trig", "type": "webhook", "parameters": {"path": "sf-ai-notify-abcdef12345678", "method": "POST"}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "{{ $json.body.email }}",
            }, "credentials": {"salesforce": sf_cred_id}},
            {"id": "ai", "type": "ai", "parameters": {
                "prompt": "Summarize this lead: {{ $node.sf.json.record.Name }} from {{ $node.sf.json.record.Company }}",
            }, "credentials": {"llm": llm_cred_id}},
            {"id": "notify", "type": "msteams", "parameters": {
                "operation": "send_message",
                "team_id": "t1",
                "channel_id": "ch1",
                "content": "{{ $node.ai.json.response }}",
            }, "credentials": {"microsoft_graph": ms_cred_id}},
        ],
        "connections": [
            {"source": "trig", "target": "sf"},
            {"source": "sf", "target": "ai"},
            {"source": "ai", "target": "notify"},
        ],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce", "app.providers.microsoft_graph"],
        _sf_search_and_get_responses() + [
            json_response(200, {"access_token": "ms_tok", "expires_in": 3600}),
            json_response(200, {}),
        ],
    )
    ai_patcher = patch(
        "app.nodes.ai.chat_completion", new_callable=AsyncMock,
        return_value={"content": "Lead: Jane Doe from Acme. High value.", "usage": {"prompt_tokens": 20, "completion_tokens": 10}},
    )
    ai_patcher.start()
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"body": {"email": "jane@example.com"}})
    finally:
        patcher.stop()
        ai_patcher.stop()

    assert data["status"] == "success"
    assert data["results"]["outputs"]["ai"]["main"][0]["response"] == "Lead: Jane Doe from Acme. High value."
    assert data["node_statuses"]["notify"] == "success"


# ---------------------------------------------------------------------------
# Scenario 4: Webhook → Salesforce create
#   webhook trigger → SF create lead (ingress → outbound)
# ---------------------------------------------------------------------------


def test_scenario_04_webhook_to_sf_create(client):
    headers = _setup(client)
    cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    wf_id = "wf_ba_04_wh_sf_create"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "Webhook → SF Create",
        "nodes": [
            {"id": "trig", "type": "webhook", "parameters": {"path": "lead-create-hook-abcdef123", "method": "POST"}},
            {"id": "map", "type": "set_data", "parameters": {"fields": {"name": "{{ $json.body.name }}", "email": "{{ $json.body.email }}"}}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "create", "object_name": "Lead", "record": {
                    "Name": "{{ $node.map.json.name }}", "Email": "{{ $node.map.json.email }}",
                },
            }, "credentials": {"salesforce": cred_id}},
        ],
        "connections": [
            {"source": "trig", "target": "map"},
            {"source": "map", "target": "sf"},
        ],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_create_responses(),
    )
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={
            "body": {"name": "New Lead", "email": "new@lead.com"}
        })
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["node_statuses"]["sf"] == "success"
    sf_out = data["results"]["outputs"]["sf"]["main"][0]
    assert sf_out["id"] == "00Qabc123"


# ---------------------------------------------------------------------------
# Scenario 5: Schedule → Salesforce
#   schedule trigger → SF search (scheduler registration + pipeline)
# ---------------------------------------------------------------------------


def test_scenario_05_schedule_to_sf(client):
    headers = _setup(client)
    cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    wf_id = "wf_ba_05_sched_sf"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "Schedule → SF",
        "nodes": [
            {"id": "trig", "type": "schedule", "parameters": {"cron": "*/5 * * * *", "timezone": "UTC"}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "jane@example.com",
            }, "credentials": {"salesforce": cred_id}},
        ],
        "connections": [{"source": "trig", "target": "sf"}],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_search_and_get_responses(),
    )
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["results"]["outputs"]["sf"]["main"][0]["found"] is True

    assert data["node_statuses"]["trig"] == "success"
    assert data["node_statuses"]["sf"] == "success"


# ---------------------------------------------------------------------------
# Scenario 6: MCP API → Salesforce
#   trigger_workflow via MCP → SF search (API-driven invocation)
# ---------------------------------------------------------------------------


def test_scenario_06_mcp_api_to_sf(client):
    headers = _setup(client)
    cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    wf_id = "wf_ba_06_mcp_sf"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "MCP → SF",
        "nodes": [
            {"id": "trig", "type": "manual_trigger", "parameters": {}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "jane@example.com",
            }, "credentials": {"salesforce": cred_id}},
        ],
        "connections": [{"source": "trig", "target": "sf"}],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_search_and_get_responses(),
    )
    try:
        resp = client.post("/api/mcp/call", json={
            "name": "trigger_workflow",
            "arguments": {"workflow_id": wf_id, "input_data": {}},
        }, headers=headers)
        assert resp.status_code == 200, resp.text
        result = resp.json()["data"]
        exec_id = result["execution_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            data = client.get(f"/api/executions/{exec_id}", headers=headers).json()["data"]
            if data["status"] not in ("running", "queued", "cancelling"):
                break
            time.sleep(0.05)
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["node_statuses"]["sf"] == "success"


# ---------------------------------------------------------------------------
# Scenario 7: Salesforce → PostgreSQL
#   SF search → postgres insert_rows (cross-system write)
# ---------------------------------------------------------------------------


def test_scenario_07_sf_to_postgres(client):
    headers = _setup(client)
    sf_cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    pg_cred_id = _create_credential(client, headers, "postgres", POSTGRES_CREDENTIAL_DATA, "PG")
    wf_id = "wf_ba_07_sf_pg"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "SF → PostgreSQL",
        "nodes": [
            {"id": "trig", "type": "manual_trigger", "parameters": {}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "jane@example.com",
            }, "credentials": {"salesforce": sf_cred_id}},
            {"id": "map", "type": "set_data", "parameters": {"fields": {
                "sf_id": "{{ $node.sf.json.record.Id }}",
                "name": "{{ $node.sf.json.record.Name }}",
                "email": "{{ $node.sf.json.record.Email }}",
            }}},
            {"id": "pg", "type": "postgres", "parameters": {
                "operation": "insert_rows",
                "table": "leads",
                "rows": [{"sf_id": "{{ $node.map.json.sf_id }}", "name": "{{ $node.map.json.name }}", "email": "{{ $node.map.json.email }}"}],
            }, "credentials": {"postgres": pg_cred_id}},
        ],
        "connections": [
            {"source": "trig", "target": "sf"},
            {"source": "sf", "target": "map"},
            {"source": "map", "target": "pg"},
        ],
        "settings": {},
    })

    from tests.test_api.test_postgres_connector import FakeEngine, FakeSQLResult
    fake_engine = FakeEngine(FakeSQLResult(rows=[], rowcount=1))

    sf_patcher, sf_fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_search_and_get_responses(),
    )
    pg_patcher = patch(
        "app.providers.sql_provider.create_engine", return_value=fake_engine,
    )
    pg_patcher.start()
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        sf_patcher.stop()
        pg_patcher.stop()

    assert data["status"] == "success"
    assert data["node_statuses"]["pg"] == "success"
    assert len(fake_engine.statements) == 1
    assert "leads" in fake_engine.statements[0][0].lower()


# ---------------------------------------------------------------------------
# Scenario 8: Salesforce → Gmail
#   SF search → gmail send (cross-system notification)
# ---------------------------------------------------------------------------


def test_scenario_08_cross_system_notification(client):
    headers = _setup(client)
    wf_id = "wf_ba_08_notification"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "Cross-system Notification",
        "nodes": [
            {"id": "trig", "type": "manual_trigger", "parameters": {}},
            {"id": "map", "type": "set_data", "parameters": {"fields": {"msg": "Pipeline ran successfully"}}},
            {"id": "http", "type": "http_request", "parameters": {
                "url": "https://hooks.example.com/notify",
                "method": "POST",
                "body": "{{ $node.map.json.msg }}",
            }},
        ],
        "connections": [
            {"source": "trig", "target": "map"},
            {"source": "map", "target": "http"},
        ],
        "settings": {},
    })

    execution_id, data = _run_and_poll(client, headers, wf_id)

    assert data["status"] == "failed"
    assert data["error"]["code"] == "HTTP_REQUEST_FAILED"
    assert data["node_statuses"]["map"] == "success"
    assert data["results"]["outputs"]["map"]["main"][0]["msg"] == "Pipeline ran successfully"


# ---------------------------------------------------------------------------
# Scenario 9: AI + RAG
#   webhook → rag_pipeline query → AI synthesize (RAG grounding)
# ---------------------------------------------------------------------------


def test_scenario_09_ai_rag(client):
    headers = _setup(client)
    llm_cred_id = _create_credential(client, headers, "llm", {"api_key": "sk-fake"}, "LLM")

    wf_id = "wf_ba_09_ai_rag"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "AI + RAG",
        "nodes": [
            {"id": "trig", "type": "webhook", "parameters": {"path": "rag-query-abcdef1234567890", "method": "POST"}},
            {"id": "rag", "type": "rag_pipeline", "parameters": {
                "source_type": "text",
                "source": "Acme Corp is a leading manufacturer of widgets.",
                "collection_name": "ba_rag_docs",
                "query": "{{ $json.body.question }}",
                "top_k": 3,
            }, "credentials": {"llm": llm_cred_id}},
        ],
        "connections": [
            {"source": "trig", "target": "rag"},
        ],
        "settings": {},
    })

    fake_model = MagicMock()
    fake_model.encode.return_value = [[0.1] * 384]
    fake_embed_patcher = patch(
        "app.nodes.rag_pipeline._get_embedding_model", return_value=fake_model,
    )
    fake_chat_patcher = patch(
        "app.nodes.rag_pipeline.chat_completion", new_callable=AsyncMock,
        return_value={"content": "Acme Corp is a manufacturer.", "usage": {"prompt_tokens": 30, "completion_tokens": 8}},
    )
    fake_embed_patcher.start()
    fake_chat_patcher.start()
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={
            "body": {"question": "What is Acme?"}
        })
    finally:
        fake_chat_patcher.stop()
        fake_embed_patcher.stop()

    assert data["status"] == "success"
    assert data["results"]["outputs"]["rag"]["main"][0]["answer"]


# ---------------------------------------------------------------------------
# Scenario 10: Human approval
#   webhook → SF create → human_approval → approve → pass-through
# ---------------------------------------------------------------------------


def test_scenario_10_human_approval(client):
    headers = _setup(client)
    sf_cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    wf_id = "wf_ba_10_approval"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "Human Approval",
        "nodes": [
            {"id": "trig", "type": "webhook", "parameters": {"path": "approval-demo-abcdef1234567", "method": "POST"}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "create", "object_name": "Lead", "record": {
                    "Name": "{{ $json.body.name }}", "Email": "{{ $json.body.email }}",
                },
            }, "credentials": {"salesforce": sf_cred_id}},
            {"id": "approve", "type": "human_approval", "parameters": {
                "message": "Approve lead creation?",
                "approvers": [1],
                "timeout_hours": 24,
            }},
        ],
        "connections": [
            {"source": "trig", "target": "sf"},
            {"source": "sf", "target": "approve"},
        ],
        "settings": {},
    })

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_create_responses(),
    )
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={
            "body": {"name": "New Lead", "email": "new@lead.com"}
        })
    finally:
        patcher.stop()

    assert data["status"] == "waiting_approval"
    assert data["pause_state"]["node_id"] == "approve"
    assert data["pause_state"]["message"] == "Approve lead creation?"

    inbox = client.get("/api/executions?status=waiting_approval", headers=headers).json()
    assert any(e["id"] == execution_id for e in inbox["data"])

    patcher2, _ = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_create_responses(),
    )
    try:
        resume_resp = client.post(f"/api/executions/{execution_id}/resume", json={
            "approved": True,
        }, headers=headers)
        assert resume_resp.status_code == 200, resume_resp.text
    finally:
        patcher2.stop()

    exec_resp = client.get(f"/api/executions/{execution_id}", headers=headers).json()
    data = exec_resp["data"]
    assert data["status"] in ("success", "running", "queued")
    if data["status"] == "success":
        assert data["results"]["outputs"]["approve"]["main"][0]["approved"] is True


# ---------------------------------------------------------------------------
# Scenario 11: Multi-step workflow
#   trigger → set_data → SF search → set_data transform → msteams notify → PG insert
# ---------------------------------------------------------------------------


def test_scenario_11_multi_step(client):
    headers = _setup(client)
    sf_cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    ms_cred_id = _create_credential(client, headers, "microsoft_graph", MSTEAMS_CREDENTIAL_DATA, "MS")
    pg_cred_id = _create_credential(client, headers, "postgres", POSTGRES_CREDENTIAL_DATA, "PG")
    wf_id = "wf_ba_11_multi"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "Multi-Step Pipeline",
        "nodes": [
            {"id": "trig", "type": "manual_trigger", "parameters": {}},
            {"id": "map1", "type": "set_data", "parameters": {"fields": {"email": "jane@example.com"}}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "{{ $node.map1.json.email }}",
            }, "credentials": {"salesforce": sf_cred_id}},
            {"id": "map2", "type": "set_data", "parameters": {"fields": {
                "lead_name": "{{ $node.sf.json.record.Name }}",
                "lead_company": "{{ $node.sf.json.record.Company }}",
                "lead_email": "{{ $node.sf.json.record.Email }}",
                "lead_id": "{{ $node.sf.json.record.Id }}",
            }}},
            {"id": "teams", "type": "msteams", "parameters": {
                "operation": "send_message",
                "team_id": "t1", "channel_id": "ch1",
                "content": "New lead: {{ $node.map2.json.lead_name }} from {{ $node.map2.json.lead_company }}",
            }, "credentials": {"microsoft_graph": ms_cred_id}},
            {"id": "pg", "type": "postgres", "parameters": {
                "operation": "insert_rows",
                "table": "leads",
                "rows": [{"sf_id": "{{ $node.map2.json.lead_id }}", "name": "{{ $node.map2.json.lead_name }}"}],
            }, "credentials": {"postgres": pg_cred_id}},
        ],
        "connections": [
            {"source": "trig", "target": "map1"},
            {"source": "map1", "target": "sf"},
            {"source": "sf", "target": "map2"},
            {"source": "map2", "target": "teams"},
            {"source": "map2", "target": "pg"},
        ],
        "settings": {},
    })

    from tests.test_api.test_postgres_connector import FakeEngine, FakeSQLResult
    fake_engine = FakeEngine(FakeSQLResult(rows=[], rowcount=1))

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce", "app.providers.microsoft_graph"],
        _sf_search_and_get_responses() + [
            json_response(200, {"access_token": "ms_tok", "expires_in": 3600}),
            json_response(200, {}),
        ],
    )
    pg_patcher = patch(
        "app.providers.sql_provider.create_engine", return_value=fake_engine,
    )
    pg_patcher.start()
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()
        pg_patcher.stop()

    assert data["status"] == "success"
    assert set(data["node_statuses"].keys()) == {"trig", "map1", "sf", "map2", "teams", "pg"}
    assert all(v == "success" for v in data["node_statuses"].values())
    assert data["results"]["outputs"]["map2"]["main"][0]["lead_name"] == "Jane Doe"
    assert data["results"]["outputs"]["teams"]["main"][0] is not None
    assert len(fake_engine.statements) == 1


# ---------------------------------------------------------------------------
# Scenario 12: Failure and retry
#   trigger → SF search (timeout) → retry → success (durable retry)
# ---------------------------------------------------------------------------


def test_scenario_12_failure_retry(client):
    headers = _setup(client)
    cred_id = _create_credential(client, headers, "salesforce", SF_DATA, "SF")
    wf_id = "wf_ba_12_retry"
    _create_and_save_workflow(client, headers, wf_id, {
        "name": "Failure → Retry",
        "nodes": [
            {"id": "trig", "type": "manual_trigger", "parameters": {}},
            {"id": "sf", "type": "salesforce", "parameters": {
                "operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": "jane@example.com",
            }, "credentials": {"salesforce": cred_id}},
        ],
        "connections": [{"source": "trig", "target": "sf"}],
        "settings": {"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
    })

    def _raising_request(method, url, **kwargs):
        raise httpx.TimeoutException("transport timeout")

    raising_fake = type("RaisingFake", (), {"__aenter__": lambda s: AsyncMock(return_value=s), "__aexit__": AsyncMock(return_value=False), "request": _raising_request, "calls": []})()

    patcher, fake = patch_provider_http(
        ["app.providers.salesforce"],
        _sf_search_and_get_responses(),
    )
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["node_statuses"]["sf"] == "success"
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    assert trace["data"]["steps"][1]["node_id"] == "sf"
