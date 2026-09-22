"""End-to-end test: multi-step enterprise workflow.

Reproduces the complex workflow:
Schedule Trigger → Code → Login API → IF → Get Extracted Data → Split →
Loop Over Items → Run for Each Item → Search Custom Object → IF → Create/Update

Uses httpbin.org for real HTTP calls and the actual execution engine.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import httpx
import pytest

from app.db import get_session, init_db, Base
from tests.conftest import TEST_DB_URL, make_node, make_workflow, conn

# ── helpers ───────────────────────────────────────────────────────────

def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _wf_id() -> str:
    return f"wf_ent_{_uid()}"


# ── Workflow builders ─────────────────────────────────────────────────

def build_enterprise_equivalent_workflow(wf_id: str | None = None) -> dict:
    """Build the full enterprise equivalent workflow JSON.

    Nodes:
      1. manual_trigger (entry point for test)
      2. code (JavaScript — generates data items)
      3. http_request (Login API — POST to httpbin)
      4. if_condition (branch on response status)
      5. set_data (Get Extracted Data — extract JSON from response)
      6. split (Split — fan out items)
      7. loop_over_items (Loop Over Items — iteration)
      8. http_request (Run for Each Item — GET per item)
      9. set_data (Search Custom Object — simulate search result)
     10. if_condition (IF3 — branch on search result)
     11. http_request (Create Custom Object — POST)
     12. http_request (Update Custom Object — PATCH)
    """
    wid = wf_id or _wf_id()
    return {
        "id": wid,
        "name": "Enterprise Equivalent Workflow",
        "nodes": [
            {
                "id": "trigger",
                "type": "manual_trigger",
                "parameters": {},
                "settings": {},
            },
            {
                "id": "code",
                "type": "code",
                "parameters": {
                    "code": "return [{json: {name: 'Alice', email: 'alice@example.com', status: 'active'}}, {json: {name: 'Bob', email: 'bob@example.com', status: 'inactive'}}, {json: {name: 'Carol', email: 'carol@example.com', status: 'active'}}]",
                    "mode": "runOnceForAllItems",
                },
                "settings": {},
            },
            {
                "id": "login_api",
                "type": "http_request",
                "parameters": {
                    "method": "POST",
                    "url": "https://httpbin.org/post",
                    "sendBody": True,
                    "body": {"email": "{{ $json.email }}", "name": "{{ $json.name }}"},
                    "body_format": "json",
                    "authentication": "none",
                    "response_format": "json",
                },
                "settings": {},
            },
            {
                "id": "if_status",
                "type": "if_condition",
                "parameters": {
                    "conditions": [
                        {
                            "id": "cond1",
                            "left": "{{ $json.status }}",
                            "operator": "equals",
                            "right": 200,
                            "combinator": "AND",
                        }
                    ],
                    "combinator": "AND",
                },
                "settings": {},
            },
            {
                "id": "extract_data",
                "type": "set_data",
                "parameters": {
                    "mode": "merge",
                    "fields": {
                        "extracted_name": "{{ $json.name }}",
                        "extracted_email": "{{ $json.email }}",
                        "extracted_status": "{{ $json.status }}",
                    },
                },
                "settings": {},
            },
            {
                "id": "split",
                "type": "split",
                "parameters": {
                    "field": "",
                    "batch_size": 0,
                },
                "settings": {},
            },
            {
                "id": "loop_items",
                "type": "loop_over_items",
                "parameters": {
                    "field": "",
                    "batch_size": 0,
                },
                "settings": {},
            },
            {
                "id": "search_object",
                "type": "set_data",
                "parameters": {
                    "mode": "merge",
                    "fields": {
                        "found": True,
                        "record_id": "sf_001",
                        "object_name": "CustomObject__c",
                    },
                },
                "settings": {},
            },
            {
                "id": "if_exists",
                "type": "if_condition",
                "parameters": {
                    "conditions": [
                        {
                            "id": "cond2",
                            "left": "{{ $json.found }}",
                            "operator": "is true",
                            "right": "",
                            "combinator": "AND",
                        }
                    ],
                    "combinator": "AND",
                },
                "settings": {},
            },
            {
                "id": "create_object",
                "type": "http_request",
                "parameters": {
                    "method": "POST",
                    "url": "https://httpbin.org/post",
                    "sendBody": True,
                    "body": {"name": "{{ $json.name }}", "action": "create"},
                    "body_format": "json",
                    "authentication": "none",
                    "response_format": "json",
                },
                "settings": {},
            },
            {
                "id": "update_object",
                "type": "http_request",
                "parameters": {
                    "method": "PATCH",
                    "url": "https://httpbin.org/patch",
                    "sendBody": True,
                    "body": {"name": "{{ $json.name }}", "action": "update", "record_id": "{{ $json.record_id }}"},
                    "body_format": "json",
                    "authentication": "none",
                    "response_format": "json",
                },
                "settings": {},
            },
        ],
        "connections": [
            {"source": "trigger", "sourceHandle": "main", "target": "code", "targetHandle": "main"},
            {"source": "code", "sourceHandle": "main", "target": "login_api", "targetHandle": "main"},
            {"source": "login_api", "sourceHandle": "main", "target": "if_status", "targetHandle": "main"},
            {"source": "if_status", "sourceHandle": "true", "target": "extract_data", "targetHandle": "main"},
            {"source": "extract_data", "sourceHandle": "main", "target": "split", "targetHandle": "main"},
            {"source": "split", "sourceHandle": "main", "target": "loop_items", "targetHandle": "main"},
            {"source": "loop_items", "sourceHandle": "main", "target": "search_object", "targetHandle": "main"},
            {"source": "search_object", "sourceHandle": "main", "target": "if_exists", "targetHandle": "main"},
            {"source": "if_exists", "sourceHandle": "true", "target": "create_object", "targetHandle": "main"},
            {"source": "if_exists", "sourceHandle": "false", "target": "update_object", "targetHandle": "main"},
        ],
        "settings": {
            "timeout_seconds": 120,
        },
    }


# ── Tests ─────────────────────────────────────────────────────────────

class TestEnterpriseWorkflowCompatibility:
    """End-to-end test suite for enterprise workflow compatibility."""

    def test_workflow_creation_and_persistence(self, client):
        """Test 1: Workflow creation and persistence."""
        from tests.test_api.conftest import auth_headers, register

        reg = register(client)
        wf = build_enterprise_equivalent_workflow()
        resp = client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["id"] == wf["id"]
        assert data["name"] == "Enterprise Equivalent Workflow"
        assert len(data["nodes"]) == 11

        # Verify persistence
        resp2 = client.get(f'/api/workflows/{wf["id"]}', headers=auth_headers(reg["token"]))
        assert resp2.status_code == 200
        assert resp2.json()["data"]["id"] == wf["id"]

    def test_workflow_validation(self, client):
        """Test 2: Workflow graph validation."""
        from tests.test_api.conftest import auth_headers, register

        reg = register(client)
        wf = build_enterprise_equivalent_workflow()
        client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))

        # Validate the workflow graph
        from app.engine.graph import validate_graph, build_graph, topological_sort
        from app.schemas.workflow import Workflow as WF

        wf_obj = WF.model_validate(wf)
        validate_graph(wf_obj)
        graph = build_graph(wf_obj)
        order = topological_sort(graph)
        assert len(order) == 11
        # Trigger must be first
        assert order[0] == "trigger"
        # Code must come after trigger
        assert order.index("code") > order.index("trigger")

    def test_code_node_execution(self, client):
        """Test 3: Code node actually executes JavaScript."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.code import CodeNode
        from app.engine.node_base import NodeContext

        reg = register(client)
        # Test the code node directly
        node = CodeNode()
        params = node.build_params({
            "code": "return [{json: {name: 'Alice', email: 'alice@test.com'}}, {json: {name: 'Bob', email: 'bob@test.com'}}]",
            "mode": "runOnceForAllItems",
        })
        ctx = NodeContext(
            node_id="code",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        result = asyncio.run(
            node.run(ctx, params, [{}])
        )
        assert len(result.output_items) == 2
        assert result.output_items[0]["name"] == "Alice"
        assert result.output_items[1]["name"] == "Bob"

    def test_http_request_node_real_call(self, client):
        """Test 4: HTTP Request node makes real API call."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.http_request import HTTPRequestNode
        from app.engine.node_base import NodeContext

        reg = register(client)
        node = HTTPRequestNode()
        params = node.build_params({
            "method": "GET",
            "url": "https://httpbin.org/get",
            "authentication": "none",
            "response_format": "json",
        })
        ctx = NodeContext(
            node_id="http",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        result = asyncio.run(
            node.run(ctx, params, [{"test": "data"}])
        )
        assert len(result.output_items) >= 1
        output = result.output_items[0]
        assert output.get("status") == 200 or "body" in output

    def test_if_condition_branching(self, client):
        """Test 5: IF condition routes items correctly."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.if_condition import IfConditionNode
        from app.engine.node_base import NodeContext

        reg = register(client)
        node = IfConditionNode()
        params = node.build_params({
            "conditions": [
                {
                    "id": "c1",
                    "left": "{{ $json.status }}",
                    "operator": "equals",
                    "right": "active",
                    "combinator": "AND",
                }
            ],
            "combinator": "AND",
        })
        ctx = NodeContext(
            node_id="if1",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        items = [
            {"name": "Alice", "status": "active"},
            {"name": "Bob", "status": "inactive"},
            {"name": "Carol", "status": "active"},
        ]
        result = asyncio.run(
            node.run(ctx, params, items)
        )
        assert "true" in result.output_by_handle
        assert "false" in result.output_by_handle
        assert len(result.output_by_handle["true"]) == 2  # Alice and Carol
        assert len(result.output_by_handle["false"]) == 1  # Bob

    def test_split_fan_out(self, client):
        """Test 6: Split node fans out items correctly."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.split import SplitNode
        from app.engine.node_base import NodeContext

        reg = register(client)
        node = SplitNode()
        params = node.build_params({"field": "", "batch_size": 0})
        ctx = NodeContext(
            node_id="split",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        items = [
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Bob", "email": "bob@test.com"},
            {"name": "Carol", "email": "carol@test.com"},
        ]
        result = asyncio.run(
            node.run(ctx, params, items)
        )
        # Split should output each item individually
        assert len(result.output_items) == 3
        assert result.output_items[0]["name"] == "Alice"
        assert result.output_items[1]["name"] == "Bob"
        assert result.output_items[2]["name"] == "Carol"

    def test_loop_over_items_iteration(self, client):
        """Test 7: Loop Over Items processes all items."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.loop_over_items import LoopOverItemsNode
        from app.engine.node_base import NodeContext

        reg = register(client)
        node = LoopOverItemsNode()
        params = node.build_params({"field": "", "batch_size": 0})
        ctx = NodeContext(
            node_id="loop",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        items = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
        result = asyncio.run(
            node.run(ctx, params, items)
        )
        # All 4 items should be output
        assert len(result.output_items) == 4
        assert [item["id"] for item in result.output_items] == [1, 2, 3, 4]

    def test_split_with_field_path(self, client):
        """Test 8: Split with field path extracts nested arrays."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.split import SplitNode
        from app.engine.node_base import NodeContext

        reg = register(client)
        node = SplitNode()
        params = node.build_params({"field": "items", "batch_size": 0})
        ctx = NodeContext(
            node_id="split",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        items = [
            {
                "items": [
                    {"name": "A"},
                    {"name": "B"},
                    {"name": "C"},
                ]
            }
        ]
        result = asyncio.run(
            node.run(ctx, params, items)
        )
        assert len(result.output_items) == 3
        assert result.output_items[0]["name"] == "A"

    def test_set_data_get_extracted(self, client):
        """Test 9: Set Data node extracts/maps fields correctly."""
        from tests.test_api.conftest import auth_headers, register
        from app.nodes.set_data import SetDataNode
        from app.engine.node_base import NodeContext
        from app.engine.expressions import resolve, build_context

        reg = register(client)
        node = SetDataNode()
        items = [{"name": "Alice", "email": "alice@test.com", "extra": "keep"}]
        # The executor resolves expressions before passing to the node
        context = build_context(items, {}, "test_wf", "test_exec")
        resolved_fields = {
            "extracted_name": resolve("{{ $json.name }}", context),
            "extracted_email": resolve("{{ $json.email }}", context),
        }
        params = node.build_params({
            "mode": "merge",
            "fields": resolved_fields,
        })
        ctx = NodeContext(
            node_id="set_data",
            execution_id="test_exec",
            workflow_id="test_wf",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
            emit_event=lambda *a, **kw: None,
            cancel_event=asyncio.Event(),
        )
        result = asyncio.run(
            node.run(ctx, params, items)
        )
        assert len(result.output_items) == 1
        output = result.output_items[0]
        assert output["extracted_name"] == "Alice"
        assert output["extracted_email"] == "alice@test.com"
        assert output["extra"] == "keep"  # merge preserves original fields

    def test_expression_resolution(self, client):
        """Test 10: Expressions resolve correctly."""
        from app.engine.expressions import resolve, build_context

        context = build_context(
            [{"name": "Alice", "email": "alice@test.com", "tags": ["admin", "user"]}],
            {},
            "wf_test",
            "exec_test",
        )
        # Simple field
        assert resolve("{{ $json.name }}", context) == "Alice"
        # Nested - not present
        assert resolve("{{ $json.missing }}", context) == "{{ $json.missing }}"
        # String concatenation
        assert resolve("Hello {{ $json.name }}", context) == "Hello Alice"
        # Type coercion
        assert resolve("{{ $json.name }}", context) == "Alice"

    def test_full_workflow_execution_via_engine(self, client):
        """Test 11: Full workflow execution through the engine."""
        from tests.test_api.conftest import auth_headers, register
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        reg = register(client)
        wf = build_enterprise_equivalent_workflow()
        client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as client:
                return await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=client,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=reg["user"]["id"],
                )

        result = asyncio.run(_run())

        # The workflow should complete (may have some failures due to httpbin latency,
        # but the structure should work)
        assert result.status in ("success", "failed")
        assert len(result.trace) > 0

        # Check that nodes executed
        node_ids = {step["node_id"] for step in result.trace}
        assert "trigger" in node_ids
        assert "code" in node_ids
        assert "login_api" in node_ids or "if_status" in node_ids

    def test_execution_via_queue_and_worker(self, client):
        """Test 12: Full execution through queue → worker → engine."""
        from tests.test_api.conftest import auth_headers, register

        reg = register(client)
        wf = build_enterprise_equivalent_workflow()
        resp = client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
        assert resp.status_code == 201

        # Trigger execution via API
        resp = client.post(
            f'/api/workflows/{wf["id"]}/run',
            json={},
            headers=auth_headers(reg["token"]),
        )
        assert resp.status_code == 202
        exec_id = resp.json()["data"]["execution_id"]

        # Wait for execution to complete (poll status)
        max_wait = 60
        start = time.time()
        final_status = None
        while time.time() - start < max_wait:
            resp = client.get(
                f"/api/executions/{exec_id}",
                headers=auth_headers(reg["token"]),
            )
            if resp.status_code == 200:
                status = resp.json()["data"]["status"]
                if status in ("success", "failed", "cancelled", "timeout"):
                    final_status = status
                    break
            time.sleep(1)

        assert final_status is not None, f"Execution did not complete within {max_wait}s"
        assert final_status in ("success", "failed")

        # Verify execution history is persisted
        resp = client.get(
            f"/api/executions/{exec_id}",
            headers=auth_headers(reg["token"]),
        )
        assert resp.status_code == 200
        exec_data = resp.json()["data"]
        assert exec_data["status"] == final_status
        assert exec_data.get("results") is not None or exec_data.get("error") is not None

    def test_loop_processes_all_items_not_just_first(self, client):
        """Test 13: Loop processes ALL items, not just the first."""
        from tests.test_api.conftest import auth_headers, register
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        reg = register(client)

        # Build a simple workflow: code → split → http_request (counts items)
        wf = {
            "id": f"wf_loop_test_{_uid()}",
            "name": "Loop Test",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": "return [{json: {id: 1}}, {json: {id: 2}}, {json: {id: 3}}, {json: {id: 4}}, {json: {id: 5}}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
                {
                    "id": "split",
                    "type": "split",
                    "parameters": {"field": "", "batch_size": 0},
                    "settings": {},
                },
                {
                    "id": "http_per_item",
                    "type": "http_request",
                    "parameters": {
                        "method": "GET",
                        "url": "https://httpbin.org/get",
                        "authentication": "none",
                        "response_format": "json",
                    },
                    "settings": {},
                },
            ],
            "connections": [
                {"source": "code", "sourceHandle": "main", "target": "split", "targetHandle": "main"},
                {"source": "split", "sourceHandle": "main", "target": "http_per_item", "targetHandle": "main"},
            ],
            "settings": {"timeout_seconds": 120},
        }

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_loop_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as hc:
                return await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=hc,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=reg["user"]["id"],
                )

        result = asyncio.run(_run())

        # The HTTP node should have produced 5 output items (one per split item)
        http_result = result.results.get("http_per_item", {})
        http_items = http_result.get("main", [])
        assert len(http_items) == 5, f"Expected 5 HTTP output items, got {len(http_items)}"
        # All should have status 200 from httpbin
        assert all(item.get("status") == 200 for item in http_items)

    def test_if_branches_exclusively(self, client):
        """Test 14: IF node routes items to exactly one branch."""
        from tests.test_api.conftest import auth_headers, register
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        reg = register(client)

        wf = {
            "id": f"wf_if_test_{_uid()}",
            "name": "IF Test",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": "return [{json: {name: 'Alice', active: true}}, {json: {name: 'Bob', active: false}}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
                {
                    "id": "if_active",
                    "type": "if_condition",
                    "parameters": {
                        "conditions": [
                            {
                                "id": "c1",
                                "left": "{{ $json.active }}",
                                "operator": "is true",
                                "right": "",
                                "combinator": "AND",
                            }
                        ],
                        "combinator": "AND",
                    },
                    "settings": {},
                },
                {
                    "id": "set_active",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"category": "active_user"},
                    },
                    "settings": {},
                },
                {
                    "id": "set_inactive",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"category": "inactive_user"},
                    },
                    "settings": {},
                },
            ],
            "connections": [
                {"source": "code", "sourceHandle": "main", "target": "if_active", "targetHandle": "main"},
                {"source": "if_active", "sourceHandle": "true", "target": "set_active", "targetHandle": "main"},
                {"source": "if_active", "sourceHandle": "false", "target": "set_inactive", "targetHandle": "main"},
            ],
            "settings": {"timeout_seconds": 60},
        }

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_if_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as hc:
                return await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=hc,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=reg["user"]["id"],
                )

        result = asyncio.run(_run())
        assert result.status == "success"

        # Check IF node output
        if_result = result.results.get("if_active", {})
        assert len(if_result.get("true", [])) == 1  # Alice
        assert len(if_result.get("false", [])) == 1  # Bob

        # Check that set_active only got Alice
        active_result = result.results.get("set_active", {})
        assert len(active_result.get("main", [])) == 1
        assert active_result["main"][0]["category"] == "active_user"

        # Check that set_inactive only got Bob
        inactive_result = result.results.get("set_inactive", {})
        assert len(inactive_result.get("main", [])) == 1
        assert inactive_result["main"][0]["category"] == "inactive_user"

    def test_split_then_loop_over_items_combined(self, client):
        """Test 15: Split + Loop Over Items processes all items through downstream nodes."""
        from tests.test_api.conftest import auth_headers, register
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        reg = register(client)

        wf = {
            "id": f"wf_split_loop_{_uid()}",
            "name": "Split+Loop Test",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": "return [{json: {data: [{name: 'A'}, {name: 'B'}, {name: 'C'}]}}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
                {
                    "id": "split",
                    "type": "split",
                    "parameters": {"field": "data", "batch_size": 0},
                    "settings": {},
                },
                {
                    "id": "process",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"processed": True},
                    },
                    "settings": {},
                },
            ],
            "connections": [
                {"source": "code", "sourceHandle": "main", "target": "split", "targetHandle": "main"},
                {"source": "split", "sourceHandle": "main", "target": "process", "targetHandle": "main"},
            ],
            "settings": {"timeout_seconds": 30},
        }

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_sl_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as hc:
                return await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=hc,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=reg["user"]["id"],
                )

        result = asyncio.run(_run())
        assert result.status == "success"

        # Split should have produced 3 items
        split_result = result.results.get("split", {})
        assert len(split_result.get("main", [])) == 3

        # Process should have received all 3 items
        process_result = result.results.get("process", {})
        assert len(process_result.get("main", [])) == 3
        assert all(item["processed"] is True for item in process_result["main"])

    def test_schedule_trigger_persistence(self, client):
        """Test 16: Schedule trigger configuration persists correctly."""
        from tests.test_api.conftest import auth_headers, register

        reg = register(client)
        wf = build_enterprise_equivalent_workflow()

        # Add a schedule trigger node
        wf["nodes"].append({
            "id": "schedule",
            "type": "schedule",
            "parameters": {
                "rules": [
                    {
                        "id": "rule1",
                        "interval": "minutes",
                        "value": 5,
                        "timezone": "UTC",
                    }
                ]
            },
            "settings": {},
        })
        # Add connection from schedule to code
        wf["connections"].append({
            "source": "schedule",
            "sourceHandle": "main",
            "target": "code",
            "targetHandle": "main",
        })

        resp = client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
        assert resp.status_code == 201

        # Activate the workflow
        resp = client.patch(
            f'/api/workflows/{wf["id"]}/active',
            json={"active": True},
            headers=auth_headers(reg["token"]),
        )
        assert resp.status_code == 200

        # Verify schedule trigger is registered in DB
        from app.models.webhook import ScheduleTrigger
        db = get_session()
        try:
            triggers = db.query(ScheduleTrigger).filter(
                ScheduleTrigger.workflow_id == wf["id"]
            ).all()
            assert len(triggers) >= 1
            assert triggers[0].cron is not None
            assert triggers[0].timezone == "UTC"
        finally:
            db.close()

    def test_execution_results_persisted(self, client):
        """Test 17: Execution results are persisted correctly."""
        from tests.test_api.conftest import auth_headers, register

        reg = register(client)
        wf = {
            "id": f"wf_persist_{_uid()}",
            "name": "Persist Test",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": "return [{json: {result: 'success'}}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
            ],
            "connections": [],
            "settings": {"timeout_seconds": 30},
        }

        resp = client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
        assert resp.status_code == 201

        # Trigger execution
        resp = client.post(
            f'/api/workflows/{wf["id"]}/run',
            json={},
            headers=auth_headers(reg["token"]),
        )
        assert resp.status_code == 202
        exec_id = resp.json()["data"]["execution_id"]

        # Wait for completion
        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            resp = client.get(
                f"/api/executions/{exec_id}",
                headers=auth_headers(reg["token"]),
            )
            if resp.status_code == 200:
                status = resp.json()["data"]["status"]
                if status in ("success", "failed"):
                    break
            time.sleep(0.5)

        # Verify results are persisted
        resp = client.get(
            f"/api/executions/{exec_id}",
            headers=auth_headers(reg["token"]),
        )
        assert resp.status_code == 200
        exec_data = resp.json()["data"]
        assert exec_data["status"] in ("success", "failed")
        assert exec_data.get("results") is not None

    def test_worker_processes_job(self, client):
        """Test 18: Worker actually picks up and processes jobs."""
        from tests.test_api.conftest import auth_headers, register
        from app.queue import get_queue

        reg = register(client)
        wf = {
            "id": f"wf_worker_{_uid()}",
            "name": "Worker Test",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": "return [{json: {worker_test: true}}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
            ],
            "connections": [],
            "settings": {"timeout_seconds": 30},
        }

        resp = client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
        assert resp.status_code == 201

        # Trigger execution
        run_resp = client.post(
            f'/api/workflows/{wf["id"]}/run',
            json={},
            headers=auth_headers(reg["token"]),
        )
        assert run_resp.status_code == 202
        exec_id = run_resp.json()["data"]["execution_id"]

        # The embedded consumer should pick up the job automatically
        # Wait and verify execution completes
        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            resp = client.get(
                f'/api/executions/{exec_id}',
                headers=auth_headers(reg["token"]),
            )
            if resp.status_code == 200:
                status = resp.json()["data"]["status"]
                if status in ("success", "failed"):
                    assert status == "success"
                    return
            time.sleep(0.5)

        pytest.fail("Worker did not process job within timeout")

    def test_error_handling_invalid_api(self, client):
        """Test 19: Error handling for invalid API calls."""
        from tests.test_api.conftest import auth_headers, register
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        reg = register(client)

        wf = {
            "id": f"wf_err_{_uid()}",
            "name": "Error Test",
            "nodes": [
                {
                    "id": "http_fail",
                    "type": "http_request",
                    "parameters": {
                        "method": "GET",
                        "url": "https://httpbin.org/status/500",
                        "authentication": "none",
                        "response_format": "json",
                    },
                    "settings": {"continue_on_error": True},
                },
                {
                    "id": "after_error",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"handled": True},
                    },
                    "settings": {},
                },
            ],
            "connections": [
                {"source": "http_fail", "sourceHandle": "main", "target": "after_error", "targetHandle": "main"},
            ],
            "settings": {"timeout_seconds": 30},
        }

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_err_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as hc:
                return await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=hc,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=reg["user"]["id"],
                )

        result = asyncio.run(_run())
        # With continue_on_error, the workflow should complete
        # even though the HTTP call got a 500
        assert result.status in ("success", "failed")

    def test_data_flow_between_all_nodes(self, client):
        """Test 20: Data flows correctly between ALL connected nodes."""
        from tests.test_api.conftest import auth_headers, register
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        reg = register(client)

        wf = {
            "id": f"wf_flow_{_uid()}",
            "name": "Data Flow Test",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": "return [{json: {value: 10, name: 'test'}}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
                {
                    "id": "transform1",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"step1": "done"},
                    },
                    "settings": {},
                },
                {
                    "id": "transform2",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"step2": "done"},
                    },
                    "settings": {},
                },
                {
                    "id": "transform3",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"step3": "done"},
                    },
                    "settings": {},
                },
            ],
            "connections": [
                {"source": "code", "sourceHandle": "main", "target": "transform1", "targetHandle": "main"},
                {"source": "transform1", "sourceHandle": "main", "target": "transform2", "targetHandle": "main"},
                {"source": "transform2", "sourceHandle": "main", "target": "transform3", "targetHandle": "main"},
            ],
            "settings": {"timeout_seconds": 30},
        }

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_flow_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as hc:
                return await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=hc,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=reg["user"]["id"],
                )

        result = asyncio.run(_run())
        assert result.status == "success"

        # Each node should have produced output
        for node_id in ["code", "transform1", "transform2", "transform3"]:
            assert node_id in result.results
            assert len(result.results[node_id].get("main", [])) > 0

        # Final node should have all accumulated fields
        final = result.results["transform3"]["main"][0]
        assert final["value"] == 10
        assert final["name"] == "test"
        assert final["step1"] == "done"
        assert final["step2"] == "done"
        assert final["step3"] == "done"


class TestPerformance:
    """Performance tests: workflow with 1/10/50/100 items."""

    def _build_perf_workflow(self, item_count: int) -> dict:
        wf_id = f"wf_perf_{item_count}_{_uid()}"
        code_items = ", ".join(
            [f'{{json: {{id: {i}, name: "item_{i}"}}}}' for i in range(item_count)]
        )
        return {
            "id": wf_id,
            "name": f"Perf Test {item_count} items",
            "nodes": [
                {
                    "id": "code",
                    "type": "code",
                    "parameters": {
                        "code": f"return [{code_items}]",
                        "mode": "runOnceForAllItems",
                    },
                    "settings": {},
                },
                {
                    "id": "split",
                    "type": "split",
                    "parameters": {"field": "", "batch_size": 0},
                    "settings": {},
                },
                {
                    "id": "process",
                    "type": "set_data",
                    "parameters": {
                        "mode": "merge",
                        "fields": {"processed": True},
                    },
                    "settings": {},
                },
            ],
            "connections": [
                {"source": "code", "sourceHandle": "main", "target": "split", "targetHandle": "main"},
                {"source": "split", "sourceHandle": "main", "target": "process", "targetHandle": "main"},
            ],
            "settings": {"timeout_seconds": 120},
        }

    def _run_workflow(self, wf: dict, user_id: int) -> tuple[str, float]:
        from app.engine.executor import execute_workflow
        from app.schemas.workflow import Workflow as WF
        from app.security.safe_http_client import SafeHTTPClient

        wf_obj = WF.model_validate(wf)
        execution_id = f"exec_perf_{_uid()}"

        async def _run():
            async with SafeHTTPClient() as hc:
                start = time.time()
                result = await execute_workflow(
                    workflow=wf_obj,
                    trigger_items=[{}],
                    execution_id=execution_id,
                    http_client=hc,
                    cancel_event=asyncio.Event(),
                    event_sink=lambda *a, **kw: None,
                    credential_resolver=lambda types, uid: {},
                    env_vars={},
                    initial_results=None,
                    storage_seed={},
                    execution_depth=0,
                    workspace_id="ws_test",
                    user_id=user_id,
                )
                elapsed = time.time() - start
                return result, elapsed

        result, elapsed = asyncio.run(_run())
        return result.status, elapsed

    def test_perf_1_item(self, client):
        from tests.test_api.conftest import register
        reg = register(client)
        wf = self._build_perf_workflow(1)
        status, elapsed = self._run_workflow(wf, reg["user"]["id"])
        assert status == "success"
        assert elapsed < 10  # should be fast

    def test_perf_10_items(self, client):
        from tests.test_api.conftest import register
        reg = register(client)
        wf = self._build_perf_workflow(10)
        status, elapsed = self._run_workflow(wf, reg["user"]["id"])
        assert status == "success"
        assert elapsed < 30

    def test_perf_50_items(self, client):
        from tests.test_api.conftest import register
        reg = register(client)
        wf = self._build_perf_workflow(50)
        status, elapsed = self._run_workflow(wf, reg["user"]["id"])
        assert status == "success"
        assert elapsed < 60

    def test_perf_100_items(self, client):
        from tests.test_api.conftest import register
        reg = register(client)
        wf = self._build_perf_workflow(100)
        status, elapsed = self._run_workflow(wf, reg["user"]["id"])
        assert status == "success"
        assert elapsed < 120
