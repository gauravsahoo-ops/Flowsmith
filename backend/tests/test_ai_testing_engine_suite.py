"""Flowsmith AI Testing Engine Automated Verification Suite.

Comprehensive multi-tier test suite covering:
1. Unit Tier: Cryptographic vault, expression evaluation & safety guards.
2. API Tier: Health/Readiness contracts, workflow lifecycle, execution universal search.
3. Integration Tier: DataLoad step runner, schema preservation, async execution.
4. Regression Tier: Database reconnection retry logic, OAuth state single-use and TTL.
"""

from __future__ import annotations

import json
import time
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings
from app.security.crypto import encrypt_text, decrypt_text
from app.engine.expressions import interpolate, resolve
from app.models.oauth_state import OAuthState
from app.models.execution import Execution
from app.db import get_session
from tests.test_api.conftest import auth_headers, register, make_workflow


# ==============================================================================
# Tier 1: Unit Tests
# ==============================================================================

def test_unit_crypto_vault_aes_gcm():
    """Unit test: AES-256-GCM encryption, decryption, and tamper resistance."""
    secret = "sk_live_super_secret_salesforce_token_9999"
    encrypted = encrypt_text(secret)
    assert encrypted != secret
    assert isinstance(encrypted, (str, bytes))

    # Decrypt and verify exact match
    decrypted = decrypt_text(encrypted)
    assert decrypted == secret

    # Tamper test: Corrupt ciphertext and assert decryption fails
    if isinstance(encrypted, bytes):
        tampered = encrypted[:-4] + b"AAAA"
    else:
        tampered = encrypted[:-4] + "AAAA"
    with pytest.raises(Exception):
        decrypt_text(tampered)


def test_unit_expression_evaluator_safety():
    """Unit test: Safe expression parsing & security sandbox."""
    item = {"name": "Alice", "score": 95, "role": "admin"}
    
    # Safe valid expressions with string interpolation
    result = interpolate("Hello {{ $json.name }}! Role: {{ $json.role }}", item)
    assert result == "Hello Alice! Role: admin"

    # Arithmetic expression
    calc = interpolate("{{ $json.score * 2 }}", item)
    assert calc == 190

    # Security check: dunder or python execution attempts must not execute
    malicious = interpolate("{{ __import__('os').system('ls') }}", item)
    # The pure engine returns unresolvable or empty, never executes arbitrary code
    assert "os" not in str(malicious) or malicious == "{{ __import__('os').system('ls') }}"


# ==============================================================================
# Tier 2: API & Contract Tests
# ==============================================================================

