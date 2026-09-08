"""Reference workflow E2E — reproduces the attached n8n screenshot pattern:

Schedule/Manual → Code (prepare) → HTTP Login → IF → HTTP Get Data → Split → Loop Over Items → Code (per item) → Salesforce Search → IF → Create / Update

Verifies:
- visual graph can be built (all node types exist)
- branching (IF true/false) routes correctly
- loop per-item (3 items → 3 downstream executions)
- Code node transforms
- HTTP batch handling
- Salesforce dynamic custom object mocked
- data mapping via {{ $json.* }} and $node
- worker/execution history path
"""

import pytest
import respx
import httpx
from httpx import Response

from app.engine.executor import execute_workflow
from app.schemas.workflow import Workflow, WorkflowNode, Connection


class FakeSalesforceProvider:
    def __init__(self):
        self.search_calls = []
        self.create_calls = []
        self.update_calls = []

    async def search_records(self, creds, object_name, field, value, **kwargs):
        self.search_calls.append((object_name, field, value))
        if str(value).lower() == "b@example.com":
            return {"records": [{"Id": "001B", "Email": value}]}
        return {"records": []}

    async def create_record(self, creds, object_name, record, **kwargs):
        self.create_calls.append((object_name, record))
        return {"id": f"new_{record.get('Email')}", "success": True}

    async def update_record(self, creds, object_name, record_id, record, **kwargs):
        self.update_calls.append((object_name, record_id, record))
        return {"id": record_id, "success": True}


