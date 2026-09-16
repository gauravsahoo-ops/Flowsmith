"""Stress / concurrency + additional node coverage tests."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
import uuid
from typing import Any

import httpx
import pytest

from app.engine.executor import execute_workflow
from app.engine.expressions import build_context, resolve
from app.engine.node_base import MemoryKVStore, NodeContext, NodeResult
from app.nodes.aggregate import AggregateNode
from app.nodes.code import CodeNode
from app.nodes.csv_json_transform import CsvJsonTransformNode
from app.nodes.filter import FilterNode
from app.nodes.loop_while import LoopWhileNode
from app.nodes.manual_trigger import ManualTriggerNode
from app.nodes.merge import MergeNode
from app.nodes.pagination import PaginationNode
from app.nodes.set_data import SetDataNode
from app.nodes.switch import SwitchNode
from app.nodes.wait import WaitNode
from app.nodes.webhook import WebhookTriggerNode
from app.schemas.workflow import Connection, Workflow, WorkflowNode
from tests.conftest import conn, make_node, make_workflow


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ctx(node_id: str = "n1") -> NodeContext:
    return NodeContext(
        execution_id=f"exec_{uuid.uuid4().hex[:8]}",
        workflow_id="wf_test",
        node_id=node_id,
        logger=__import__("logging").getLogger("test"),
        http_client=httpx.AsyncClient(),
    )


def _code_workflow(wf_id: str = "wf_code", code: str = "return $input.all();") -> Workflow:
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("code1", "code", parameters={"code": code, "language": "javascript"}),
        ],
        [conn("trigger", "code1")],
        wf_id=wf_id,
    )


# ===========================================================================
# STRESS / CONCURRENCY
# ===========================================================================


@pytest.mark.asyncio
async def test_concurrent_10_workflows_with_code_node():
    """Run 10 workflows concurrently, each with a Code node."""
    workflows = [_code_workflow(wf_id=f"wf_{i}") for i in range(10)]
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[execute_workflow(wf, http_client=client) for wf in workflows]
        )
    assert all(r.status == "success" for r in results)
    assert all(r.results.get("code1", {}).get("main") is not None for r in results)


@pytest.mark.asyncio
async def test_sequential_50_executions_same_workflow():
    """Run the same workflow 50 times sequentially."""
    wf = _code_workflow(wf_id="wf_seq50")
    async with httpx.AsyncClient() as client:
        for i in range(50):
            result = await execute_workflow(wf, execution_id=f"seq_{i}", http_client=client)
            assert result.status == "success"
            assert result.results["code1"]["main"] == [{}]


@pytest.mark.asyncio
async def test_5_different_workflows_simultaneously():
    """Run 5 distinct workflow shapes at the same time."""
    wf_a = _code_workflow("wf_a", "return [{json: {v: 1}}];")
    wf_b = _code_workflow("wf_b", "return [{json: {v: 2}}];")
    wf_c = _code_workflow("wf_c", "return [{json: {v: 3}}];")
    wf_d = _code_workflow("wf_d", "return [{json: {v: 4}}];")
    wf_e = _code_workflow("wf_e", "return [{json: {v: 5}}];")
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            execute_workflow(wf_a, http_client=client),
            execute_workflow(wf_b, http_client=client),
            execute_workflow(wf_c, http_client=client),
            execute_workflow(wf_d, http_client=client),
            execute_workflow(wf_e, http_client=client),
        )
    assert all(r.status == "success" for r in results)


@pytest.mark.asyncio
async def test_expression_engine_1000_items():
    """Resolve expressions across 1000 items."""
    items = [{"i": i, "name": f"item_{i}"} for i in range(1000)]
    ctx = build_context(items, {}, "wf_test", "exec_test")
    for item in items:
        ctx["$json"] = item
        result = resolve("{{ $json.name }}", ctx)
        assert result == item["name"]
        result2 = resolve("{{ $json.i + 1 }}", ctx)
        assert result2 == item["i"] + 1


# ===========================================================================
# NODE COVERAGE — Switch
# ===========================================================================


@pytest.mark.asyncio
async def test_switch_node_routes_to_correct_handle():
    """Switch routes item to route_1 when condition matches."""
    node = SwitchNode()
    params = node.build_params({
        "rules": [
            {"left": "$json.type", "operator": "equals", "right": "B", "output": "route_1"},
            {"left": "$json.type", "operator": "equals", "right": "A", "output": "route_0"},
        ]
    })
    items = [{"type": "A"}, {"type": "B"}, {"type": "C"}]
    result = await node.run(_ctx(), params, items)
    assert result.output_by_handle is not None
    assert result.items_for("route_0") == [{"type": "A"}]
    assert result.items_for("route_1") == [{"type": "B"}]
    assert result.items_for("default") == [{"type": "C"}]


# ===========================================================================
# NODE COVERAGE — Merge
# ===========================================================================


@pytest.mark.asyncio
async def test_merge_node_concat_mode():
    """Merge concat flattens all items."""
    node = MergeNode()
    params = node.build_params({"strategy": "concat"})
    items = [{"a": 1}, {"b": 2}, {"c": 3}]
    result = await node.run(_ctx(), params, items)
    assert result.output_items == [{"a": 1}, {"b": 2}, {"c": 3}]


@pytest.mark.asyncio
async def test_merge_node_keep_first_mode():
    """Merge keep_first discards all but the first item."""
    node = MergeNode()
    params = node.build_params({"strategy": "keep_first"})
    items = [{"a": 1}, {"b": 2}, {"c": 3}]
    result = await node.run(_ctx(), params, items)
    assert len(result.output_items) == 1
    assert result.output_items[0] == {"a": 1}


# ===========================================================================
# NODE COVERAGE — Aggregate
# ===========================================================================


@pytest.mark.asyncio
async def test_aggregate_node_collects_into_list():
    """Aggregate collects all items into a single list."""
    node = AggregateNode()
    params = node.build_params({"field": "rows"})
    items = [{"id": 1}, {"id": 2}, {"id": 3}]
    result = await node.run(_ctx(), params, items)
    assert len(result.output_items) == 1
    assert result.output_items[0]["rows"] == [{"id": 1}, {"id": 2}, {"id": 3}]


# ===========================================================================
# NODE COVERAGE — Set Data
# ===========================================================================


@pytest.mark.asyncio
async def test_set_data_node_merge_mode():
    """Set Data merge keeps existing fields and adds new ones."""
    node = SetDataNode()
    params = node.build_params({"mode": "merge", "fields": {"extra": 42}})
    items = [{"existing": "value"}]
    result = await node.run(_ctx(), params, items)
    assert result.output_items[0] == {"existing": "value", "extra": 42}


@pytest.mark.asyncio
async def test_set_data_node_replace_mode():
    """Set Data replace overwrites all fields."""
    node = SetDataNode()
    params = node.build_params({"mode": "replace", "fields": {"only": True}})
    items = [{"old": "data", "keep": False}]
    result = await node.run(_ctx(), params, items)
    assert result.output_items[0] == {"only": True}
    assert "old" not in result.output_items[0]


# ===========================================================================
# NODE COVERAGE — Filter
# ===========================================================================


@pytest.mark.asyncio
async def test_filter_node_keeps_matching_items():
    """Filter keeps items matching the condition."""
    node = FilterNode()
    params = node.build_params({
        "condition": {"left": "$json.active", "operator": "is true", "right": None}
    })
    items = [
        {"active": True, "name": "a"},
        {"active": False, "name": "b"},
        {"active": True, "name": "c"},
    ]
    result = await node.run(_ctx(), params, items)
    kept = result.output_items
    assert len(kept) == 2
    assert all(it["active"] is True for it in kept)


# ===========================================================================
# NODE COVERAGE — LoopWhile
# ===========================================================================


@pytest.mark.asyncio
async def test_loop_while_node_runs_until_condition():
    """LoopWhile increments counter until target is reached."""
    node = LoopWhileNode()
    ctx = _ctx()
    ctx.expression_context = {}
    params = node.build_params({
        "condition": {"left": "$json.counter", "operator": "is greater than or equal to", "right": 5},
        "mode": "until",
        "update": {"counter": "{{ $json.counter + 1 }}"},
        "max_iterations": 10,
        "delay_seconds": 0.0,
    })
    items = [{"counter": 0}]
    result = await node.run(ctx, params, items)
    assert result.output_items[0]["counter"] == 5
    assert result.metadata.get("iterations") == 6


# ===========================================================================
# NODE COVERAGE — Pagination
# ===========================================================================


@pytest.mark.asyncio
async def test_pagination_node_splits_into_pages():
    """Pagination splits items into correct pages."""
    node = PaginationNode()
    params = node.build_params({"page_size": 3, "field": ""})
    items = [{"i": i} for i in range(10)]
    result = await node.run(_ctx(), params, items)
    assert len(result.output_items) == 4
    assert result.output_items[0]["page_index"] == 0
    assert result.output_items[0]["item_count"] == 3
    assert result.output_items[3]["item_count"] == 1
    assert result.output_items[0]["total_pages"] == 4


# ===========================================================================
# NODE COVERAGE — CSV/JSON Transform
# ===========================================================================


@pytest.mark.asyncio
async def test_csv_json_transform_json_to_csv():
    """json-to-csv converts list of dicts to CSV string."""
    node = CsvJsonTransformNode()
    params = node.build_params({"mode": "json-to-csv", "include_header": True})
    items = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    result = await node.run(_ctx(), params, items)
    csv_str = result.output_items[0]["csv"]
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["name"] == "Alice"
    assert rows[1]["age"] == "25"


@pytest.mark.asyncio
async def test_csv_json_transform_csv_to_json():
    """csv-to-json parses CSV string into list of dicts."""
    node = CsvJsonTransformNode()
    csv_data = "name,age\nAlice,30\nBob,25\n"
    params = node.build_params({"mode": "csv-to-json", "csv_input": csv_data})
    result = await node.run(_ctx(), params, [])
    rows = result.output_items[0]["json"]
    assert len(rows) == 2
    assert rows[0]["name"] == "Alice"
    assert rows[1]["age"] == "25"


@pytest.mark.asyncio
async def test_csv_json_transform_json_pretty():
    """json-pretty pretty-prints JSON."""
    node = CsvJsonTransformNode()
    data = {"name": "Alice", "scores": [1, 2, 3]}
    params = node.build_params({"mode": "json-pretty", "json_input": data})
    result = await node.run(_ctx(), params, [])
    pretty = result.output_items[0]["json"]
    assert "Alice" in pretty
    parsed_back = json.loads(pretty)
    assert parsed_back["scores"] == [1, 2, 3]


# ===========================================================================
# NODE COVERAGE — Wait
# ===========================================================================


@pytest.mark.asyncio
async def test_wait_node_delay_short():
    """Wait node delays for a short period."""
    node = WaitNode()
    params = node.build_params({"mode": "delay", "seconds": 0.5})
    items = [{"before": True}]
    started = time.monotonic()
    result = await node.run(_ctx(), params, items)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.4
    assert result.output_items == [{"before": True}]


# ===========================================================================
# NODE COVERAGE — Webhook
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_node_normalizes_payload():
    """Webhook normalizes raw payload into {body, headers, query, params}."""
    node = WebhookTriggerNode()
    params = node.build_params({"path": "test-hook", "method": "POST"})
    result = await node.run(_ctx(), params, [{"data": "hello"}])
    assert result.output_items[0]["body"] == {"data": "hello"}
    assert result.output_items[0]["headers"] == {}


# ===========================================================================
# NODE COVERAGE — Manual Trigger
# ===========================================================================


@pytest.mark.asyncio
async def test_manual_trigger_node_passthrough():
    """Manual Trigger passes through input items or emits [{}]."""
    node = ManualTriggerNode()
    params = node.build_params({})
    result = await node.run(_ctx(), params, [{"key": "val"}])
    assert result.output_items == [{"key": "val"}]

    result2 = await node.run(_ctx(), params, [])
    assert result2.output_items in ([{}], [{"success": True}])