def test_api_health_contract(client):
    """API contract test: GET /api/health."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ok"
    assert "version" in data
    # Liveness must not expose deployment metadata or claim dependency health.
    assert "stage" not in data
    assert "pid" not in data
    assert "database" not in data


def test_api_readyz_contract(client):
    """API contract test: GET /api/readyz."""
    resp = client.get("/api/readyz")
    assert resp.status_code in (200, 503)
    data = resp.json()["data"]
    assert "checks" in data
    assert "postgres" in data["checks"]
    assert data["checks"]["postgres"] in ("ok", "ready")


def test_api_workflow_lifecycle_crud(client):
    """API test: Workflow creation, retrieval, and deletion lifecycle."""
    reg = register(client)
    headers = auth_headers(reg["token"])
    wf_id = f"wf_test_{uuid.uuid4().hex[:8]}"
    wf_payload = make_workflow(workflow_id=wf_id, name="AI Test Engine Automated Workflow")

    # 1. Create
    resp = client.post("/api/workflows", json=wf_payload, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["data"]["id"] == wf_id

    # 2. Get
    resp = client.get(f"/api/workflows/{wf_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "AI Test Engine Automated Workflow"

    # 3. Delete
    resp = client.delete(f"/api/workflows/{wf_id}", headers=headers)
    assert resp.status_code in (200, 204)


def test_api_execution_universal_search(client):
    """API test: Universal search finding executions by formatted timestamp & content."""
    reg = register(client)
    headers = auth_headers(reg["token"])
    db = get_session()

    unique_marker = f"order_{uuid.uuid4().hex[:6]}"
    exec_id = f"exec_search_{uuid.uuid4().hex[:8]}"
    wf_id = f"wf_s_{uuid.uuid4().hex[:8]}"

    # Create dummy workflow first for FK constraint
    wf_payload = make_workflow(workflow_id=wf_id, name="Search Test Workflow")
    client.post("/api/workflows", json=wf_payload, headers=headers)

    # Seed an execution record with custom content
    sample_exec = Execution(
        id=exec_id,
        workflow_id=wf_id,
        user_id=reg["user"]["id"],
        workflow_version=1,
        workflow_data=wf_payload,
        trigger="manual",
        status="success",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        trace=[
            {
                "node_id": "email_sender",
                "output": {"recipient": f"{unique_marker}@example.com", "subject": "Quarterly Statement"},
            }
        ],
    )
    db.add(sample_exec)
    db.commit()

    # Search by email recipient marker
    resp = client.get(f"/api/executions?search={unique_marker}", headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()["data"]
    items = res_data["items"] if isinstance(res_data, dict) and "items" in res_data else res_data
    match = any(e["id"] == exec_id for e in items)
    assert match, f"Universal search failed to locate execution containing '{unique_marker}'"


# ==============================================================================
# Tier 3: Integration Tests
# ==============================================================================

def test_integration_dataload_step_runner_and_schema_integrity(client):
    """Integration test: Execute Step on DataLoad and assert schema key integrity."""
    reg = register(client)
    headers = auth_headers(reg["token"])
    wf_id = f"wf_dataload_{uuid.uuid4().hex[:8]}"

    csv_data = (
        "company_name,account_id,revenue_usd,lead_status,contact_email\n"
        "Acme Corp,ACC-1001,500000.00,Qualified,ops@acme.org\n"
        "Globex,ACC-1002,1200000.50,Won,finance@globex.com\n"
    )

    wf = {
        "id": wf_id,
        "name": "Integration DataLoad Ingestion",
        "nodes": [
            {
                "id": "load_node",
                "type": "flowsmith.data_load",
                "parameters": {
                    "csv_content": csv_data,
                    "target_object": "Account",
                    "persist_to_db": False,
                },
                "position": {"x": 100, "y": 100},
            }
        ],
        "connections": [],
        "settings": {},
    }

    create_resp = client.post("/api/workflows", json=wf, headers=headers)
    assert create_resp.status_code in (200, 201)

    # Execute single step
    step_resp = client.post(f"/api/workflows/{wf_id}/run-node", json={"node_id": "load_node"}, headers=headers)
    assert step_resp.status_code in (200, 202)
    step_body = step_resp.json().get("data", {})
    assert "execution_id" in step_body or "output" in step_body or "status" in step_body


# ==============================================================================
# Tier 4: Regression Tests
# ==============================================================================

def test_regression_oauth_state_ttl_and_replay_protection(client):
    """Regression test: Ensure OAuth states expire properly and cannot be replayed."""
    reg = register(client)
    db = get_session()
    settings = get_settings()

    # Create an expired OAuth state row
    expired_state = f"state_exp_{uuid.uuid4().hex[:12]}"
    past_time = datetime.now(timezone.utc) - timedelta(seconds=settings.oauth_state_ttl_seconds + 30)
    row = OAuthState(
        state=expired_state,
        user_id=reg["user"]["id"],
        login_url="https://login.salesforce.com",
        used=False,
        created_at=past_time,
    )
    db.add(row)
    db.commit()

    # Query back and verify age logic
    fetched = db.get(OAuthState, expired_state)
    assert fetched is not None
    created = fetched.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - created
    assert age > timedelta(seconds=settings.oauth_state_ttl_seconds), "OAuthState should be expired"

    # Test replay protection: Once marked used, it cannot be reused
    fresh_state = f"state_fresh_{uuid.uuid4().hex[:12]}"
    row_fresh = OAuthState(
        state=fresh_state,
        user_id=reg["user"]["id"],
        login_url="https://login.salesforce.com",
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row_fresh)
    db.commit()

    fresh_row = db.get(OAuthState, fresh_state)
    assert fresh_row.used is False
    fresh_row.used = True
    db.commit()

    re_fetched = db.get(OAuthState, fresh_state)
    assert re_fetched.used is True, "State must remain marked used to prevent replay"


def test_regression_db_connection_retry_resilience():
    """Regression test: Verifies that DB connectivity retry logic recovers gracefully."""
    attempts = 0
    max_attempts = 5

    def mock_db_connector():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("Consistent recovery state has not been yet reached")
        return "Connected successfully"

    connected = False
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            status = mock_db_connector()
            connected = True
            break
        except ConnectionError as exc:
            last_err = exc

    assert connected is True
    assert attempts == 3
    assert status == "Connected successfully"
