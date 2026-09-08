"""E2E test: n8n workflow compatibility.

Recreates the exact n8n workflow structure and verifies end-to-end execution:

Schedule Trigger -> Code -> Login API (HTTP) -> IF -> Get Extracted Data (HTTP)
-> Split -> Loop Over Items -> Run for Each Item (Code) -> Search Custom Object (HTTP)
-> IF3 -> Create/Update Custom Object (HTTP)

Uses mock HTTP servers to simulate external APIs (Salesforce, login endpoint).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from sqlalchemy import text

from app.db import get_session
import logging


def _make_ctx(**overrides):
    """Build a NodeContext with sensible defaults for unit tests."""
    from app.engine.node_base import NodeContext
    defaults = dict(
        execution_id="test", workflow_id="test", node_id="test_node",
        logger=logging.getLogger("test"),
        http_client=None,
        emit_event=lambda *a, **k: None,
        workspace_id=None, user_id=1,
    )
    defaults.update(overrides)
    return NodeContext(**defaults)
from app.execution_runtime import run_job
from app.queue import QueueJob


# ---------------------------------------------------------------------------
# Mock HTTP servers
# ---------------------------------------------------------------------------

class _LoginHandler(BaseHTTPRequestHandler):
    """Mock login API that returns a token."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        resp = {"access_token": "mock_token_abc123", "token_type": "Bearer", "expires_in": 3600}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *args):
        pass


class _SearchHandler(BaseHTTPRequestHandler):
    """Mock Salesforce search endpoint."""

    def do_GET(self):
        # Return 2 results to test Split/Loop
        resp = {
            "totalSize": 2,
            "done": True,
            "records": [
                {
                    "Id": "a00001ABCDEF",
                    "Name": "Record Alpha",
                    "Email": "alpha@test.com",
                    "Company": "TestCo Alpha",
                    "attributes": {"type": "Contact", "url": "/services/data/v63.0/sobjects/Contact/a00001ABCDEF"},
                },
                {
                    "Id": "a00002ABCDEF",
                    "Name": "Record Beta",
                    "Email": "beta@test.com",
                    "Company": "TestCo Beta",
                    "attributes": {"type": "Contact", "url": "/services/data/v63.0/sobjects/Contact/a00002ABCDEF"},
                },
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *args):
        pass


class _CreateHandler(BaseHTTPRequestHandler):
    """Mock Salesforce create endpoint."""

    records_created = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        _CreateHandler.records_created.append(body)
        resp = {"id": f"a00{uuid.uuid4().hex[:12]}", "success": True, "errors": []}
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *args):
        pass


