"""Comprehensive automated test suite for Flowsmith Logs & Monitoring Module.

Validates:
1. Real execution engine telemetry lifecycle & record counters extraction.
2. Step-by-step ExecutionStep persistence & timeline DAG telemetry.
3. Outbound ApiRequestTelemetry capture with strict secret redaction.
4. Error taxonomy categorization.
5. API Inspector endpoints (/requests, /requests/{id}, /steps, /timeline).
6. Retry execution with idempotency keys & ExecutionRetryHistory persistence.
7. Centralized logs server-side filtering, searching & sorting.
8. Sanitized CSV export with spreadsheet formula injection defense.
9. Monitoring summary 8-metric aggregation & error breakdown.
10. Strict multi-tenant isolation across all endpoints.
"""

from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

from app.db import get_session
from app.models.execution import Execution
from app.models.monitoring_telemetry import (
    ExecutionStep,
    ApiRequestTelemetry,
    ExecutionRetryHistory,
)
from app.engine.redact import (
    MASK,
    redact_headers,
    redact_payload,
    redact_url,
    sanitize_error,
    sanitize_csv_cell,
)
from tests.test_api.conftest import auth_headers, register, make_workflow


@contextmanager
def session_scope():
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _setup_user(client, email=None):
    reg = register(client, email=email) if email else register(client)
    return auth_headers(reg["token"]), reg["user"]


def _create_execution(session, **kwargs):
    now = datetime.now(timezone.utc)
    wf_id = kwargs.get("workflow_id", "wf_test")
    kwargs.pop("workflow_name", None)
    defaults = {
        "id": f"exec_{uuid.uuid4().hex[:8]}",
        "workflow_id": wf_id,
        "workflow_version": 1,
        "workflow_data": {"id": wf_id, "nodes": []},
        "trigger": "manual",
        "status": "success",
        "started_at": now,
        "finished_at": now,
        "workspace_id": "default",
        "retry_count": 0,
        "records_read": 0,
        "records_created": 0,
        "records_updated": 0,
        "records_skipped": 0,
        "records_failed": 0,
        "records_processed": 0,
    }
    defaults.update(kwargs)
    execution = Execution(**defaults)
    session.add(execution)
    session.flush()
    return execution


def test_redaction_utilities():
    """Verify URL, header, payload, and formula injection sanitization functions."""
    # URL sanitization (query param secret values masked)
    raw_url = "https://api.salesforce.com/services/data/v58.0/sobjects/Contact?token=secret123&client_secret=supersecret"
    clean_url = redact_url(raw_url)
    assert "%E2%80%A2" in clean_url or MASK in clean_url
    assert "secret123" not in clean_url
    assert "supersecret" not in clean_url

    # Header sanitization
    raw_headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer eyJhbGciOi...",
        "X-Api-Key": "secret_key_abc",
        "Cookie": "session=xyz123",
        "Normal-Header": "AllowedValue",
    }
    clean_headers = redact_headers(raw_headers)
    assert clean_headers["Content-Type"] == "application/json"
    assert clean_headers["Authorization"] == MASK
    assert clean_headers["X-Api-Key"] == MASK
    assert clean_headers["Cookie"] == MASK
    assert clean_headers["Normal-Header"] == "AllowedValue"

    # Payload sanitization
    raw_payload = {
        "email": "test@example.com",
        "password": "SuperSecretPassword123!",
        "nested": {
            "api_key": "key_987",
            "normal_field": 42,
        },
    }
    clean_payload, is_truncated = redact_payload(raw_payload)
    assert not is_truncated
    assert clean_payload["email"] == "test@example.com"
    assert clean_payload["password"] == MASK
    assert clean_payload["nested"]["api_key"] == MASK
    assert clean_payload["nested"]["normal_field"] == 42

    # CSV Formula Injection Defense
    assert sanitize_csv_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_csv_cell("-1+1") == "'-1+1"
    assert sanitize_csv_cell("@SUM") == "'@SUM"
    assert sanitize_csv_cell("\tTABBED") == "'\tTABBED"
    assert sanitize_csv_cell("Normal Text") == "Normal Text"
    assert sanitize_csv_cell(12345) == "12345"


