"""Unit and integration tests for enterprise completions:
- Phase 10: MCP list_connectors tool
- Phase 13: Webhook signature verification
- Phase 15: Workflow environment promotion
"""

from __future__ import annotations

import hashlib
import hmac
import time
from fastapi.testclient import TestClient

from tests.test_api.conftest import auth_headers, register


def _setup(client: TestClient) -> dict[str, str]:
    return auth_headers(register(client)["token"])


def test_mcp_list_connectors_tool(client: TestClient):
    headers = _setup(client)
    resp = client.post(
        "/api/mcp/call",
        json={"name": "list_connectors", "arguments": {}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert isinstance(data, list)
    assert len(data) >= 30
    keys = {c["connector_key"] for c in data}
    assert "salesforce" in keys
    assert "slack" in keys
    assert "postgres" in keys


def test_workflow_environment_promotion(client: TestClient):
    headers = _setup(client)
    wf = {
        "id": "wf_promo_test",
        "name": "Promote Test",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "s", "type": "set_data", "parameters": {"fields": {"env": "test"}}},
        ],
        "connections": [{"source": "t", "target": "s"}],
        "settings": {"environment": "development"},
    }
    create_resp = client.post("/api/workflows", json=wf, headers=headers)
    assert create_resp.status_code == 201

    promote_resp = client.post(
        "/api/workflows/wf_promo_test/promote",
        json={"target_environment": "production", "notes": "Approved for prod release"},
        headers=headers,
    )
    assert promote_resp.status_code == 200, promote_resp.text
    pdata = promote_resp.json()["data"]
    assert pdata["workflow_id"] == "wf_promo_test"
    assert pdata["source_environment"] == "development"
    assert pdata["target_environment"] == "production"
    assert pdata["version"] == 2

    # Verify updated workflow settings
    detail_resp = client.get("/api/workflows/wf_promo_test", headers=headers)
    assert detail_resp.status_code == 200
    wf_settings = detail_resp.json()["data"]["settings"]
    assert wf_settings["environment"] == "production"
    assert wf_settings["promotion_notes"] == "Approved for prod release"


def test_webhook_hmac_signature_verification(client: TestClient):
    headers = _setup(client)
    secret_key = "super_secret_webhook_token_123"
    webhook_path = "hook-enterprise-secure-9999"

    wf = {
        "id": "wf_secure_hook",
        "name": "Secure Webhook Workflow",
        "nodes": [
            {
                "id": "wh1",
                "type": "webhook",
                "parameters": {
                    "path": webhook_path,
                    "method": "POST",
                    "secret": secret_key,
                },
            }
        ],
        "connections": [],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    act_resp = client.patch("/api/workflows/wf_secure_hook/active", json={"active": True}, headers=headers)
    assert act_resp.status_code == 200, act_resp.text

    payload = b'{"event":"test.alert","status":"active"}'

    # 1. Unauthenticated hit without signature -> should be rejected (401)
    resp_unauth = client.post(f"/api/webhooks/{webhook_path}", content=payload)
    assert resp_unauth.status_code == 401

    # 2. Invalid signature -> should be rejected (401)
    resp_bad = client.post(
        f"/api/webhooks/{webhook_path}",
        content=payload,
        headers={"x-hub-signature-256": "sha256=invalidhexsignature000000000000000000000000000000000000"},
    )
    assert resp_bad.status_code == 401

    # 3. Valid HMAC-SHA256 signature -> accepted (202)
    valid_sig = hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    resp_good = client.post(
        f"/api/webhooks/{webhook_path}",
        content=payload,
        headers={"x-hub-signature-256": f"sha256={valid_sig}"},
    )
    assert resp_good.status_code == 202
    assert resp_good.json()["data"]["delivery_id"]


def test_multi_level_error_workflow(client: TestClient):
    """Phase 14: multi-level error handler fallback (workflow -> workspace error_trigger)."""
    headers = _setup(client)
    from app.db import SessionLocal
    from app.models import WorkflowRecord
    from app.execution_runtime import _maybe_run_error_workflow
    from app.queue import QueueJob

    # 1. Create error handler workflow with error_trigger
    err_wf = {
        "id": "wf_error_handler_test",
        "name": "Global Error Handler",
        "nodes": [
            {"id": "et", "type": "error_trigger", "parameters": {}},
            {"id": "sd", "type": "set_data", "parameters": {"fields": {"caught": True}}},
        ],
        "connections": [{"source": "et", "target": "sd"}],
        "settings": {},
    }
    client.post("/api/workflows", json=err_wf, headers=headers)
    client.patch("/api/workflows/wf_error_handler_test/active", json={"active": True}, headers=headers)

    # 2. Create workspace-associated workflow that specifies on_error_workflow_id
    failing_wf = {
        "id": "wf_failing_main",
        "name": "Failing Workflow",
        "nodes": [
            {"id": "m", "type": "manual_trigger", "parameters": {}},
        ],
        "connections": [],
        "settings": {"on_error_workflow_id": "wf_error_handler_test"},
    }
    client.post("/api/workflows", json=failing_wf, headers=headers)

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, "wf_failing_main")
        job = QueueJob(
            id="job_dummy_123",
            execution_id="exec_dummy_fail_123",
            payload={
                "workflow_id": "wf_failing_main",
                "version": 1,
                "trigger": "manual",
                "workflow_data": rec.data,
                "user_id": rec.user_id,
                "trigger_items": [{}],
            },
        )
        # Should invoke start_execution for wf_error_handler_test without throwing
        _maybe_run_error_workflow(
            db, job, "exec_dummy_fail_123", {"code": "NODE_FAILED", "message": "Simulated failure"}
        )

        from app.models import Execution as ExecutionModel
        from sqlalchemy import select
        err_exec = db.scalars(
            select(ExecutionModel).where(
                ExecutionModel.workflow_id == "wf_error_handler_test",
                ExecutionModel.trigger == "error_handler",
            )
        ).first()
        assert err_exec is not None
        assert err_exec.trigger_data[0]["error"]["code"] == "NODE_FAILED"
        assert err_exec.trigger_data[0]["failed_execution_id"] == "exec_dummy_fail_123"
        assert err_exec.trigger_data[0]["failed_workflow_id"] == "wf_failing_main"