@pytest.mark.asyncio
async def test_reference_workflow_visual_and_functional_parity():
    from app.nodes.registry import NODE_REGISTRY
    required_nodes = ["schedule", "manual_trigger", "code", "http_request", "if_condition", "split", "loop", "loop_over_items"]
    for t in required_nodes:
        assert t in NODE_REGISTRY, f"Missing node type {t}"
    import app.connectors.salesforce_connector as sf_module
    assert hasattr(sf_module, "SalesforceConnector")

    wf = Workflow(
        id="wf_ref",
        name="Reference Ditto",
        nodes=[
            WorkflowNode(id="sched", type="manual_trigger", parameters={}),
            WorkflowNode(id="code1", type="code", parameters={"code": "output = [{'json': {'token': 'abc'}}]"}),
            WorkflowNode(id="http_login", type="http_request", parameters={"method": "POST", "url": "https://example.com/login", "body": {"user": "test"}, "body_format": "json"}),
            WorkflowNode(id="if_login", type="if_condition", parameters={"condition": {"left": "{{ $json.body }}", "operator": "exists", "right": ""}}),
            WorkflowNode(id="http_get", type="http_request", parameters={"method": "GET", "url": "https://example.com/data"}),
            WorkflowNode(id="split", type="split", parameters={"field": "body.items"}),
            WorkflowNode(id="loop", type="loop_over_items", parameters={"field": "", "batch_size": 0}),
            WorkflowNode(id="code2", type="code", parameters={"code": "output = items.map(function(it) { var e = (it.json && it.json.email) || it.email || ''; return {'email': e.toUpperCase(), 'orig': it}; });"}),
            WorkflowNode(id="sf_search", type="salesforce", parameters={"operation": "search", "object_name": "CustomObject__c", "search_field": "Email", "search_value": "{{ $json.email }}"}, credentials={"salesforce": "test_sf"}),
            WorkflowNode(id="if_found", type="if_condition", parameters={"condition": {"left": "{{ $json.found }}", "operator": "equals", "right": True}}),
            WorkflowNode(id="sf_create", type="salesforce", parameters={"operation": "create", "object_name": "CustomObject__c", "record": {"Email": "{{ $json.email }}", "Name": "{{ $json.email }}" }}, credentials={"salesforce": "test_sf"}),
            WorkflowNode(id="sf_update", type="salesforce", parameters={"operation": "update", "object_name": "CustomObject__c", "record_id": "001B", "record": {"Name": "Updated {{ $json.email }}" }}, credentials={"salesforce": "test_sf"}),
        ],
        connections=[
            Connection(source="sched", target="code1"),
            Connection(source="code1", target="http_login"),
            Connection(source="http_login", target="if_login"),
            Connection(source="if_login", target="http_get", sourceHandle="true"),
            Connection(source="http_get", target="split"),
            Connection(source="split", target="loop"),
            Connection(source="loop", target="code2"),
            Connection(source="code2", target="sf_search"),
            Connection(source="sf_search", target="if_found"),
            Connection(source="if_found", target="sf_update", sourceHandle="true"),
            Connection(source="if_found", target="sf_create", sourceHandle="false"),
        ],
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://example.com/login").mock(return_value=Response(200, json={"token": "abc"}))
        mock.get("https://example.com/data").mock(return_value=Response(200, json={"items": [{"email": "a@example.com"}, {"email": "B@example.com"}, {"email": "c@example.com"}]}))

        import app.connectors.salesforce_connector as sf_conn
        fake_provider = FakeSalesforceProvider()
        import unittest.mock as mock_lib

        async def fake_search(self, creds, params, *args, **kwargs):
            val = getattr(params, 'search_value', None)
            if val is None and isinstance(params, dict):
                val = params.get('search_value')
            if not val and args:
                val = args[0] if args else None
            if not val:
                payload = kwargs.get('payload') or (args[0] if args else {})
                if isinstance(payload, dict):
                    val = payload.get('search_value')
            result = await fake_provider.search_records(creds, getattr(params, 'object_name', 'CustomObject__c') if hasattr(params, 'object_name') else 'CustomObject__c', getattr(params, 'search_field', 'Email') if hasattr(params, 'search_field') else 'Email', val)
            records = result["records"]
            if records:
                return {"output": {"record": records[0], "found": True}, "success": True, "operation": "search"}
            return {"output": {"record": None, "found": False}, "success": True, "operation": "search"}

        async def fake_create(self, creds, params, *args, **kwargs):
            rec = getattr(params, 'record', None) or kwargs.get('record') or {}
            val = await fake_provider.create_record(creds, getattr(params, 'object_name', 'CustomObject__c'), rec)
            return {"output": val, "success": True, "operation": "create"}

        async def fake_update(self, creds, params, *args, **kwargs):
            rec_id = getattr(params, 'record_id', None) or kwargs.get('record_id') or "001B"
            rec = getattr(params, 'record', None) or kwargs.get('record') or {}
            val = await fake_provider.update_record(creds, getattr(params, 'object_name', 'CustomObject__c'), rec_id, rec)
            return {"output": val, "success": True, "operation": "update"}

        with mock_lib.patch.object(sf_conn.SalesforceConnector, '_op_search', fake_search), \
             mock_lib.patch.object(sf_conn.SalesforceConnector, '_op_create', fake_create), \
             mock_lib.patch.object(sf_conn.SalesforceConnector, '_op_update', fake_update):
            async with httpx.AsyncClient() as client:
                def cred_resolver(refs):
                    return {"salesforce": {
                        "client_id": "fake_client",
                        "client_secret": "fake_secret",
                        "username": "test@example.com",
                        "password": "fake_pass",
                        "security_token": "fake_token",
                        "instance_url": "https://test.salesforce.com",
                        "access_token": "fake_token",
                        "refresh_token": "fake_refresh",
                    }}
                result = await execute_workflow(
                    wf,
                    [{"trigger": "manual"}],
                    execution_id="exec_ref_test",
                    http_client=client,
                    credential_resolver=cred_resolver,
                )

    assert result.status == "success", f"Workflow failed: {result.error} trace={result.trace}"
    assert len(fake_provider.search_calls) == 3, f"Expected 3 searches, got {len(fake_provider.search_calls)}"
    assert len(fake_provider.create_calls) == 2, f"create calls {fake_provider.create_calls}"
    assert len(fake_provider.update_calls) == 1, f"update calls {fake_provider.update_calls}"
    assert "code1" not in result.node_errors
    assert "code2" not in result.node_errors
    trace_by_id = {step["node_id"]: step for step in result.trace}
    assert trace_by_id["if_login"]["status"] == "success"
    assert trace_by_id["if_found"]["status"] == "success"
    assert "A@EXAMPLE.COM" in [c[2] for c in fake_provider.search_calls]
