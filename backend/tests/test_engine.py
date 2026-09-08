"""Engine tests --- THE most important file (spec 14, 51.1)."""

from __future__ import annotations

import asyncio

import pytest
import respx
import httpx

from app.engine.executor import execute_workflow
from tests.conftest import conn, make_node, make_workflow


async def test_simple_chain():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("set", "set_data", parameters={"fields": {"greeting": "hello"}}),
        ],
        [conn("trigger", "set")],
    )
    result = await execute_workflow(wf, [{"name": "world"}])
    assert result.status == "success"
    assert result.results["set"]["main"] == [{"name": "world", "greeting": "hello"}]
    assert result.skipped == []


async def test_http_request_chain(respx_mock):
    respx_mock.get("https://api.example.com/data").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("http", "http_request", parameters={"method": "GET", "url": "https://api.example.com/data"}),
        ],
        [conn("trigger", "http")],
    )
    result = await execute_workflow(wf)
    assert result.status == "success"
    http_out = result.results["http"]["main"][0]
    assert http_out["status"] == 200
    assert http_out["ok"] is True


async def test_branching_true_route():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("if", "if_condition", parameters={
                "condition": {"left": "{{ $json.subject }}", "operator": "contains", "right": "urgent"}
            }),
            make_node("slack", "slack"),
            make_node("db", "db"),
        ],
        [
            conn("trigger", "if"),
            conn("if", "slack", source_handle="true"),
            conn("if", "db", source_handle="false"),
        ],
    )
    result = await execute_workflow(wf, [{"subject": "urgent: please fix"}])
    assert result.status == "success"
    assert "slack" in result.results
    assert "db" not in result.results
    assert result.results["slack"]["main"][0]["sent_via"] == "slack"
    assert "db" in result.skipped


async def test_branching_false_route():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("if", "if_condition", parameters={
                "condition": {"left": "{{ $json.subject }}", "operator": "contains", "right": "urgent"}
            }),
            make_node("slack", "slack"),
            make_node("db", "db"),
        ],
        [
            conn("trigger", "if"),
            conn("if", "slack", source_handle="true"),
            conn("if", "db", source_handle="false"),
        ],
    )
    result = await execute_workflow(wf, [{"subject": "weekly report"}])
    assert result.status == "success"
    assert "db" in result.results
    assert "slack" not in result.results
    assert "slack" in result.skipped


async def test_error_stops_downstream():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("boom", "boom"),
            make_node("set", "set_data", parameters={"fields": {"x": 1}}),
        ],
        [conn("trigger", "boom"), conn("boom", "set")],
    )
    result = await execute_workflow(wf)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "NODE_ERROR"
    assert result.error.node_id == "boom"
    assert "set" not in result.results
    assert "set" in result.skipped


async def test_continue_on_error_passes_error_item():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("boom", "boom", settings={"continue_on_error": True}),
            make_node("set", "set_data", parameters={"fields": {"noted": True}}),
        ],
        [conn("trigger", "boom"), conn("boom", "set")],
    )
    result = await execute_workflow(wf)
    assert result.status == "success"
    error_item = result.results["set"]["main"][0]
    assert error_item["noted"] is True
    assert error_item["$error"]["node_id"] == "boom"


async def test_expressions_resolve_from_input_and_nodes():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("set", "set_data", parameters={
                "fields": {
                    "subject": "{{ $json.subject }}",
                    "from_node": "{{ $node.trigger.json.name }}",
                }
            }),
        ],
        [conn("trigger", "set")],
    )
    result = await execute_workflow(wf, [{"subject": "urgent!", "name": "Alice"}])
    assert result.status == "success"
    out = result.results["set"]["main"][0]
    assert out["subject"] == "urgent!"
    assert out["from_node"] == "Alice"


async def test_two_parents_merge_items():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("a", "set_data", parameters={"fields": {"a": 1}}),
            make_node("b", "set_data", parameters={"fields": {"b": 2}}),
            make_node("c", "set_data", parameters={"fields": {"c": 3}}),
        ],
        [conn("trigger", "a"), conn("trigger", "b"), conn("a", "c"), conn("b", "c")],
    )
    result = await execute_workflow(wf)
    assert result.status == "success"
    c_items = result.results["c"]["main"]
    assert {"a": 1, "c": 3} in c_items
    assert {"b": 2, "c": 3} in c_items


async def test_node_timeout():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow", "slow", settings={"timeout_seconds": 0.05}),
        ],
        [conn("trigger", "slow")],
    )
    result = await execute_workflow(wf)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "NODE_TIMEOUT"
    assert result.error.retryable is True


async def test_external_task_cancellation():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow", "slow"),
        ],
        [conn("trigger", "slow")],
    )
    task = asyncio.create_task(execute_workflow(wf))
    await asyncio.sleep(0.05)
    task.cancel()
    result = await task
    assert result.status == "cancelled"


async def test_unresolved_expression_kept_intact():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("set", "set_data", parameters={"fields": {"missing": "{{ $json.nope }}"}}),
        ],
        [conn("trigger", "set")],
    )
    result = await execute_workflow(wf, [{"x": 1}])
    assert result.status == "success"
    assert result.results["set"]["main"][0]["missing"] == "{{ $json.nope }}"


async def test_multiple_trigger_items_flow_through():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("set", "set_data", parameters={"fields": {"seen": True}}),
        ],
        [conn("trigger", "set")],
    )
    result = await execute_workflow(wf, [{"n": 1}, {"n": 2}])
    assert result.status == "success"
    assert result.results["set"]["main"] == [{"n": 1, "seen": True}, {"n": 2, "seen": True}]


async def test_split_out_empty_array_stops_downstream_flow():
    """When Split Out receives an empty list, it outputs 0 items and downstream nodes are skipped."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("split", "split", parameters={"fieldToSplitOut": "items"}),
            make_node("loop", "loop_over_items"),
            make_node("action", "set_data", parameters={"fields": {"executed": True}}),
        ],
        [conn("trigger", "split"), conn("split", "loop"), conn("loop", "action")],
    )
    # Payload has empty array for 'items'
    result = await execute_workflow(wf, [{"items": []}])
    assert result.status == "success"
    # Split Out produces empty list (0 items)
    assert result.results["split"]["main"] == []
    # Both downstream nodes must be skipped
    assert "loop" in result.skipped
    assert "action" in result.skipped
    assert "loop" not in result.results
    assert "action" not in result.results


async def test_split_out_always_output_data_flows_downstream():
    """When Split Out has alwaysOutputData: true, an empty input outputs [{}] and downstream nodes run."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("split", "split", parameters={"fieldToSplitOut": "items", "options": {"alwaysOutputData": True}}),
            make_node("action", "set_data", parameters={"fields": {"executed": True}}),
        ],
        [conn("trigger", "split"), conn("split", "action")],
    )
    result = await execute_workflow(wf, [{"items": []}])
    assert result.status == "success"
    assert result.results["split"]["main"] == [{}]
    assert "action" in result.results
    assert result.results["action"]["main"] == [{"executed": True}]

