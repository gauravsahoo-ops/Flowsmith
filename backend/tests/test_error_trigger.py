"""Tests for ErrorTriggerNode and error workflow integration."""

import pytest
from app.nodes.registry import NODE_REGISTRY
from app.engine.executor import execute_workflow
from app.importexport import parse_import
from tests.conftest import make_workflow, make_node, conn


def test_error_trigger_registered():
    assert "error_trigger" in NODE_REGISTRY
    cls = NODE_REGISTRY["error_trigger"]
    assert cls.display_name == "Error Trigger"
    assert cls.category == "Triggers"
    assert cls.input_handles == []


@pytest.mark.asyncio
async def test_error_trigger_standalone_produces_mock_items():
    """When tested without inputs (e.g. single-step canvas testing), outputs mock failure context."""
    wf = make_workflow(
        [make_node("err_trig", "error_trigger")],
        [],
    )
    res = await execute_workflow(wf, trigger_items=[])
    assert res.status == "success"
    outputs = res.results["err_trig"]["main"]
    assert len(outputs) == 1
    assert "error" in outputs[0]
    assert "failed_execution_id" in outputs[0]
    assert "failed_workflow_id" in outputs[0]


@pytest.mark.asyncio
async def test_error_trigger_passes_live_error_context():
    """When the error runtime passes trigger_items, error_trigger emits that exact context."""
    wf = make_workflow(
        [
            make_node("err_trig", "error_trigger"),
            make_node("setter", "set_data", parameters={"fields": {"handled": True}}),
        ],
        [conn("err_trig", "setter")],
    )
    live_payload = [{
        "error": {"message": "Database timeout", "code": "TIMEOUT", "node_id": "db_query"},
        "failed_execution_id": "exec_prod_999",
        "failed_workflow_id": "wf_order_sync",
    }]
    res = await execute_workflow(wf, trigger_items=live_payload)
    assert res.status == "success"
    trigger_out = res.results["err_trig"]["main"]
    assert trigger_out[0]["error"]["message"] == "Database timeout"
    assert trigger_out[0]["failed_execution_id"] == "exec_prod_999"

    setter_out = res.results["setter"]["main"]
    assert setter_out[0]["handled"] is True


def test_error_trigger_external_import():
    data = {
        "name": "External Error Handler",
        "nodes": [
            {
                "id": "node_1",
                "name": "Error Trigger",
                "type": "errorTrigger",
                "typeVersion": 1,
                "position": [250, 300],
                "parameters": {},
            }
        ],
        "connections": {},
    }
    imported = parse_import(data)
    assert len(imported["nodes"]) == 1
    assert imported["nodes"][0]["type"] == "error_trigger"