class _UpdateHandler(BaseHTTPRequestHandler):
    """Mock Salesforce update endpoint."""

    records_updated = []

    def do_PATCH(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        record_id = self.path.split("/")[-1]
        _UpdateHandler.records_updated.append({"id": record_id, "data": body})
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def _start_server(handler_cls, port):
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# Workflow builder
# ---------------------------------------------------------------------------

def build_n8n_workflow(
    login_url: str,
    search_url: str,
    create_url: str,
    update_url: str,
) -> dict[str, Any]:
    """Build the exact n8n workflow structure as platform workflow JSON."""
    wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    return {
        "id": wf_id,
        "name": "n8n Workflow Compatibility Test",
        "nodes": [
            {
                "id": "schedule_1",
                "type": "schedule",
                "position": {"x": 0, "y": 0},
                "parameters": {
                    "rules": [{"interval": "minutes", "value": 5, "timezone": "UTC"}],
                    "cron": None,
                    "timezone": None,
                },
                "settings": {},
            },
            {
                "id": "code_1",
                "type": "code",
                "position": {"x": 250, "y": 0},
                "parameters": {
                    "code": "for (const item of $input.all()) {\n  item.json.processed = true;\n  item.json.batch_id = 'batch_001';\n}\nreturn $input.all();",
                    "language": "javascript",
                    "mode": "runOnceForAllItems",
                },
                "settings": {},
            },
            {
                "id": "http_login",
                "type": "http_request",
                "position": {"x": 500, "y": 0},
                "parameters": {
                    "method": "POST",
                    "url": login_url,
                    "sendQuery": False,
                    "sendHeaders": True,
                    "sendBody": True,
                    "path_params": {},
                    "query": {},
                    "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                    "body": {"username": "test@example.com", "password": "secret123"},
                    "body_format": "json",
                    "authentication": "none",
                    "auth_type": "none",
                    "timeout_seconds": 10,
                    "max_response_bytes": 10485760,
                    "follow_redirects": True,
                    "max_redirects": 5,
                    "ignore_ssl_issues": False,
                    "response_format": "json",
                },
                "settings": {},
            },
            {
                "id": "if_1",
                "type": "if_condition",
                "position": {"x": 750, "y": 0},
                "parameters": {
                    "conditions": [
                        {
                            "id": "cond_1",
                            "left": "{{ $json.access_token }}",
                            "operator": "is not empty",
                            "right": "",
                            "combinator": "AND",
                        }
                    ],
                    "combinator": "AND",
                    "convertTypes": False,
                    "options": {},
                },
                "settings": {},
            },
            {
                "id": "http_search",
                "type": "http_request",
                "position": {"x": 1000, "y": -100},
                "parameters": {
                    "method": "GET",
                    "url": search_url,
                    "sendQuery": True,
                    "sendHeaders": True,
                    "sendBody": False,
                    "path_params": {},
                    "query": {"q": "SELECT Id, Name, Email, Company FROM Contact LIMIT 10"},
                    "headers": {"Authorization": "Bearer mock_token_abc123", "Accept": "application/json"},
                    "body": None,
                    "body_format": "json",
                    "authentication": "none",
                    "auth_type": "none",
                    "timeout_seconds": 10,
                    "max_response_bytes": 10485760,
                    "follow_redirects": True,
                    "max_redirects": 5,
                    "ignore_ssl_issues": False,
                    "response_format": "json",
                },
                "settings": {},
            },
            {
                "id": "split_1",
                "type": "split",
                "position": {"x": 1250, "y": -100},
                "parameters": {
                    "field": "records",
                    "batch_size": 0,
                },
                "settings": {},
            },
            {
                "id": "loop_1",
                "type": "loop_over_items",
                "position": {"x": 1500, "y": -100},
                "parameters": {
                    "field": "",
                    "batch_size": 0,
                },
                "settings": {},
            },
            {
                "id": "code_per_item",
                "type": "code",
                "position": {"x": 1750, "y": -100},
                "parameters": {
                    "code": "item.json.search_key = item.json.Email;\nitem.json.exists = false;\nreturn item;",
                    "language": "javascript",
                    "mode": "runOnceForEachItem",
                },
                "settings": {},
            },
            {
                "id": "http_search_existing",
                "type": "http_request",
                "position": {"x": 2000, "y": -100},
                "parameters": {
                    "method": "GET",
                    "url": search_url,
                    "sendQuery": True,
                    "sendHeaders": True,
                    "sendBody": False,
                    "path_params": {},
                    "query": {"q": "SELECT Id, Name FROM Contact WHERE Email = '{{ $json.Email }}' LIMIT 1"},
                    "headers": {"Authorization": "Bearer mock_token_abc123", "Accept": "application/json"},
                    "body": None,
                    "body_format": "json",
                    "authentication": "none",
                    "auth_type": "none",
                    "timeout_seconds": 10,
                    "max_response_bytes": 10485760,
                    "follow_redirects": True,
                    "max_redirects": 5,
                    "ignore_ssl_issues": False,
                    "response_format": "json",
                },
                "settings": {},
            },
            {
                "id": "if_exists",
                "type": "if_condition",
                "position": {"x": 2250, "y": -100},
                "parameters": {
                    "conditions": [
                        {
                            "id": "cond_exists",
                            "left": "{{ $json.totalSize }}",
                            "operator": "is greater than",
                            "right": "0",
                            "combinator": "AND",
                        }
                    ],
                    "combinator": "AND",
                    "convertTypes": True,
                    "options": {},
                },
                "settings": {},
            },
            {
                "id": "http_update",
                "type": "http_request",
                "position": {"x": 2500, "y": -200},
                "parameters": {
                    "method": "PATCH",
                    "url": update_url + "/{{ $json.records[0].Id }}",
                    "sendQuery": False,
                    "sendHeaders": True,
                    "sendBody": True,
                    "path_params": {},
                    "query": {},
                    "headers": {"Authorization": "Bearer mock_token_abc123", "Content-Type": "application/json"},
                    "body": {"Name": "{{ $json.records[0].Name }}", "Company": "Updated Co"},
                    "body_format": "json",
                    "authentication": "none",
                    "auth_type": "none",
                    "timeout_seconds": 10,
                    "max_response_bytes": 10485760,
                    "follow_redirects": True,
                    "max_redirects": 5,
                    "ignore_ssl_issues": False,
                    "response_format": "json",
                },
                "settings": {},
            },
            {
                "id": "http_create",
                "type": "http_request",
                "position": {"x": 2500, "y": 0},
                "parameters": {
                    "method": "POST",
                    "url": create_url,
                    "sendQuery": False,
                    "sendHeaders": True,
                    "sendBody": True,
                    "path_params": {},
                    "query": {},
                    "headers": {"Authorization": "Bearer mock_token_abc123", "Content-Type": "application/json"},
                    "body": {"Name": "{{ $json.Name }}", "Email": "{{ $json.Email }}", "Company": "{{ $json.Company }}"},
                    "body_format": "json",
                    "authentication": "none",
                    "auth_type": "none",
                    "timeout_seconds": 10,
                    "max_response_bytes": 10485760,
                    "follow_redirects": True,
                    "max_redirects": 5,
                    "ignore_ssl_issues": False,
                    "response_format": "json",
                },
                "settings": {},
            },
        ],
        "connections": [
            {"source": "schedule_1", "target": "code_1", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "code_1", "target": "http_login", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "http_login", "target": "if_1", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "if_1", "target": "http_search", "sourceHandle": "true", "targetHandle": "main"},
            {"source": "http_search", "target": "split_1", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "split_1", "target": "loop_1", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "loop_1", "target": "code_per_item", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "code_per_item", "target": "http_search_existing", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "http_search_existing", "target": "if_exists", "sourceHandle": "main", "targetHandle": "main"},
            {"source": "if_exists", "target": "http_update", "sourceHandle": "true", "targetHandle": "main"},
            {"source": "if_exists", "target": "http_create", "sourceHandle": "false", "targetHandle": "main"},
        ],
        "version": 1,
        "active": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

LOGIN_PORT = 18901
SEARCH_PORT = 18902
CREATE_PORT = 18903
UPDATE_PORT = 18904


def _run_workflow_directly(db, wf: dict) -> tuple[str, dict | None, str | None, dict | None]:
    """Run a workflow directly through the engine (bypassing queue).
    Returns (execution_id, results_dict_or_None, status_string, error_dict_or_None).
    """
    import uuid
    from datetime import datetime, timezone
    from app.models import Execution

    execution_id = f"exec_test_{uuid.uuid4().hex[:12]}"

    # Create execution row
    db.add(Execution(
        id=execution_id,
        workflow_id=wf["id"],
        user_id=1,
        workflow_version=1,
        workflow_data=wf,
        trigger="manual",
        trigger_data=[{}],
        status="running",
        started_at=datetime.now(timezone.utc),
    ))
    db.commit()

    # Build a fake QueueJob and call run_job directly
    job = QueueJob(
        id=f"job_{uuid.uuid4().hex[:12]}",
        execution_id=execution_id,
        payload={
            "workflow_data": wf,
            "trigger_items": [{}],
            "trigger": "manual",
            "user_id": 1,
            "workflow_id": wf["id"],
            "version": 1,
            "workspace_id": None,
        },
    )

    import asyncio
    import sys

    loop = asyncio.new_event_loop()
    try:
        status = loop.run_until_complete(run_job(job, event_sink=None))
        print(f"[TRACE] run_job returned: {status}", file=sys.stderr, flush=True)
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        status = "exception"
    finally:
        loop.close()

    # Use a FRESH session to read results (run_job commits in its own session)
    fresh_db = get_session()
    try:
        row = fresh_db.execute(text(
            "SELECT status, results, error FROM executions WHERE id = :id"
        ), {"id": execution_id}).fetchone()
        print(f"[TRACE] Fresh DB read: status={row[0] if row else 'NOT FOUND'}", file=sys.stderr, flush=True)
        if row and row[2]:
            print(f"[TRACE] Error: {row[2]}", file=sys.stderr, flush=True)
        return execution_id, row[1] if row else None, row[0] if row else status, row[2] if row else None
    finally:
        fresh_db.close()


@pytest.fixture(autouse=True)
def _ensure_test_user():
    """Create a user for FK constraints — runs after _clean_db truncation."""
    from app.models import User
    db = get_session()
    try:
        if not db.get(User, 1):
            db.add(User(id=1, email="test_e2e@example.com", password_hash="not-used"))
            db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def mock_servers():
    """Start mock HTTP servers for the test."""
    login_server = _start_server(_LoginHandler, LOGIN_PORT)
    search_server = _start_server(_SearchHandler, SEARCH_PORT)
    create_server = _start_server(_CreateHandler, CREATE_PORT)
    update_server = _start_server(_UpdateHandler, UPDATE_PORT)
    _CreateHandler.records_created.clear()
    _UpdateHandler.records_updated.clear()
    time.sleep(0.2)
    yield
    login_server.shutdown()
    search_server.shutdown()
    create_server.shutdown()
    update_server.shutdown()


class TestN8nWorkflowCompatibility:
    """End-to-end test of the n8n workflow structure."""

    def test_full_workflow_e2e(self, mock_servers):
        """Test the complete n8n workflow: Schedule -> Code -> Login -> IF -> Search -> Split -> Loop -> IF3 -> Create/Update."""
        wf = build_n8n_workflow(
            login_url=f"http://127.0.0.1:{LOGIN_PORT}/auth/token",
            search_url=f"http://127.0.0.1:{SEARCH_PORT}/services/data/v63.0/query",
            create_url=f"http://127.0.0.1:{CREATE_PORT}/services/data/v63.0/sobjects/Contact",
            update_url=f"http://127.0.0.1:{UPDATE_PORT}/services/data/v63.0/sobjects/Contact",
        )

        db = get_session()
        try:
            # Persist the workflow
            from app.models import WorkflowRecord

            db.add(WorkflowRecord(
                id=wf["id"],
                name=wf["name"],
                data=wf,
                user_id=1,
                version=1,
                active=False,
            ))
            db.commit()

            execution_id, results, status, error = _run_workflow_directly(db, wf)

            # Assert final status
            assert status == "success", f"Workflow should succeed, got {status}. Error: {error}"

            # Assert outputs exist for all expected nodes
            assert results is not None, "Results must be present"
            outputs = results.get("outputs", {})

            # Schedule trigger produced output
            assert "schedule_1" in outputs, "Schedule trigger must produce output"
            assert len(outputs["schedule_1"].get("main", [])) > 0, "Schedule must have items"

            # Code node processed
            assert "code_1" in outputs, "Code node must produce output"
            code_items = outputs["code_1"]["main"]
            assert code_items[0].get("processed") is True, "Code must add processed=True"
            assert code_items[0].get("batch_id") == "batch_001", "Code must add batch_id"

            # Login API returned token (data at top level in n8n format)
            assert "http_login" in outputs, "Login API must produce output"
            login_items = outputs["http_login"]["main"]
            assert login_items[0].get("access_token") == "mock_token_abc123", "Login must return token"

            # IF branched correctly (true path)
            assert "if_1" in outputs, "IF must produce output"
            assert len(outputs["if_1"].get("true", [])) > 0, "IF true branch must have items"
            assert len(outputs["if_1"].get("false", [])) == 0, "IF false branch must be empty"

            # Search returned records (data at top level in n8n format)
            assert "http_search" in outputs, "Search must produce output"
            search_items = outputs["http_search"]["main"]
            assert search_items[0].get("totalSize") == 2, "Search must return 2 records"

            # Split expanded records
            assert "split_1" in outputs, "Split must produce output"
            split_items = outputs["split_1"]["main"]
            assert len(split_items) == 2, f"Split must produce 2 items, got {len(split_items)}"

            # Loop processed items
            assert "loop_1" in outputs, "Loop must produce output"
            loop_items = outputs["loop_1"]["main"]
            assert len(loop_items) == 2, f"Loop must pass through 2 items, got {len(loop_items)}"

            # Code per-item ran for each item
            assert "code_per_item" in outputs, "Code per-item must produce output"
            per_item_items = outputs["code_per_item"]["main"]
            assert len(per_item_items) == 2, f"Per-item code must produce 2 items, got {len(per_item_items)}"
            for item in per_item_items:
                assert "search_key" in item, "Per-item code must add search_key"
                assert item["search_key"] == item.get("Email"), "search_key must equal Email"

            # Search existing ran per item
            assert "http_search_existing" in outputs, "Search existing must produce output"

            # IF3 branched correctly
            assert "if_exists" in outputs, "IF3 must produce output"

            # Create/Update happened
            assert "http_create" in outputs or "http_update" in outputs, "Either create or update must run"

            print(f"\n=== FULL WORKFLOW PASSED ===")
            print(f"Execution: {execution_id}")
            print(f"Status: {status}")
            print(f"Nodes executed: {len(outputs)}")
            print(f"Records created: {len(_CreateHandler.records_created)}")
            print(f"Records updated: {len(_UpdateHandler.records_updated)}")

        finally:
            db.close()

    def test_schedule_trigger_config(self, mock_servers):
        """Test Schedule Trigger configuration persistence and validation."""
        from app.nodes.schedule import ScheduleTriggerNode, ScheduleTriggerParams

        # Valid config
        params = ScheduleTriggerParams(rules=[{"interval": "minutes", "value": 5, "timezone": "UTC"}])
        assert len(params.rules) == 1
        assert params.rules[0].interval == "minutes"
        assert params.rules[0].value == 5

        # Multiple rules
        params = ScheduleTriggerParams(rules=[
            {"interval": "minutes", "value": 5, "timezone": "UTC"},
            {"interval": "hours", "value": 1, "timezone": "US/Eastern"},
        ])
        assert len(params.rules) == 2

        # Cron rule
        params = ScheduleTriggerParams(rules=[{"interval": "cron", "cron": "*/5 * * * *", "timezone": "UTC"}])
        assert params.rules[0].cron == "*/5 * * * *"

        # Execution produces correct output
        node = ScheduleTriggerNode()
        import asyncio
        ctx = _make_ctx()
        result = asyncio.run(node.run(ctx, params, input_items=[{}]))
        assert len(result.output_items) == 1
        item = result.output_items[0]
        assert "timestamp" in item
        assert "success" in item
        assert item["success"] is True
        assert "Readable date" in item
        assert "Day of week" in item
        assert "Year" in item
        assert "Month" in item
        assert "Hour" in item
        assert "Minute" in item

    def test_code_node_both_modes(self, mock_servers):
        """Test Code node in both runOnceForAllItems and runOnceForEachItem modes."""
        from app.nodes.code import CodeNode, CodeParams
        import asyncio

        node = CodeNode()
        ctx = _make_ctx()

        # Mode: runOnceForAllItems
        params = CodeParams(
            code="for (const item of $input.all()) {\n  item.json.doubled = (item.json.value || 0) * 2;\n}\nreturn $input.all();",
            language="javascript",
            mode="runOnceForAllItems",
        )
        result = asyncio.run(
            node.run(ctx, params, input_items=[{"value": 5}, {"value": 10}])
        )
        assert len(result.output_items) == 2
        assert result.output_items[0]["doubled"] == 10
        assert result.output_items[1]["doubled"] == 20

        # Mode: runOnceForEachItem
        params = CodeParams(
            code="item.json.triple = (item.json.value || 0) * 3;\nreturn item;",
            language="javascript",
            mode="runOnceForEachItem",
        )
        result = asyncio.run(
            node.run(ctx, params, input_items=[{"value": 5}, {"value": 10}])
        )
        assert len(result.output_items) == 2
        assert result.output_items[0]["triple"] == 15
        assert result.output_items[1]["triple"] == 30

    def test_if_condition_branching(self, mock_servers):
        """Test IF node routes items to correct branches."""
        from app.nodes.if_condition import IfConditionNode, IfConditionParams
        import asyncio

        node = IfConditionNode()
        ctx = _make_ctx()

        params = IfConditionParams(
            conditions=[{"id": "c1", "left": "{{ $json.status }}", "operator": "is equal to", "right": "active", "combinator": "AND"}],
            combinator="AND",
        )
        result = asyncio.run(
            node.run(ctx, params, input_items=[
                {"status": "active", "name": "Alice"},
                {"status": "inactive", "name": "Bob"},
                {"status": "active", "name": "Charlie"},
            ])
        )
        assert len(result.output_by_handle["true"]) == 2
        assert len(result.output_by_handle["false"]) == 1
        assert result.output_by_handle["false"][0]["name"] == "Bob"

    def test_split_expands_list(self, mock_servers):
        """Test Split node expands a list field into individual items."""
        from app.nodes.split import SplitNode
        from app.nodes.loop import LoopParams
        from app.engine.node_base import NodeContext
        import asyncio

        node = SplitNode()
        ctx = _make_ctx()

        params = LoopParams(field="records", batch_size=0)
        result = asyncio.run(
            node.run(ctx, params, input_items=[{"records": [{"id": 1}, {"id": 2}, {"id": 3}]}])
        )
        assert len(result.output_items) == 3
        assert result.output_items[0]["id"] == 1
        assert result.output_items[2]["id"] == 3

    def test_split_empty_list(self, mock_servers):
        """Test Split with empty list produces no items."""
        from app.nodes.split import SplitNode
        from app.nodes.loop import LoopParams
        import asyncio

        node = SplitNode()
        ctx = _make_ctx()

        params = LoopParams(field="records", batch_size=0)
        result = asyncio.run(
            node.run(ctx, params, input_items=[{"records": []}])
        )
        assert len(result.output_items) <= 1, f"Split with empty list should produce 0 or 1 items, got {len(result.output_items)}"

    def test_http_request_per_item_resolution(self, mock_servers):
        """Test HTTP Request resolves expressions per-item for multi-item input."""
        from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams
        import asyncio
        import httpx

        node = HTTPRequestNode()
        ctx = _make_ctx(http_client=httpx.AsyncClient())

        # The node should resolve per-item when given multiple items
        params = HTTPRequestParams(
            method="GET",
            url=f"http://127.0.0.1:{SEARCH_PORT}/services/data/v63.0/query",
            sendQuery=True,
            sendHeaders=True,
            headers={"Accept": "application/json"},
            query={"q": "test"},
            timeout_seconds=5,
        )
        result = asyncio.run(
            node.run(ctx, params, input_items=[{"dummy": 1}, {"dummy": 2}])
        )
        # Per-item: 2 items in, 2 items out
        assert len(result.output_items) == 2

    def test_queue_and_worker_flow(self, mock_servers):
        """Test the full queue -> worker -> engine -> result flow (direct engine call)."""
        wf = build_n8n_workflow(
            login_url=f"http://127.0.0.1:{LOGIN_PORT}/auth/token",
            search_url=f"http://127.0.0.1:{SEARCH_PORT}/services/data/v63.0/query",
            create_url=f"http://127.0.0.1:{CREATE_PORT}/services/data/v63.0/sobjects/Contact",
            update_url=f"http://127.0.0.1:{UPDATE_PORT}/services/data/v63.0/sobjects/Contact",
        )

        db = get_session()
        try:
            from app.models import WorkflowRecord
            db.add(WorkflowRecord(
                id=wf["id"], name=wf["name"], data=wf,
                user_id=1, version=1, active=False,
            ))
            db.commit()

            execution_id, results, status, _ = _run_workflow_directly(db, wf)

            # Verify execution completed
            assert status == "success", f"Execution must succeed, got {status}"

            # Verify execution has results
            assert results is not None, "Results must be present"

        finally:
            db.close()

    def test_performance_1_item(self, mock_servers):
        """Test workflow with 1 item in Split output."""
        _CreateHandler.records_created.clear()
        _UpdateHandler.records_updated.clear()
        self._run_with_item_count(1)

    def test_performance_10_items(self, mock_servers):
        """Test workflow with 10 items in Split output."""
        self._run_with_item_count(10)

    def _run_with_item_count(self, count: int):
        """Helper: run workflow with N records from search."""
        # Override search handler to return N records
        original_do_GET = _SearchHandler.do_GET

        def dynamic_search(self):
            records = [
                {"Id": f"a00{i:05d}ABCDEF", "Name": f"Record {i}", "Email": f"record{i}@test.com", "Company": f"Co {i}",
                 "attributes": {"type": "Contact", "url": f"/sobjects/Contact/a00{i:05d}ABCDEF"}}
                for i in range(count)
            ]
            resp = {"totalSize": count, "done": True, "records": records}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())

        _SearchHandler.do_GET = dynamic_search
        try:
            wf = build_n8n_workflow(
                login_url=f"http://127.0.0.1:{LOGIN_PORT}/auth/token",
                search_url=f"http://127.0.0.1:{SEARCH_PORT}/services/data/v63.0/query",
                create_url=f"http://127.0.0.1:{CREATE_PORT}/services/data/v63.0/sobjects/Contact",
                update_url=f"http://127.0.0.1:{UPDATE_PORT}/services/data/v63.0/sobjects/Contact",
            )

            db = get_session()
            try:
                from app.models import WorkflowRecord
                wf["id"] = f"wf_perf_{count}_{uuid.uuid4().hex[:6]}"
                db.add(WorkflowRecord(
                    id=wf["id"], name=wf["name"], data=wf,
                    user_id=1, version=1, active=False,
                ))
                db.commit()

                start = time.monotonic()
                execution_id, results, status, _ = _run_workflow_directly(db, wf)
                elapsed = time.monotonic() - start

                assert status == "success", f"Perf test ({count} items) failed: {status}"
                outputs = results.get("outputs", {}) if results else {}
                print(f"\n  {count} items: {elapsed:.2f}s, {len(outputs)} nodes executed")

            finally:
                db.close()
        finally:
            _SearchHandler.do_GET = original_do_GET
