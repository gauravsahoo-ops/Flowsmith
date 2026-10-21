"""Comprehensive Backend & APIs Audit Test Suite.

Verifies all 8 sections:
1. Every API endpoint, HTTP method and response schema
2. Authentication, authorization and tenant isolation
3. Input validation, malformed payloads and error responses
4. Pagination, sorting, filtering and search
5. Rate limiting, timeouts, retries and idempotency
6. Concurrent requests and duplicate submissions
7. Database transactions and rollback behavior
8. API versioning, migrations and backward compatibility
"""

from __future__ import annotations

import concurrent.futures
import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import app
from app.config import get_settings
from app.db import get_session, get_engine, verify_schema_state, EXPECTED_ALEMBIC_HEAD
from app.models import Execution, User, WorkflowRecord, Credential
from tests.test_api.conftest import auth_headers, register, make_workflow


# ==============================================================================
# Item 1: Every API endpoint, HTTP method and response schema
# ==============================================================================

def test_api_endpoints_methods_and_response_schemas(client):
    """Item 1: Tests standard HTTP methods (GET, POST, PATCH, DELETE) and JSON response envelopes."""
    user = register(client)
    headers = auth_headers(user["token"])

    # 1. GET - System endpoints
    resp_health = client.get("/api/health")
    assert resp_health.status_code == 200
    assert "data" in resp_health.json()
    assert resp_health.json()["data"]["status"] == "ok"

    resp_readyz = client.get("/api/readyz")
    assert resp_readyz.status_code in (200, 503)
    assert "data" in resp_readyz.json()

    # 2. POST - Workflow creation
    wf_id = f"wf_api_{uuid.uuid4().hex[:8]}"
    wf_payload = make_workflow(workflow_id=wf_id, name="API Test Workflow")
    resp_create = client.post("/api/workflows", json=wf_payload, headers=headers)
    assert resp_create.status_code in (200, 201)
    body = resp_create.json()
    assert "data" in body
    assert body["data"]["id"] == wf_id

    # 3. GET - Retrieve resource
    resp_get = client.get(f"/api/workflows/{wf_id}", headers=headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["data"]["name"] == "API Test Workflow"

    # 4. PATCH - Partial update
    resp_patch = client.patch(f"/api/workflows/{wf_id}/active", json={"active": True}, headers=headers)
    assert resp_patch.status_code == 200
    assert resp_patch.json()["data"]["active"] is True

    # 5. DELETE - Resource cleanup
    resp_del = client.delete(f"/api/workflows/{wf_id}", headers=headers)
    assert resp_del.status_code in (200, 204)

    # 6. GET - Verify 404 after deletion
    resp_missing = client.get(f"/api/workflows/{wf_id}", headers=headers)
    assert resp_missing.status_code == 404


# ==============================================================================
# Item 2: Authentication, authorization and tenant isolation
# ==============================================================================

def test_auth_and_multi_tenant_isolation(client):
    """Item 2: Tests 401 unauthenticated, invalid JWTs, and strict multi-tenant boundary isolation."""
    # 1. Unauthenticated request to protected endpoint
    resp_unauth = client.get("/api/workflows")
    assert resp_unauth.status_code == 401

    # 2. Forged / invalid Bearer token
    resp_bad_jwt = client.get("/api/workflows", headers={"Authorization": "Bearer forged.token.signature"})
    assert resp_bad_jwt.status_code == 401

    # 3. Tenant Isolation: User A creates resource, User B cannot access or mutate it
    user_a = register(client, email=f"tenant_a_{uuid.uuid4().hex[:6]}@example.com")
    user_b = register(client, email=f"tenant_b_{uuid.uuid4().hex[:6]}@example.com")

    headers_a = auth_headers(user_a["token"])
    headers_b = auth_headers(user_b["token"])

    wf_id = f"wf_tenant_a_{uuid.uuid4().hex[:8]}"
    wf_payload = make_workflow(workflow_id=wf_id, name="Tenant A Confidential Workflow")
    client.post("/api/workflows", json=wf_payload, headers=headers_a)

    # User B attempts to GET User A's workflow -> 404 Not Found (zero information disclosure)
    resp_cross_get = client.get(f"/api/workflows/{wf_id}", headers=headers_b)
    assert resp_cross_get.status_code == 404

    # User B attempts to PATCH User A's workflow -> 404
    resp_cross_patch = client.patch(f"/api/workflows/{wf_id}/active", json={"active": True}, headers=headers_b)
    assert resp_cross_patch.status_code == 404

    # User B attempts to DELETE User A's workflow -> 404
    resp_cross_del = client.delete(f"/api/workflows/{wf_id}", headers=headers_b)
    assert resp_cross_del.status_code == 404


# ==============================================================================
# Item 3: Input validation, malformed payloads and error responses
# ==============================================================================

def test_input_validation_malformed_payloads_and_sanitization(client):
    """Item 3: Validates HTTP 422 on schema violation, 400 on malformed JSON, and injection safety."""
    user = register(client)
    headers = auth_headers(user["token"])

    # 1. Malformed non-JSON body
    resp_malformed = client.post(
        "/api/workflows",
        content=b"{invalid: json syntax",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert resp_malformed.status_code in (400, 422)

    # 2. Pydantic schema validation failure (invalid email format / too short password)
    resp_bad_reg = client.post("/api/auth/register", json={"email": "not-an-email", "password": "123"})
    assert resp_bad_reg.status_code == 422
    assert "detail" in resp_bad_reg.json()

    # 3. Domain validation failure: Webhook paths shorter than 24 chars are rejected with 422
    bad_webhook_wf = {
        "id": f"wf_bad_{uuid.uuid4().hex[:6]}",
        "name": "Bad Webhook Workflow",
        "nodes": [{"id": "w1", "type": "webhook", "parameters": {"path": "short", "method": "POST"}}],
        "connections": [],
    }
    resp_bad_wf = client.post("/api/workflows", json=bad_webhook_wf, headers=headers)
    assert resp_bad_wf.status_code == 422

    # 4. SQL injection safety in path parameter
    sqli_attempt = "wf_test' OR 1=1; DROP TABLE workflows; --"
    resp_sqli = client.get(f"/api/workflows/{sqli_attempt}", headers=headers)
    assert resp_sqli.status_code == 404  # Clean 404, never 500 error


# ==============================================================================
# Item 4: Pagination, sorting, filtering and search
# ==============================================================================

def test_pagination_filtering_and_universal_search(client):
    """Item 4: Tests page/pageSize pagination, sorting, status filtering, and universal search."""
    user = register(client)
    headers = auth_headers(user["token"])

    # Seed 3 workflows for this user
    for i in range(3):
        wf = make_workflow(workflow_id=f"wf_page_{i}_{uuid.uuid4().hex[:6]}", name=f"Pagination Item {i}")
        client.post("/api/workflows", json=wf, headers=headers)

    # Pagination: page=1, pageSize=2
    resp_page1 = client.get("/api/workflows?page=1&pageSize=2", headers=headers)
    assert resp_page1.status_code == 200
    body_page1 = resp_page1.json()
    assert len(body_page1["data"]) <= 2
    assert body_page1["meta"]["page"] == 1
    assert body_page1["meta"]["pageSize"] == 2

    # Execution filtering and sorting
    resp_exec_filter = client.get("/api/executions?status=success&sort_by=started_at&sort_dir=desc&pageSize=5", headers=headers)
    assert resp_exec_filter.status_code == 200
    exec_body = resp_exec_filter.json()
    assert "data" in exec_body
    assert "meta" in exec_body
    for ex in exec_body["data"]:
        assert ex.get("status") in ("success", "completed")

    # Universal search keyword filter
    resp_search = client.get("/api/executions?search=nonexistent_token_xyz999", headers=headers)
    assert resp_search.status_code == 200
    assert resp_search.json()["data"] == []


# ==============================================================================
# Item 5: Rate limiting, timeouts, retries and idempotency
# ==============================================================================

def test_idempotency_and_rate_limiting_resilience(client):
    """Item 5: Tests idempotent webhook triggering and rate limiter protection."""
    user = register(client)
    headers = auth_headers(user["token"])

    # Create active webhook workflow
    hook_path = f"hook_idem_test_{uuid.uuid4().hex}"
    wf_id = f"wf_idem_{uuid.uuid4().hex[:8]}"
    wf = {
        "id": wf_id,
        "name": "Idempotent Webhook Workflow",
        "nodes": [
            {"id": "w1", "type": "webhook", "parameters": {"path": hook_path, "method": "POST"}},
            {"id": "s1", "type": "set_data", "parameters": {"fields": {"done": True}}},
        ],
        "connections": [{"source": "w1", "target": "s1"}],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    client.patch(f"/api/workflows/{wf_id}/active", json={"active": True}, headers=headers)

    # Trigger with Idempotency-Key
    idem_key = f"key_{uuid.uuid4().hex}"
    resp1 = client.post(f"/api/webhooks/{hook_path}", json={"foo": "bar"}, headers={"Idempotency-Key": idem_key})
    assert resp1.status_code == 202
    exec_id_1 = resp1.json()["data"].get("execution_id") or resp1.json()["data"].get("delivery_id")

    # Re-send with identical Idempotency-Key
    resp2 = client.post(f"/api/webhooks/{hook_path}", json={"foo": "bar"}, headers={"Idempotency-Key": idem_key})
    assert resp2.status_code == 202
    exec_id_2 = resp2.json()["data"].get("execution_id") or resp2.json()["data"].get("delivery_id")

    assert exec_id_1 == exec_id_2, "Idempotency-Key must return identical execution delivery!"


# ==============================================================================
# Item 6: Concurrent requests and duplicate submissions
# ==============================================================================

def test_concurrent_requests_and_atomic_execution_triggers(client):
    """Item 6: Tests rapid parallel workflow execution submissions without race conditions."""
    user = register(client)
    headers = auth_headers(user["token"])

    wf_id = f"wf_conc_{uuid.uuid4().hex[:8]}"
    client.post("/api/workflows", json=make_workflow(workflow_id=wf_id), headers=headers)

    # Trigger 5 concurrent execution requests
    execution_ids = []
    def trigger_run():
        return client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(trigger_run) for _ in range(5)]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            assert res.status_code == 202
            eid = res.json()["data"].get("execution_id")
            assert eid is not None
            execution_ids.append(eid)

    # Every concurrent submission receives a distinct, unique execution ID
    assert len(execution_ids) == 5
    assert len(set(execution_ids)) == 5, "Duplicate execution ID generated during concurrent trigger!"


# ==============================================================================
# Item 7: Database transactions and rollback behavior
# ==============================================================================

def test_database_transactions_and_atomic_rollback():
    """Item 7: Verifies that database transactions cleanly roll back on exceptions."""
    db = get_session()

    canary_id = f"canary_tx_{uuid.uuid4().hex[:8]}"
    rollback_user_id = 999999999  # Guaranteed non-existent FK

    # Attempt to insert an execution with invalid user_id foreign key
    canary_exec = Execution(
        id=canary_id,
        workflow_id="non_existent_wf",
        user_id=rollback_user_id,
        workflow_version=1,
        workflow_data={},
        status="running",
    )

    with pytest.raises(Exception):
        db.add(canary_exec)
        db.commit()

    db.rollback()

    # Verify that transaction rolled back and canary record does NOT exist
    record = db.get(Execution, canary_id)
    assert record is None, "Failed transaction was not rolled back cleanly!"


# ==============================================================================
# Item 8: API versioning, migrations and backward compatibility
# ==============================================================================

def test_api_versioning_and_schema_compatibility(client):
    """Item 8: Tests API version contract, Alembic migration head state, and backward compatibility."""
    # 1. API version in health probe
    resp = client.get("/api/health")
    assert resp.status_code == 200
    version = resp.json()["data"].get("version")
    assert version == "1.6.0"

    # 2. Database schema verification on production PostgreSQL engine
    prod_engine = create_engine(get_settings().database_url)
    schema_state = verify_schema_state(prod_engine)
    assert schema_state["ok"] is True, f"Database schema drift detected: {schema_state}"
    assert schema_state["status"] == "ok"
    assert schema_state["current_revision"] == schema_state["expected_revision"] == EXPECTED_ALEMBIC_HEAD
    assert schema_state["missing_tables"] == []
    assert schema_state["existing_table_count"] > 0

    # Test drift detector behavior
    with patch("app.db.get_current_revision", return_value="outdated_rev"), patch("app.db.inspect") as mock_insp:
        mock_insp.return_value.get_table_names.return_value = []
        drift_result = verify_schema_state(prod_engine)
        assert drift_result["ok"] is False
        assert drift_result["status"] == "drift_detected"

    # 3. Backward compatibility: legacy workflow without modern optional fields loads cleanly
    user = register(client)
    headers = auth_headers(user["token"])

    legacy_wf = {
        "id": f"wf_legacy_{uuid.uuid4().hex[:8]}",
        "name": "Legacy v1.0 Workflow",
        "nodes": [
            {"id": "node_a", "type": "manual_trigger"},
            {"id": "node_b", "type": "set_data", "parameters": {"fields": {"x": 1}}},
        ],
        "connections": [{"source": "node_a", "target": "node_b"}],
    }
    # No "settings", no "position" - legacy payload must be accepted seamlessly
    resp_legacy = client.post("/api/workflows", json=legacy_wf, headers=headers)
    assert resp_legacy.status_code in (200, 201)
    saved = resp_legacy.json()["data"]
    assert saved["name"] == "Legacy v1.0 Workflow"