def test_error_taxonomy_categorization():
    """Verify error taxonomy mapping for HTTP status codes, timeouts, and validation."""
    cat, code, summary = sanitize_error({"code": "AUTH_FAILED", "message": "Unauthorized access"})
    assert cat == "AUTHENTICATION_ERROR"
    assert code == "AUTH_FAILED"

    cat, code, summary = sanitize_error({"code": "RATE_LIMIT_429", "message": "Too Many Requests"})
    assert cat == "RATE_LIMITED"
    assert code == "RATE_LIMIT_429"

    cat, code, summary = sanitize_error({"code": "TIMEOUT", "message": "Connection timed out after 30000ms"})
    assert cat == "TIMEOUT"
    assert code == "TIMEOUT"

    cat, code, summary = sanitize_error({"code": "VALIDATION_ERROR", "message": "Schema validation failed"})
    assert cat == "VALIDATION_ERROR"


def test_execution_telemetry_persistence_and_api(client):
    """Test full telemetry persistence: steps, API calls, record counts, and API inspection endpoints."""
    headers, user = _setup_user(client)
    wf_id = f"wf_telemetry_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_id, "CRM Sync Integration"), headers=headers)

    exec_id = f"exec_telemetry_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        execution = _create_execution(
            session,
            id=exec_id,
            workflow_id=wf_id,
            user_id=user["id"],
            status="success",
            trigger="webhook",
            started_at=now - timedelta(seconds=5),
            finished_at=now,
            records_read=50,
            records_processed=48,
            records_created=40,
            records_updated=8,
            records_skipped=2,
            records_failed=0,
            source_connector="hubspot",
            destination_connector="salesforce",
            source_object="contacts",
            destination_object="leads",
            http_method="POST",
            api_endpoint="https://api.salesforce.com/services/data/v58.0/composite/sobjects",
            http_status_code=201,
            node_statuses={"hubspot_read": "success", "salesforce_write": "success"},
        )

        step1 = ExecutionStep(
            execution_id=exec_id,
            node_id="hubspot_read",
            node_type="hubspot",
            step_name="Read Contacts from HubSpot",
            status="success",
            started_at=now - timedelta(seconds=5),
            completed_at=now - timedelta(seconds=3),
            duration_ms=2000,
            input_record_count=50,
            output_record_count=50,
            connector_id="hubspot",
        )
        step2 = ExecutionStep(
            execution_id=exec_id,
            node_id="salesforce_write",
            node_type="salesforce",
            step_name="Upsert Leads in Salesforce",
            status="success",
            started_at=now - timedelta(seconds=3),
            completed_at=now,
            duration_ms=3000,
            output_record_count=48,
            created_record_count=40,
            updated_record_count=8,
            skipped_record_count=2,
            failed_record_count=0,
            connector_id="salesforce",
        )
        session.add_all([step1, step2])
        session.flush()

        api_call = ApiRequestTelemetry(
            execution_id=exec_id,
            step_id=step2.id,
            node_id="salesforce_write",
            connector_name="salesforce",
            connector_id="salesforce",
            http_method="POST",
            endpoint_url="https://api.salesforce.com/services/data/v58.0/composite/sobjects",
            http_status_code=201,
            duration_ms=450,
            request_headers={"Authorization": f"Bearer {MASK}", "Content-Type": "application/json"},
            request_payload={"records": [{"LastName": "Smith", "Company": "Acme"}]},
            response_headers={"Content-Type": "application/json"},
            response_payload={"hasErrors": False, "results": [{"id": "00Q5g000001", "success": True}]},
        )
        session.add(api_call)

    # 2. Test GET /api/executions/{id}
    res = client.get(f"/api/executions/{exec_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["id"] == exec_id
    assert data["records_read"] == 50
    assert data["records_processed"] == 48
    assert data["source_connector"] == "hubspot"
    assert data["destination_connector"] == "salesforce"
    assert data["http_status_code"] == 201

    # 3. Test GET /api/executions/{id}/steps
    res = client.get(f"/api/executions/{exec_id}/steps", headers=headers)
    assert res.status_code == 200
    steps = res.json()["data"]
    assert len(steps) == 2
    assert steps[0]["node_id"] == "hubspot_read"

    # 4. Test GET /api/executions/{id}/timeline
    res = client.get(f"/api/executions/{exec_id}/timeline", headers=headers)
    assert res.status_code == 200
    events = res.json()["data"]["events"]
    assert len(events) >= 2

    # 5. Test GET /api/executions/{id}/requests (API Inspector)
    res = client.get(f"/api/executions/{exec_id}/requests", headers=headers)
    assert res.status_code == 200
    reqs = res.json()["data"]
    assert len(reqs) == 1
    assert reqs[0]["connector_name"] == "salesforce"
    assert reqs[0]["http_status_code"] == 201
    assert reqs[0]["http_method"] == "POST"

    # 6. Test GET /api/executions/{id}/requests/{request_id}
    req_id = reqs[0]["id"]
    res = client.get(f"/api/executions/{exec_id}/requests/{req_id}", headers=headers)
    assert res.status_code == 200
    req_detail = res.json()["data"]
    assert MASK in req_detail["request_headers"]["Authorization"]
    assert req_detail["response_payload"]["hasErrors"] is False


def test_retry_execution_and_idempotency(client):
    """Test POST /api/executions/{id}/retry, idempotency keys, and retry history tracking."""
    headers, user = _setup_user(client)
    wf_id = f"wf_retry_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_id, "Order Webhook Sync"), headers=headers)

    # 1. Create a failed execution to retry
    parent_id = f"exec_fail_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        execution = _create_execution(
            session,
            id=parent_id,
            workflow_id=wf_id,
            user_id=user["id"],
            status="failed",
            trigger="webhook",
            started_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=1),
            error_type="RATE_LIMIT",
            error_code="HTTP_429",
            error_summary="Upstream rate limit exceeded. Retry after 60s.",
            workflow_data={"id": wf_id, "nodes": [{"id": "trigger", "type": "manual_trigger"}]},
        )

    # 2. Trigger retry with idempotency key
    idempotency_key = f"key_{uuid.uuid4().hex}"
    res = client.post(
        f"/api/executions/{parent_id}/retry",
        json={"idempotency_key": idempotency_key, "reason": "Rate limit backoff elapsed"},
        headers=headers,
    )
    assert res.status_code == 202
    retry_data = res.json()["data"]
    new_exec_id = retry_data["execution_id"]
    assert new_exec_id != parent_id

    # 3. Test idempotency: re-submitting identical idempotency_key returns original retry
    res_repeat = client.post(
        f"/api/executions/{parent_id}/retry",
        json={"idempotency_key": idempotency_key, "reason": "Repeated submission"},
        headers=headers,
    )
    assert res_repeat.status_code == 202
    assert res_repeat.json()["data"]["execution_id"] == new_exec_id
    assert res_repeat.json()["data"]["idempotent_replay"] is True

    # 4. Check retry history endpoint
    res_hist = client.get(f"/api/executions/{parent_id}/retries", headers=headers)
    assert res_hist.status_code == 200
    retries = res_hist.json()["data"]
    assert len(retries) >= 1
    assert retries[0]["execution_id"] == new_exec_id
    assert retries[0]["attempt_number"] == 1


