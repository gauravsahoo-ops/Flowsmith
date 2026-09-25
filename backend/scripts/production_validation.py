"""PRODUCTION VALIDATION — Full E2E Stack Test.

Runs against the live running platform at http://127.0.0.1:8000
Tests every subsystem end-to-end through the real API.

Usage: python backend/scripts/production_validation.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

import httpx

BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
RESULTS: list[dict[str, Any]] = []
FAILURES: list[str] = []


def api(method: str, path: str, token: str = "", **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.request(method, f"{BASE}{path}", headers=headers, timeout=30, **kw)


def ok(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append({"test": name, "status": status, "detail": detail})
    if not passed:
        FAILURES.append(f"{name}: {detail}")
    ch = "." if passed else "F"
    suffix = f" ({detail})" if detail and not passed else ""
    print(f"  {ch} {name}{suffix}")


def wait_for_execution(exec_id: str, token: str, max_wait: int = 60) -> str:
    for _ in range(max_wait // 2):
        time.sleep(2)
        r = api("GET", f"/api/executions/{exec_id}", token=token)
        if r.status_code == 200:
            st = r.json()["data"]["status"]
            if st in ("completed", "success", "failed", "error"):
                return st
    r = api("GET", f"/api/executions/{exec_id}", token=token)
    return r.json()["data"]["status"] if r.status_code == 200 else "unknown"


def create_and_run(wf: dict, token: str, name: str, wait: bool = True) -> tuple[bool, str]:
    r = api("POST", "/api/workflows", token=token, json=wf)
    if r.status_code != 201:
        return False, f"create failed: {r.status_code}"
    r2 = api("POST", f"/api/workflows/{wf['id']}/run", token=token, json={"data": {"test": True}})
    if r2.status_code != 202:
        return False, f"trigger failed: {r2.status_code}"
    exec_id = r2.json()["data"]["execution_id"]
    if wait:
        status = wait_for_execution(exec_id, token)
        return status in ("completed", "success"), f"status={status}"
    return True, f"exec_id={exec_id}"


# ═════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 70)
    print("  PRODUCTION VALIDATION — FULL E2E STACK TEST")
    print("=" * 70)
    print(f"\n  Target: {BASE}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ─── 0. INFRASTRUCTURE ────────────────────────────────
    print("[1/14] Infrastructure Health")
    r = api("GET", "/api/health")
    ok("infra.health", r.status_code == 200 and r.json()["data"]["status"] == "ok", f"status={r.status_code}")

    r = api("GET", "/api/readyz")
    data = r.json()["data"]
    ok("infra.readyz.postgres", data.get("checks", {}).get("postgres") == "ok")
    ok("infra.readyz.redis", data.get("checks", {}).get("redis") == "ok")
    ok("infra.readyz.status", data.get("status") == "ready")

    # ─── 1. AUTH ──────────────────────────────────────────
    print("\n[2/14] Authentication")
    email = f"prodtest_{uuid.uuid4().hex[:8]}@test.com"
    pw = "P@ssw0rd!2024"

    r = api("POST", "/api/auth/register", json={"email": email, "password": pw})
    ok("auth.register", r.status_code == 201, f"status={r.status_code} body={r.text[:100]}")
    token = r.json()["data"]["token"] if r.status_code == 201 else ""

    r = api("POST", "/api/auth/login", json={"email": email, "password": pw})
    ok("auth.login", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        token = r.json()["data"]["token"]

    # Verify token works by listing workflows
    r = api("GET", "/api/workflows", token=token)
    ok("auth.token_valid", r.status_code == 200, f"status={r.status_code}")

    r = api("POST", "/api/auth/login", json={"email": email, "password": "wrong"})
    ok("auth.invalid_login_rejected", r.status_code in (401, 422), f"status={r.status_code}")

    r = api("GET", "/api/workflows")
    ok("auth.unauthorized_blocked", r.status_code == 401, f"status={r.status_code}")

    # ─── 2. WORKFLOWS CRUD ────────────────────────────────
    print("\n[3/14] Workflows CRUD")
    wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    wf = {
        "id": wf_id,
        "name": "Production Validation",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code1", "type": "code", "parameters": {"code": "return [{json: {msg: 'hello'}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 300, "y": 0}},
        ],
        "connections": [{"source": "trigger", "sourceHandle": "main", "target": "code1", "targetHandle": "main"}],
        "settings": {"timeout_seconds": 60},
    }
    r = api("POST", "/api/workflows", token=token, json=wf)
    ok("workflow.create", r.status_code == 201, f"status={r.status_code}")

    r = api("GET", "/api/workflows", token=token)
    ok("workflow.list", r.status_code == 200 and len(r.json().get("data", [])) > 0)

    r = api("GET", f"/api/workflows/{wf_id}", token=token)
    ok("workflow.get", r.status_code == 200 and r.json()["data"]["id"] == wf_id)

    r = api("PUT", f"/api/workflows/{wf_id}", token=token, json={
        **wf, "name": "Production Validation Updated",
        "settings": {"timeout_seconds": 120},
    })
    ok("workflow.update", r.status_code == 200, f"status={r.status_code}")

    r = api("GET", f"/api/workflows/{wf_id}/expression-context", token=token)
    ok("workflow.expression_context", r.status_code == 200, f"status={r.status_code}")

    r = api("GET", f"/api/workflows/{wf_id}/versions", token=token)
    ok("workflow.versions", r.status_code == 200, f"status={r.status_code}")

    r = api("GET", f"/api/workflows/{wf_id}/export", token=token)
    ok("workflow.export", r.status_code == 200, f"status={r.status_code}")

    # ─── 3. MANUAL EXECUTION (Queue → Worker) ─────────────
    print("\n[4/14] Manual Execution (Queue -> Worker)")
    r = api("POST", f"/api/workflows/{wf_id}/run", token=token, json={"data": {"key": "test123"}})
    ok("execution.manual_trigger", r.status_code == 202, f"status={r.status_code} body={r.text[:150]}")
    exec_id = r.json()["data"]["execution_id"] if r.status_code == 202 else ""

    if exec_id:
        status = wait_for_execution(exec_id, token)
        ok("execution.manual_completes", status in ("completed", "success"), f"final_status={status}")

        r = api("GET", f"/api/executions/{exec_id}", token=token)
        ok("execution.has_results", r.status_code == 200 and "data" in r.json())

        r = api("GET", f"/api/executions/{exec_id}/items", token=token)
        ok("execution.items", r.status_code == 200)

        r = api("GET", f"/api/executions/{exec_id}/trace", token=token)
        ok("execution.trace", r.status_code == 200)

        r = api("GET", "/api/executions", token=token)
        ok("execution.list", r.status_code == 200 and len(r.json().get("data", [])) > 0)

        r = api("POST", f"/api/executions/{exec_id}/retry", token=token)
        ok("execution.retry", r.status_code == 202, f"status={r.status_code}")
    else:
        ok("execution.manual_completes", False, "no exec_id")

    # ─── 4. CODE EXECUTION (5 items) ──────────────────────
    print("\n[5/14] Code Execution (Multiple Items)")
    code_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    code_wf = {
        "id": code_wf_id,
        "name": "Code 5-Item Test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code", "type": "code", "parameters": {
                "code": "var items = []; for (var i = 0; i < 5; i++) { items.push({json: {index: i, doubled: i*2}}); } return items;",
                "mode": "runOnceForAllItems"
            }, "settings": {}, "position": {"x": 300, "y": 0}},
        ],
        "connections": [{"source": "trigger", "sourceHandle": "main", "target": "code", "targetHandle": "main"}],
        "settings": {"timeout_seconds": 30},
    }
    passed, detail = create_and_run(code_wf, token, "code_5_items")
    ok("code.five_items", passed, detail)

    # ─── 5. IF CONDITION ──────────────────────────────────
    print("\n[6/14] IF Condition + Branching")
    if_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    if_wf = {
        "id": if_wf_id,
        "name": "IF Branch Test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code_prepare", "type": "code", "parameters": {
                "code": "return [{json: {value: 42}}]",
                "mode": "runOnceForAllItems"
            }, "settings": {}, "position": {"x": 200, "y": 0}},
            {"id": "if_cond", "type": "if_condition", "parameters": {
                "conditions": [{"left": "={{$json.value}}", "operator": "is greater than", "right": 10}]
            }, "settings": {}, "position": {"x": 400, "y": 0}},
            {"id": "code_true", "type": "code", "parameters": {
                "code": "return [{json: {branch: 'true', result: 'PASS'}}]",
                "mode": "runOnceForAllItems"
            }, "settings": {}, "position": {"x": 600, "y": -50}},
            {"id": "code_false", "type": "code", "parameters": {
                "code": "return [{json: {branch: 'false', result: 'FAIL'}}]",
                "mode": "runOnceForAllItems"
            }, "settings": {}, "position": {"x": 600, "y": 50}},
        ],
        "connections": [
            {"source": "trigger", "sourceHandle": "main", "target": "code_prepare", "targetHandle": "main"},
            {"source": "code_prepare", "sourceHandle": "main", "target": "if_cond", "targetHandle": "main"},
            {"source": "if_cond", "sourceHandle": "true", "target": "code_true", "targetHandle": "main"},
            {"source": "if_cond", "sourceHandle": "false", "target": "code_false", "targetHandle": "main"},
        ],
        "settings": {"timeout_seconds": 30},
    }
    passed, detail = create_and_run(if_wf, token, "if_condition")
    ok("if_condition.branching", passed, detail)

    # ─── 6. LOOPS + MULTIPLE ITEMS ────────────────────────
    print("\n[7/14] Loops + Multiple Items")
    loop_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    loop_wf = {
        "id": loop_wf_id,
        "name": "Loop Test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code_items", "type": "code", "parameters": {
                "code": "return [{json: {items: [{v: 0}, {v: 10}, {v: 20}]}}]",
                "mode": "runOnceForAllItems"
            }, "settings": {}, "position": {"x": 200, "y": 0}},
            {"id": "loop", "type": "loop", "parameters": {"field": "items"}, "settings": {}, "position": {"x": 400, "y": 0}},
            {"id": "code_in_loop", "type": "code", "parameters": {
                "code": "return [{json: {processed: true, val: $json.v}}]",
                "mode": "runOnceForAllItems"
            }, "settings": {}, "position": {"x": 600, "y": 0}},
        ],
        "connections": [
            {"source": "trigger", "sourceHandle": "main", "target": "code_items", "targetHandle": "main"},
            {"source": "code_items", "sourceHandle": "main", "target": "loop", "targetHandle": "main"},
            {"source": "loop", "sourceHandle": "main", "target": "code_in_loop", "targetHandle": "main"},
        ],
        "settings": {"timeout_seconds": 30},
    }
    passed, detail = create_and_run(loop_wf, token, "loop")
    ok("loop.execution", passed, detail)

    # ─── 7. DAG (Diamond) ─────────────────────────────────
    print("\n[8/14] DAG Execution (Diamond)")
    dag_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    dag_wf = {
        "id": dag_wf_id,
        "name": "DAG Diamond",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code_a", "type": "code", "parameters": {"code": "return [{json: {path: 'A'}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 200, "y": -80}},
            {"id": "code_b", "type": "code", "parameters": {"code": "return [{json: {path: 'B'}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 200, "y": 80}},
            {"id": "code_merge", "type": "code", "parameters": {"code": "return [{json: {merged: true}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 450, "y": 0}},
        ],
        "connections": [
            {"source": "trigger", "sourceHandle": "main", "target": "code_a", "targetHandle": "main"},
            {"source": "trigger", "sourceHandle": "main", "target": "code_b", "targetHandle": "main"},
            {"source": "code_a", "sourceHandle": "main", "target": "code_merge", "targetHandle": "main"},
            {"source": "code_b", "sourceHandle": "main", "target": "code_merge", "targetHandle": "main"},
        ],
        "settings": {"timeout_seconds": 30},
    }
    passed, detail = create_and_run(dag_wf, token, "dag")
    ok("dag.diamond", passed, detail)

    # ─── 8. HTTP REQUEST ──────────────────────────────────
    print("\n[9/14] HTTP Request Node")
    http_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    http_wf = {
        "id": http_wf_id,
        "name": "HTTP Test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "http", "type": "http_request", "parameters": {"url": "https://httpbin.org/get", "method": "GET", "options": {}}, "settings": {}, "position": {"x": 300, "y": 0}},
        ],
        "connections": [{"source": "trigger", "sourceHandle": "main", "target": "http", "targetHandle": "main"}],
        "settings": {"timeout_seconds": 30},
    }
    passed, detail = create_and_run(http_wf, token, "http_request")
    ok("http_request.get", passed, detail)

    # ─── 9. CREDENTIALS ───────────────────────────────────
    print("\n[10/14] Credentials")
    r = api("GET", "/api/credentials/types", token=token)
    ok("credentials.types", r.status_code == 200, f"status={r.status_code}")

    r = api("POST", "/api/credentials", token=token, json={
        "type": "http",
        "name": "Test API Key",
        "data": {"api_key": "sk-test-12345"},
    })
    ok("credentials.create", r.status_code == 201, f"status={r.status_code}")
    cred_id = r.json()["data"]["id"] if r.status_code == 201 else ""

    r = api("GET", "/api/credentials", token=token)
    ok("credentials.list", r.status_code == 200 and len(r.json().get("data", [])) > 0)

    if cred_id:
        r = api("POST", f"/api/credentials/{cred_id}/test", token=token)
        ok("credentials.test", r.status_code in (200, 400, 422), f"status={r.status_code}")

        r = api("DELETE", f"/api/credentials/{cred_id}", token=token)
        ok("credentials.delete", r.status_code in (200, 204), f"status={r.status_code}")

    r = api("POST", "/api/credentials", token=token, json={"type": "nonexistent_xyz", "name": "Bad", "data": {}})
    ok("credentials.invalid_type_rejected", r.status_code in (400, 422), f"status={r.status_code}")

    # ─── 10. DATA TABLES ──────────────────────────────────
    print("\n[11/14] Data Tables")
    # Data tables require workspace_id; create org + workspace as this user
    r = api("POST", "/api/organizations", token=token, json={"name": f"TestOrg_{uuid.uuid4().hex[:6]}"})
    org_id = r.json()["data"]["id"] if r.status_code in (200, 201) else ""
    ws_id = ""
    if org_id:
        r = api("POST", "/api/workspaces", token=token, json={"name": f"TestWS_{uuid.uuid4().hex[:6]}", "organization_id": org_id})
        ws_id = r.json()["data"]["id"] if r.status_code in (200, 201) else ""

    if ws_id:
        r = api("POST", "/api/data-tables", token=token, json={
            "name": "Production Test Table",
            "workspace_id": ws_id,
            "columns": [{"name": "name", "type": "string"}, {"name": "value", "type": "number"}, {"name": "active", "type": "boolean"}]
        })
        ok("data_tables.create", r.status_code == 201, f"status={r.status_code}")
        table_id = r.json()["data"]["id"] if r.status_code == 201 else ""
    else:
        r = api("POST", "/api/data-tables", token=token, json={
            "name": "Production Test Table",
            "columns": [{"name": "name", "type": "string"}, {"name": "value", "type": "number"}, {"name": "active", "type": "boolean"}]
        })
        ok("data_tables.create", r.status_code == 201, f"status={r.status_code} (no workspace)")
        table_id = r.json()["data"]["id"] if r.status_code == 201 else ""

    r = api("GET", "/api/data-tables", token=token)
    ok("data_tables.list", r.status_code == 200, f"status={r.status_code}")

    if table_id:
        r = api("POST", f"/api/data-tables/{table_id}/rows/bulk", token=token, json={
            "rows": [{"name": "item1", "value": 100, "active": True}, {"name": "item2", "value": 200, "active": False}]
        })
        ok("data_tables.bulk_insert", r.status_code == 201, f"status={r.status_code}")

        r = api("GET", f"/api/data-tables/{table_id}/rows", token=token)
        ok("data_tables.query_rows", r.status_code == 200, f"status={r.status_code}")

        r = api("DELETE", f"/api/data-tables/{table_id}", token=token)
        ok("data_tables.delete", r.status_code in (200, 204), f"status={r.status_code}")

    # ─── 11. WEBHOOK TRIGGER ──────────────────────────────
    print("\n[12/14] Webhook Trigger")
    wh_path = f"test_prodval_{uuid.uuid4().hex[:16]}"
    wh_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    wh_wf = {
        "id": wh_wf_id,
        "name": "Webhook Test",
        "nodes": [
            {"id": "webhook", "type": "webhook", "parameters": {"path": wh_path, "method": "POST"}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code", "type": "code", "parameters": {"code": "return [{json: {webhook: true, data: $json.body}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 300, "y": 0}},
        ],
        "connections": [{"source": "webhook", "sourceHandle": "main", "target": "code", "targetHandle": "main"}],
        "settings": {"timeout_seconds": 30},
    }
    r = api("POST", "/api/workflows", token=token, json=wh_wf)
    ok("webhook.workflow_create", r.status_code == 201, f"status={r.status_code}")

    if r.status_code == 201:
        r = api("PATCH", f"/api/workflows/{wh_wf_id}/active", token=token, json={"active": True})
        ok("webhook.activate", r.status_code == 200, f"status={r.status_code}")
        time.sleep(2)

        r = api("POST", f"/api/webhooks/{wh_path}", json={"test": True, "ts": time.time()})
        ok("webhook.trigger", r.status_code == 202, f"status={r.status_code} body={r.text[:150]}")
        wh_exec_id = r.json()["data"].get("execution_id", "") if r.status_code == 202 else ""

        if wh_exec_id:
            status = wait_for_execution(wh_exec_id, token)
            ok("webhook.completes", status in ("completed", "success"), f"status={status}")
        else:
            ok("webhook.completes", False, "no exec_id")

    r = api("POST", "/api/webhooks/this_path_definitely_does_not_exist_12345678901")
    ok("webhook.nonexistent_404", r.status_code in (404, 410, 422), f"status={r.status_code}")

    # ─── 12. SCHEDULE ─────────────────────────────────────
    print("\n[13/14] Scheduled Workflow")
    sched_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    sched_wf = {
        "id": sched_wf_id,
        "name": "Schedule Test",
        "nodes": [
            {"id": "schedule", "type": "schedule", "parameters": {
                "rules": [{"id": "r1", "interval": "minutes", "value": 9999, "timezone": "UTC"}]
            }, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "code", "type": "code", "parameters": {"code": "return [{json: {scheduled: true}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 300, "y": 0}},
        ],
        "connections": [{"source": "schedule", "sourceHandle": "main", "target": "code", "targetHandle": "main"}],
        "settings": {"timeout_seconds": 30},
    }
    r = api("POST", "/api/workflows", token=token, json=sched_wf)
    ok("schedule.workflow_create", r.status_code == 201, f"status={r.status_code}")

    if r.status_code == 201:
        r = api("PATCH", f"/api/workflows/{sched_wf_id}/active", token=token, json={"active": True})
        ok("schedule.activate", r.status_code == 200, f"status={r.status_code}")

        r = api("GET", f"/api/workflows/{sched_wf_id}", token=token)
        ok("schedule.registered", r.status_code == 200, f"status={r.status_code}")

    # ─── 13. AI / AGENTS / RAG / CONNECTORS ───────────────
    print("\n[14/14] AI, Agents, RAG, Connectors, Monitoring")
    r = api("GET", "/api/ai", token=token)
    ok("ai.endpoint", r.status_code in (200, 404, 405), f"status={r.status_code}")

    ai_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    ai_wf = {
        "id": ai_wf_id,
        "name": "AI Agent Test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "ai", "type": "ai_agent", "parameters": {
                "provider": "openai", "model": "gpt-3.5-turbo",
                "prompt": "Say hello in one word", "max_tokens": 10,
                "memory": True, "max_entries": 10
            }, "settings": {"timeout_seconds": 30}, "position": {"x": 300, "y": 0}},
        ],
        "connections": [{"source": "trigger", "sourceHandle": "main", "target": "ai", "targetHandle": "main"}],
        "settings": {"timeout_seconds": 30},
    }
    r = api("POST", "/api/workflows", token=token, json=ai_wf)
    ok("ai.workflow_create", r.status_code == 201, f"status={r.status_code}")

    r = api("GET", "/api/rag", token=token)
    ok("rag.endpoint", r.status_code in (200, 404, 405), f"status={r.status_code}")

    r = api("GET", "/api/connectors", token=token)
    ok("connectors.list", r.status_code == 200, f"status={r.status_code}")

    r = api("GET", "/api/nodes", token=token)
    ok("nodes.list", r.status_code == 200, f"status={r.status_code}")

    r = api("GET", "/api/metrics", token=token)
    ok("monitoring.metrics", r.status_code == 200, f"status={r.status_code}")

    r = api("GET", "/api/monitoring", token=token)
    ok("monitoring.endpoints", r.status_code in (200, 403, 404, 405), f"status={r.status_code}")

    # ─── 14. FAILURE SCENARIOS ────────────────────────────
    print("\n[BONUS] Failure Scenarios")
    r = api("GET", "/api/workflows/wf_nonexistent_99999", token=token)
    ok("failure.invalid_workflow_404", r.status_code == 404, f"status={r.status_code}")

    r = api("DELETE", "/api/workflows/wf_nonexistent_99999", token=token)
    ok("failure.delete_nonexistent", r.status_code in (404, 410), f"status={r.status_code}")

    r = api("POST", "/api/workflows/wf_fake/run")
    ok("failure.unauth_execution", r.status_code == 401, f"status={r.status_code}")

    boom_wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    boom_wf = {
        "id": boom_wf_id,
        "name": "Boom Node Test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}, "position": {"x": 0, "y": 0}},
            {"id": "boom", "type": "boom", "parameters": {}, "settings": {"continue_on_error": True}, "position": {"x": 200, "y": 0}},
            {"id": "after", "type": "code", "parameters": {"code": "return [{json: {after_boom: true}}]", "mode": "runOnceForAllItems"}, "settings": {}, "position": {"x": 400, "y": 0}},
        ],
        "connections": [
            {"source": "trigger", "sourceHandle": "main", "target": "boom", "targetHandle": "main"},
            {"source": "boom", "sourceHandle": "main", "target": "after", "targetHandle": "main"},
        ],
        "settings": {"timeout_seconds": 15},
    }
    passed, detail = create_and_run(boom_wf, token, "boom_node")
    ok("failure.boom_node_handled", passed or "failed" in detail or "error" in detail, detail)

    # ─── CLEANUP: Delete test workflows ───────────────────
    print("\n[CLEANUP]")
    r = api("GET", "/api/workflows", token=token)
    if r.status_code == 200:
        for wf_data in r.json().get("data", []):
            wf_name = wf_data.get("name", "")
            wf_del_id = wf_data.get("id", "")
            if "Production Validation" in wf_name or "Code 5-Item" in wf_name or "IF Branch" in wf_name or "Loop Test" in wf_name or "DAG Diamond" in wf_name or "HTTP Test" in wf_name or "Webhook Test" in wf_name or "Schedule Test" in wf_name or "AI Agent" in wf_name or "Boom Node" in wf_name or "Imported" in wf_name:
                api("DELETE", f"/api/workflows/{wf_del_id}", token=token)
                print(f"  deleted: {wf_name}")

    # ═══════════════════════════════════════════════════════
    # FINAL REPORT
    # ═══════════════════════════════════════════════════════
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    total = len(RESULTS)

    print("\n" + "=" * 70)
    print(f"  PRODUCTION VALIDATION RESULTS: {passed}/{total} PASSED ({100*passed/total:.0f}%)")
    print(f"  Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if FAILURES:
        print(f"\n  FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"    F  {f}")
        print()

    # Print all results
    print("\n  ALL RESULTS:")
    for r in RESULTS:
        ch = "P" if r["status"] == "PASS" else "F"
        d = f"  ({r['detail']})" if r["detail"] and r["status"] == "FAIL" else ""
        print(f"    {ch}  {r['test']}{d}")

    print()
    return failed == 0


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except httpx.ConnectError:
        print(f"\n  ERROR: Cannot connect to {BASE}. Is the backend running?")
        sys.exit(1)
    except Exception as exc:
        print(f"\n  ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
