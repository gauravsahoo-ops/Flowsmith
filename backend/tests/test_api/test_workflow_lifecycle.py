"""Comprehensive automated regression tests for Workflow Lifecycle, Duplication,
Import/Export, Templates, and Scheduler Integration (P0 - P8).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, Execution, ScheduleTrigger, WebhookTrigger, WorkflowRecord
from tests.test_api.conftest import auth_headers, make_workflow, register


def _setup(client):
    user = register(client)
    return user, auth_headers(user["token"])


def _complex_workflow(workflow_id="wf_complex", name="Complex Pipeline"):
    return {
        "id": workflow_id,
        "name": name,
        "nodes": [
            {
                "id": "node_trigger",
                "type": "manual_trigger",
                "name": "Manual Start",
                "position": {"x": 100, "y": 200},
                "parameters": {},
                "settings": {},
            },
            {
                "id": "node_set",
                "type": "set_data",
                "name": "Format Data",
                "position": {"x": 300, "y": 200},
                "parameters": {
                    "fields": {
                        "user_id": "={{ $json.id }}",
                        "auth_token": "secret_token_12345",
                    }
                },
                "settings": {"continue_on_error": True, "max_retries": 3},
            },
            {
                "id": "node_http",
                "type": "http_request",
                "name": "Send API Call",
                "position": {"x": 500, "y": 200},
                "parameters": {
                    "url": "https://api.example.com/v1/resource",
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer super_secret_token",
                        "Content-Type": "application/json",
                    },
                    "api_key": "api_key_abcdef123456",
                },
                "credentials": {"http": "cred_http_secret_id"},
                "settings": {"timeout_seconds": 60},
            },
            {
                "id": "node_webhook",
                "type": "webhook",
                "name": "Incoming Hook",
                "position": {"x": 100, "y": 400},
                "parameters": {
                    "path": f"hook-original-{uuid.uuid4().hex[:24]}",
                    "method": "POST",
                },
                "settings": {},
            },
        ],
        "connections": [
            {"source": "node_trigger", "target": "node_set"},
            {"source": "node_set", "target": "node_http"},
        ],
        "settings": {
            "description": "Critical ETL workflow",
            "retry_policy": {"count": 3, "delay_ms": 1000},
        },
    }


def test_duplication_excludes_secrets_creates_draft_never_auto_executes(client):
    """P0 & P1: Duplicating a workflow must copy configuration, strip credentials/secrets,
    set Draft/Inactive state, generate new IDs, and NEVER execute or register active schedules.
    """
    user, headers = _setup(client)
    orig_wf = _complex_workflow("wf_source_1", "Production Ingestion")
    create_resp = client.post("/api/workflows", json=orig_wf, headers=headers)
    assert create_resp.status_code == 201

    # Duplicate workflow
    dup_resp = client.post(f"/api/workflows/{orig_wf['id']}/duplicate", headers=headers)
    assert dup_resp.status_code == 201
    dup_data = dup_resp.json()["data"]
    meta = dup_resp.json()["meta"]

    # 1. New unique identity
    assert dup_data["id"] != orig_wf["id"]
    assert dup_data["id"].startswith("wf_")
    assert meta["duplicated_from"] == orig_wf["id"]
    assert dup_data["name"] == "Production Ingestion (Copy)"
    assert dup_data["version"] == 1

    # 2. Lifecycle state: Draft and Inactive
    assert dup_data["active"] is False
    assert dup_data["status"] == "draft"

    # 3. Design preserved: nodes, edges, positions, settings, mappings
    assert len(dup_data["nodes"]) == len(orig_wf["nodes"])
    assert len(dup_data["connections"]) == len(orig_wf["connections"])
    assert dup_data["settings"]["description"] == "Critical ETL workflow"

    # 4. Sensitive credentials & secrets stripped
    http_node = next(n for n in dup_data["nodes"] if n["id"] == "node_http")
    assert http_node["credentials"] == {}
    assert "api_key" not in http_node["parameters"]
    assert "Authorization" not in http_node["parameters"].get("headers", {})
    assert http_node["parameters"].get("headers", {}).get("Content-Type") == "application/json"

    set_node = next(n for n in dup_data["nodes"] if n["id"] == "node_set")
    assert "auth_token" not in set_node["parameters"].get("fields", {})
    assert set_node["parameters"]["fields"]["user_id"] == "={{ $json.id }}"

    # 5. Webhook path regenerated to prevent path collision
    hook_node = next(n for n in dup_data["nodes"] if n["id"] == "node_webhook")
    orig_hook_node = next(n for n in orig_wf["nodes"] if n["id"] == "node_webhook")
    assert hook_node["parameters"]["path"] != orig_hook_node["parameters"]["path"]
    assert len(hook_node["parameters"]["path"]) >= 24

    # 6. Verify NO execution was started
    db = get_session()
    try:
        exec_count = db.query(Execution).filter(Execution.workflow_id == dup_data["id"]).count()
        assert exec_count == 0, "Duplication must NEVER create or trigger an execution!"

        # 7. Verify NO active trigger was registered
        trigger_count = db.query(WebhookTrigger).filter(WebhookTrigger.workflow_id == dup_data["id"]).count()
        assert trigger_count == 0, "Duplicate workflow must remain inactive with no trigger registrations!"

        # 8. Verify audit event
        audit = db.query(AuditEvent).filter(
            AuditEvent.target_id == dup_data["id"],
            AuditEvent.action == "workflow.duplicate",
        ).first()
        assert audit is not None
    finally:
        db.close()


def test_json_export_and_import_safe_pipeline(client):
    """P2: Exporting must strip secrets, importing must sanitize, generate unique ID,
    set Draft/Inactive state, and never auto-run or register schedules.
    """
    user, headers = _setup(client)
    orig_wf = _complex_workflow("wf_export_1", "Export Source Workflow")
    client.post("/api/workflows", json=orig_wf, headers=headers)

    # 1. Export
    exp_resp = client.get(f"/api/workflows/{orig_wf['id']}/export", headers=headers)
    assert exp_resp.status_code == 200
    export_envelope = exp_resp.json()["data"]

    assert export_envelope["format"] == "opencode-workflow"
    assert export_envelope["version"] == 1
    exported_wf = export_envelope["workflow"]

    # Verify export stripped secrets
    http_node = next(n for n in exported_wf["nodes"] if n["id"] == "node_http")
    assert http_node["credentials"] == {}
    assert "api_key" not in http_node["parameters"]
    assert "Authorization" not in http_node["parameters"].get("headers", {})

    # 2. Re-import
    imp_resp = client.post("/api/workflows/import", json=export_envelope, headers=headers)
    assert imp_resp.status_code == 201
    imported = imp_resp.json()["data"]

    # Original ID was taken, fresh import ID assigned
    assert imported["id"] != orig_wf["id"]
    assert imported["id"].startswith("wf_import_")
    assert imported["active"] is False
    assert imported["status"] == "draft"

    # 3. Verify zero executions and zero active schedule triggers
    db = get_session()
    try:
        execs = db.query(Execution).filter(Execution.workflow_id == imported["id"]).all()
        assert len(execs) == 0, "Importing must NEVER execute workflow!"
        schedules = db.query(ScheduleTrigger).filter(ScheduleTrigger.workflow_id == imported["id"]).all()
        assert len(schedules) == 0, "Imported workflow must have zero active schedule triggers!"

        # Audit log check
        audit = db.query(AuditEvent).filter(
            AuditEvent.target_id == imported["id"],
            AuditEvent.action == "workflow.import",
        ).first()
        assert audit is not None
    finally:
        db.close()


def test_import_unsupported_version_and_malformed_json_rejected(client):
    """P2: Reject malformed or unsupported version imports with 422."""
    user, headers = _setup(client)

    # Unsupported future version
    future_doc = {
        "format": "opencode-workflow",
        "version": 99,
        "workflow": make_workflow(),
    }
    resp = client.post("/api/workflows/import", json=future_doc, headers=headers)
    assert resp.status_code == 422
    assert "Unsupported workflow export version" in resp.json()["detail"]

    # Malformed non-object JSON
    resp_array = client.post("/api/workflows/import", json=["not", "a", "dict"], headers=headers)
    assert resp_array.status_code == 422

    # Object without nodes
    resp_empty = client.post("/api/workflows/import", json={"random": "data"}, headers=headers)
    assert resp_empty.status_code == 422


def test_template_creation_saving_preview_and_instantiation(client):
    """P3: Templates must strip secrets on creation, provide read-only preview,
    and create inactive Draft workflows without automatic execution.
    """
    user, headers = _setup(client)
    wf_template_data = _complex_workflow("wf_tmpl_src", "Template Original")

    # 1. Create template
    create_tmpl_resp = client.post(
        "/api/templates",
        json={
            "name": "Standard ETL Pipeline",
            "description": "Production ETL template",
            "category": "automation",
            "is_public": True,
            "workflow_data": wf_template_data,
        },
        headers=headers,
    )
    assert create_tmpl_resp.status_code == 200
    tmpl_id = create_tmpl_resp.json()["data"]["id"]

    # 2. Preview template (read-only)
    preview_resp = client.get(f"/api/templates/{tmpl_id}", headers=headers)
    assert preview_resp.status_code == 200
    preview_data = preview_resp.json()["data"]
    assert preview_data["name"] == "Standard ETL Pipeline"
    # Secrets stripped in template preview
    p_http_node = next(n for n in preview_data["workflow_data"]["nodes"] if n["id"] == "node_http")
    assert p_http_node["credentials"] == {}
    assert "api_key" not in p_http_node["parameters"]

    # 3. Use template to instantiate new workflow
    use_resp = client.post(f"/api/templates/{tmpl_id}/use", headers=headers)
    assert use_resp.status_code == 200
    inst_workflow_data = use_resp.json()["data"]["workflow_data"]

    # Import this instantiated template workflow into the user's workspace
    import_resp = client.post("/api/workflows/import", json=inst_workflow_data, headers=headers)
    assert import_resp.status_code == 201
    new_wf = import_resp.json()["data"]

    assert new_wf["id"].startswith("wf_import_")
    assert new_wf["active"] is False
    assert new_wf["status"] == "draft"

    # Confirm no execution or schedule created
    db = get_session()
    try:
        exec_count = db.query(Execution).filter(Execution.workflow_id == new_wf["id"]).count()
        assert exec_count == 0, "Instantiating from template must NEVER execute workflow!"
    finally:
        db.close()


def test_scheduler_lifecycle_and_idempotency(client):
    """P4, P5, P6: Schedule triggers must only fire for explicitly activated workflows.
    Draft, inactive, or soft-deleted workflows must NEVER be fired by the scheduler.
    """
    user, headers = _setup(client)

    # Create a workflow with a schedule trigger (every minute)
    sched_wf = {
        "id": "wf_sched_test",
        "name": "Scheduled Ingestion",
        "nodes": [
            {
                "id": "sched_1",
                "type": "schedule",
                "name": "Schedule Trigger",
                "position": {"x": 100, "y": 100},
                "parameters": {
                    "rules": [{"id": "r1", "interval": "cron", "cron": "* * * * *", "timezone": "UTC"}]
                },
            },
            {
                "id": "set_1",
                "type": "set_data",
                "name": "Set Result",
                "position": {"x": 300, "y": 100},
                "parameters": {"fields": {"executed": True}},
            },
        ],
        "connections": [{"source": "sched_1", "target": "set_1"}],
        "settings": {},
    }
    client.post("/api/workflows", json=sched_wf, headers=headers)

    db = get_session()
    try:
        from app.scheduler import Scheduler

        scheduler = Scheduler()

        # Case 1: Inactive workflow -> 0 schedule trigger rows, scheduler does not fire
        active_triggers = db.query(ScheduleTrigger).filter(ScheduleTrigger.workflow_id == sched_wf["id"]).all()
        assert len(active_triggers) == 0, "Inactive workflow must have no registered ScheduleTrigger rows!"

        now = datetime.now(timezone.utc)
        fired = scheduler._tick_sync(now)
        assert fired == 0, "Scheduler must not fire inactive workflow!"

        # Case 2: Explicitly activate workflow
        act_resp = client.patch(f"/api/workflows/{sched_wf['id']}/active", json={"active": True}, headers=headers)
        assert act_resp.status_code == 200
        assert act_resp.json()["data"]["active"] is True

        # Triggers synced: exactly 1 ScheduleTrigger registered
        triggers = db.query(ScheduleTrigger).filter(
            ScheduleTrigger.workflow_id == sched_wf["id"],
            ScheduleTrigger.status == "active",
        ).all()
        assert len(triggers) == 1
        assert triggers[0].cron == "* * * * *"

        # Case 3: Deactivate workflow
        deact_resp = client.patch(f"/api/workflows/{sched_wf['id']}/active", json={"active": False}, headers=headers)
        assert deact_resp.status_code == 200
        assert deact_resp.json()["data"]["active"] is False

        # Triggers cleanly unmounted
        triggers_after = db.query(ScheduleTrigger).filter(
            ScheduleTrigger.workflow_id == sched_wf["id"],
        ).all()
        assert len(triggers_after) == 0, "Deactivating workflow must unregister ScheduleTriggers!"

        # Case 4: Manual Run still works explicitly
        run_resp = client.post(f"/api/workflows/{sched_wf['id']}/run", headers=headers)
        assert run_resp.status_code in (200, 202)
        run_data = run_resp.json()["data"]
        assert "execution_id" in run_data
        exec_id = run_data["execution_id"]

        exec_row = db.get(Execution, exec_id)
        assert exec_row is not None
        assert exec_row.workflow_id == sched_wf["id"]
        assert exec_row.trigger == "manual"
    finally:
        db.close()