def test_executions_search_filtering_and_sorting(client):
    """Test listing executions with multi-attribute filtering, search, and sorting."""
    headers, user = _setup_user(client)
    wf_id = f"wf_crm_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_id, "Customer Synchronization"), headers=headers)
    now = datetime.now(timezone.utc)

    # Populate sample executions with distinct statuses, connectors, errors
    with session_scope() as session:
        e1 = _create_execution(
            session,
            id=f"exec_search_1_{uuid.uuid4().hex[:6]}",
            workflow_id=wf_id,
            user_id=user["id"],
            status="success",
            source_connector="hubspot",
            destination_connector="salesforce",
            records_processed=150,
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3) + timedelta(seconds=2),
        )
        e2 = _create_execution(
            session,
            id=f"exec_search_2_{uuid.uuid4().hex[:6]}",
            workflow_id=wf_id,
            user_id=user["id"],
            status="failed",
            source_connector="stripe",
            destination_connector="postgres",
            error_type="AUTH_ERROR",
            error_code="HTTP_401",
            error_summary="Stripe API key expired",
            records_processed=0,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2) + timedelta(seconds=1),
        )
        e3 = _create_execution(
            session,
            id=f"exec_search_3_{uuid.uuid4().hex[:6]}",
            workflow_id=wf_id,
            user_id=user["id"],
            status="running",
            source_connector="hubspot",
            destination_connector="slack",
            records_processed=5,
            started_at=now - timedelta(minutes=10),
            finished_at=None,
        )

    # 1. Filter by connector
    res = client.get("/api/executions?connector=stripe", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) >= 1
    assert any("stripe" in (x.get("source_connector") or "") for x in data)

    # 2. Filter by status
    res = client.get("/api/executions?status=failed", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert all(x["status"] == "failed" for x in data)

    # 3. Filter by error_type
    res = client.get("/api/executions?error_type=AUTH_ERROR", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) >= 1
    assert data[0]["error_type"] == "AUTH_ERROR"

    # 4. Search query
    res = client.get(f"/api/executions?search={e2.id}", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == e2.id

    # 5. Sorting by records_processed descending
    res = client.get("/api/executions?sort_by=records_processed&sort_dir=desc", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    if len(data) >= 2:
        assert data[0]["records_processed"] >= data[1]["records_processed"]


def test_csv_export_with_formula_injection_protection(client):
    """Test GET /api/executions/export returns sanitized CSV preventing spreadsheet formula injection."""
    headers, user = _setup_user(client)
    wf_id = f"wf_sec_{uuid.uuid4().hex[:6]}"
    # Set workflow name with formula
    client.post("/api/workflows", json=make_workflow(wf_id, "=cmd|' /C calc'!A0"), headers=headers)
    now = datetime.now(timezone.utc)

    # Create an execution with malicious formula in summary / error
    malicious_id = f"exec_malicious_{uuid.uuid4().hex[:6]}"
    with session_scope() as session:
        bad_exec = _create_execution(
            session,
            id=malicious_id,
            workflow_id=wf_id,
            user_id=user["id"],
            status="failed",
            error_summary="+2+5*cmd",
            started_at=now,
            finished_at=now,
        )

    res = client.get(f"/api/executions/export?search={malicious_id}", headers=headers)
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    csv_text = res.text

    # Verify formula prefixes: '=' and '+' must be escaped with a single quote "'"
    assert "'=cmd|" in csv_text
    assert "'+2+5*cmd" in csv_text


def test_monitoring_summary_aggregation(client):
    """Test GET /api/monitoring/summary returns 8 metric cards data and error breakdown."""
    headers, user = _setup_user(client)
    wf_id = f"wf_sum_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_id, "Summary Test Flow"), headers=headers)
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        for i in range(5):
            _create_execution(
                session,
                id=f"exec_summary_ok_{i}_{uuid.uuid4().hex[:6]}",
                workflow_id=wf_id,
                user_id=user["id"],
                status="success",
                records_processed=100,
                started_at=now - timedelta(minutes=30),
                finished_at=now - timedelta(minutes=29),
            )

        _create_execution(
            session,
            id=f"exec_summary_fail_{uuid.uuid4().hex[:6]}",
            workflow_id=wf_id,
            user_id=user["id"],
            status="failed",
            error_type="RATE_LIMIT",
            records_processed=0,
            started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=19),
        )

    res = client.get("/api/monitoring/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()["data"]

    assert body["total_executions"] >= 6
    assert body["successful_executions"] >= 5
    assert body["failed_executions"] >= 1
    assert body["success_rate_percent"] > 0
    assert body["total_records_processed"] >= 500
    assert "RATE_LIMIT" in body["error_breakdown"]


def test_multi_tenant_isolation(client):
    """Test that users from Org A cannot read executions, steps, requests, or retries from Org B."""
    headers_a, user_a = _setup_user(client, email=f"user_a_{uuid.uuid4().hex[:6]}@example.com")
    headers_b, user_b = _setup_user(client, email=f"user_b_{uuid.uuid4().hex[:6]}@example.com")

    # User A creates a private workflow
    wf_a = f"wf_private_a_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_a, "Private Workflow A"), headers=headers_a)

    # Create execution for User A's workflow
    exec_a = f"exec_secret_a_{uuid.uuid4().hex[:6]}"
    with session_scope() as session:
        ea = _create_execution(
            session,
            id=exec_a,
            workflow_id=wf_a,
            user_id=user_a["id"],
            status="success",
            started_at=datetime.now(timezone.utc),
        )

    # User A can read
    res_a = client.get(f"/api/executions/{exec_a}", headers=headers_a)
    assert res_a.status_code == 200

    # User B is forbidden (returns 404 to avoid leaking execution presence)
    res_b = client.get(f"/api/executions/{exec_a}", headers=headers_b)
    assert res_b.status_code == 404

    # User B steps check
    assert client.get(f"/api/executions/{exec_a}/steps", headers=headers_b).status_code == 404

    # User B requests check
    assert client.get(f"/api/executions/{exec_a}/requests", headers=headers_b).status_code == 404

    # User B retry check
    assert client.post(f"/api/executions/{exec_a}/retry", json={}, headers=headers_b).status_code == 404


def test_finalize_execution_telemetry_with_notes_and_steps(client):
    """Test finalize_execution_telemetry safely creates ExecutionStep rows with notes and error details."""
    from types import SimpleNamespace
    from app.services.telemetry_service import finalize_execution_telemetry
    from sqlalchemy import select

    headers, user = _setup_user(client)
    wf_id = f"wf_telem_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_id, "Telemetry Test WF"), headers=headers)

    exec_id = f"exec_telem_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    with session_scope() as session:
        rec = _create_execution(
            session,
            id=exec_id,
            workflow_id=wf_id,
            user_id=user["id"],
            status="success",
            started_at=now - timedelta(seconds=10),
            finished_at=now,
            workflow_data={
                "id": wf_id,
                "nodes": [
                    {"id": "node_trigger", "type": "manual_trigger", "name": "Trigger Node"},
                    {"id": "node_salesforce", "type": "salesforce", "name": "Salesforce Upsert"},
                ],
            },
        )
        fake_result = SimpleNamespace(
            trace=[
                {
                    "node_id": "node_trigger",
                    "node_type": "manual_trigger",
                    "status": "success",
                    "duration_ms": 120.0,
                    "inputs": {"records": 10},
                    "outputs": {"records": 10},
                    "note": "Triggered manually",
                },
                {
                    "node_id": "node_salesforce",
                    "node_type": "salesforce",
                    "status": "success",
                    "duration_ms": 450.0,
                    "inputs": {"records": [{"id": 1}]},
                    "outputs": {"records": [{"id": 1, "success": True}]},
                    "note": "Upserted 1 record via Bulk API",
                    "created_record_count": 1,
                },
            ]
        )
        fake_job = SimpleNamespace(workflow_data=rec.workflow_data)

        # Call finalize_execution_telemetry directly
        finalize_execution_telemetry(session, rec, fake_result, fake_job)

    # Verify execution steps were written to DB and are retrievable
    with session_scope() as session:
        steps = session.scalars(
            select(ExecutionStep)
            .where(ExecutionStep.execution_id == exec_id)
            .order_by(ExecutionStep.sequence_number.asc())
        ).all()
        assert len(steps) == 2
        assert steps[0].node_id == "node_trigger"
        assert steps[0].error_details == {"note": "Triggered manually"}
        assert steps[0].step_metadata == {"note": "Triggered manually"}
        assert steps[1].node_id == "node_salesforce"
        assert steps[1].error_details == {"note": "Upserted 1 record via Bulk API"}
        assert steps[1].step_metadata == {"note": "Upserted 1 record via Bulk API"}

    # Verify /steps endpoint exposes metadata
    res = client.get(f"/api/executions/{exec_id}/steps", headers=headers)
    assert res.status_code == 200
    steps_data = res.json()["data"]
    assert len(steps_data) == 2
    assert steps_data[0]["metadata"] == {"note": "Triggered manually"}
    assert steps_data[1]["metadata"] == {"note": "Upserted 1 record via Bulk API"}


def test_extract_execution_flow_metadata_and_backfill():
    """Test extract_execution_flow_metadata and backfill_execution_telemetry_metadata."""
    from app.services.telemetry_service import (
        extract_execution_flow_metadata,
        backfill_execution_telemetry_metadata,
    )

    # 1. Test Ingestion workflow with data_load and Salesforce Bulk
    wf_data = {
        "nodes": [
            {"id": "sched_1", "type": "schedule", "parameters": {}},
            {
                "id": "dl_1",
                "type": "flowsmith.data_load",
                "parameters": {"file_format": "tsv", "target_object": "Contact"},
            },
            {"id": "code_1", "type": "code", "parameters": {}},
            {
                "id": "sf_1",
                "type": "salesforce",
                "parameters": {
                    "operation": "bulk",
                    "bulk_operation": "insert",
                    "object_name": "Contact",
                    "resource": "Contact",
                },
            },
        ]
    }

    # Success case
    meta_success = extract_execution_flow_metadata(
        wf_data,
        trigger="manual",
        status="success",
        workflow_name="Ingest TSV Contacts (10,000) to Salesforce",
    )
    assert meta_success["source_connector"] == "data_load"
    assert meta_success["destination_connector"] == "salesforce"
    assert meta_success["source_object"] == "Contact"
    assert meta_success["destination_object"] == "Contact"
    assert meta_success["http_method"] == "POST"
    assert meta_success["http_status_code"] == 201

    # Failed case
    meta_failed = extract_execution_flow_metadata(
        wf_data,
        trigger="manual",
        status="failed",
        error={"code": "INVALID_WORKFLOW", "message": "Credential not found"},
        workflow_name="Ingest TSV Contacts (10,000) to Salesforce",
    )
    assert meta_failed["source_connector"] == "data_load"
    assert meta_failed["destination_connector"] == "salesforce"
    assert meta_failed["source_object"] == "Contact"
    assert meta_failed["destination_object"] == "Contact"
    assert meta_failed["http_method"] == "POST"
    assert meta_failed["http_status_code"] == 400

    # 2. Test Webhook -> Slack workflow
    wf_slack = {
        "nodes": [
            {"id": "wh_1", "type": "webhook", "parameters": {"topic": "orders"}},
            {"id": "filter_1", "type": "filter", "parameters": {}},
            {"id": "slack_1", "type": "slack", "parameters": {"channel": "#alerts"}},
        ]
    }
    meta_slack = extract_execution_flow_metadata(
        wf_slack,
        trigger="webhook",
        status="success",
    )
    assert meta_slack["source_connector"] == "webhook"
    assert meta_slack["destination_connector"] == "slack"
    assert meta_slack["source_object"] == "orders"
    assert meta_slack["destination_object"] == "#alerts"
    assert meta_slack["http_method"] == "POST"
    assert meta_slack["http_status_code"] == 200

    # 3. Test backfill function returns integer
    count = backfill_execution_telemetry_metadata()
    assert isinstance(count, int)


def test_execution_search_indexing_and_snippets():
    """Verify build_execution_search_text and extract_search_matches."""
    from app.services.telemetry_service import (
        build_execution_search_text,
        extract_execution_search_matches as extract_search_matches,
    )
    from unittest.mock import MagicMock

    mock_rec = MagicMock()
    mock_rec.id = "exec_test_search_123"
    mock_rec.workflow_id = "wf_contacts_ingest"
    mock_rec.status = "success"
    mock_rec.source_connector = "data_load"
    mock_rec.destination_connector = "salesforce"
    mock_rec.source_object = "Contact"
    mock_rec.destination_object = "Contact"
    mock_rec.http_method = "POST"
    mock_rec.http_status_code = 201
    mock_rec.api_endpoint = "/services/data/v59.0/jobs/ingest"
    mock_rec.error_summary = None
    mock_rec.error_code = None
    mock_rec.error_type = None
    mock_rec.error = None
    mock_rec.trigger_data = {"filename": "contacts_batch.tsv"}
    mock_rec.results = None
    mock_rec.trace = [
        {
            "node_id": "sf_bulk_1",
            "node_title": "Salesforce Bulk Ingest",
            "node_type": "salesforce",
            "inputs": {"object_name": "Contact", "operation": "insert"},
            "outputs": {"job_id": "750XXXXXXXXXXXX", "records_processed": 10000},
        }
    ]

    # Test search text building
    search_idx = build_execution_search_text(
        mock_rec,
        workflow_name="Ingest TSV Contacts (10,000) to Salesforce",
        user_email="admin@flowsmith.local",
    )
    assert "salesforce" in search_idx
    assert "750XXXXXXXXXXXX" in search_idx
    assert "10000" in search_idx

    # Test search snippet extraction for 'contacts_batch'
    matches = extract_search_matches(mock_rec, "contacts_batch")
    assert len(matches) > 0
    assert any("contacts_batch" in m["snippet"] for m in matches)

    # Test search snippet extraction for 'Contact'
    matches_obj = extract_search_matches(mock_rec, "Contact")
    assert len(matches_obj) > 0
    assert any(m["type"] in ("object", "input", "node") for m in matches_obj)


def test_universal_execution_search_endpoint(client):
    """Test the full YouTube-like Universal Search endpoint across executions."""
    headers, user = _setup_user(client)
    wf_id = f"wf_univ_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json=make_workflow(wf_id, "Customer Sync Engine"), headers=headers)

    exec_id = f"exec_univ_{uuid.uuid4().hex[:8]}"

    with session_scope() as session:
        exec_row = _create_execution(
            session,
            id=exec_id,
            workflow_id=wf_id,
            user_id=user["id"],
            status="failed",
            source_connector="hubspot",
            destination_connector="salesforce",
            source_object="Contact",
            destination_object="Lead",
            http_method="POST",
            http_status_code=502,
            api_endpoint="/services/data/v59.0/sobjects/Lead",
            error_summary="Bad Gateway: Downstream Salesforce API gateway timed out",
            error_code="GATEWAY_TIMEOUT_502",
            error_type="DOWNSTREAM_5XX",
            trigger_data={"batch_name": "quarter_one_leads", "total_records": 100},
            trace=[
                {
                    "node_id": "step_extract_1",
                    "node_title": "Extract Contacts",
                    "node_type": "hubspot_query",
                    "inputs": {"filter_field": "email", "filter_val": "customer_one@domain.com"},
                    "outputs": {"count": 1, "lead": {"first_name": "Alice", "nested_key": "special_token_val_42"}},
                    "status": "success",
                    "duration_ms": 120.0,
                },
                {
                    "node_id": "step_load_sf",
                    "node_title": "Load to Salesforce",
                    "node_type": "salesforce_upsert",
                    "inputs": {"lead_email": "customer_one@domain.com", "tier": "enterprise"},
                    "error": "HTTP 502: Server unreachable",
                    "status": "error",
                    "duration_ms": 2500.0,
                },
            ],
        )

        # Add ExecutionStep rows
        now_step = datetime.now(timezone.utc)
        session.add(ExecutionStep(
            id=f"step_{uuid.uuid4().hex[:8]}",
            execution_id=exec_id,
            node_id="step_extract_1",
            step_name="Extract Contacts",
            node_type="hubspot_query",
            inputs={"filter_field": "email", "filter_val": "customer_one@domain.com"},
            outputs={"count": 1, "lead": {"first_name": "Alice", "nested_key": "special_token_val_42"}},
            status="success",
            started_at=now_step,
            completed_at=now_step,
            duration_ms=120.0,
        ))

        # Add ApiRequestTelemetry row
        session.add(ApiRequestTelemetry(
            id=f"req_{uuid.uuid4().hex[:8]}",
            execution_id=exec_id,
            node_id="step_load_sf",
            connector_name="salesforce",
            http_method="POST",
            endpoint_url="https://api.salesforce.com/services/data/v59.0/sobjects/Lead",
            http_status_code=502,
            duration_ms=2500.0,
            request_payload={"lead_email": "customer_one@domain.com", "tier": "enterprise"},
            response_payload={"error": "Bad Gateway", "code": 502},
        ))

    # 1. Search for single word "one" (case-insensitive)
    resp = client.get("/api/executions/universal-search?q=one", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    meta = resp.json()["meta"]
    assert meta["total"] > 0
    assert meta["facets"]["all"] > 0
    # Check that occurrence points to this execution and has target deep-link
    occ = next(o for o in data if o["execution_id"] == exec_id)
    assert occ["workflow_name"] == "Customer Sync Engine"
    assert "/executions/" in occ["url"]

    # 2. Search for deeply nested JSON string "special_token_val_42"
    resp2 = client.get("/api/executions/universal-search?q=special_token_val_42", headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    assert any(o["execution_id"] == exec_id and "special_token_val_42" in o["snippet"] for o in data2)

    # 3. Search for error keyword "gateway"
    resp3 = client.get("/api/executions/universal-search?q=gateway", headers=headers)
    assert resp3.status_code == 200
    data3 = resp3.json()["data"]
    assert any(o["category"] == "errors" or "Gateway" in o["snippet"] for o in data3)

    # 4. Search with category filter: category="api_requests"
    resp4 = client.get("/api/executions/universal-search?q=salesforce&category=api_requests", headers=headers)
    assert resp4.status_code == 200
    data4 = resp4.json()["data"]
    for o in data4:
        assert o["category"] == "api_requests"

    # 5. Verify standard execution list also returns search_matches
    resp5 = client.get("/api/executions?search=special_token_val_42", headers=headers)
    assert resp5.status_code == 200
    exec_list = resp5.json()["data"]
    assert len(exec_list) >= 1
    target = next(e for e in exec_list if e["id"] == exec_id)
    assert len(target["search_matches"]) > 0
    assert any("special_token_val_42" in m["snippet"] for m in target["search_matches"])

    # 6. Verify strict isolation: Another user cannot see these results
    other_headers, _ = _setup_user(client, email="other_auditor@test.com")
    resp_other = client.get("/api/executions/universal-search?q=special_token_val_42", headers=other_headers)
    assert resp_other.status_code == 200
    assert resp_other.json()["meta"]["total"] == 0
    assert len(resp_other.json()["data"]) == 0


