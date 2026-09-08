"""Execution engine audit — comprehensive integration tests.

Covers 12 workflow patterns end-to-end through execute_workflow():
 1. LINEAR       A -> B -> C
 2. BRANCH       A -> IF -> TRUE / FALSE
 3. MERGE        A -> C, B -> C  (two parents)
 4. LOOP         A -> Split -> Process (loop body) -> aggregate
 5. PARALLEL     A -> [B, C] -> D
 6. SKIPPED      A -> B (fails) -> C (skipped)
 7. CONTINUE_ON_ERROR  A -> B (fails, continue) -> C (sees $error)
 8. EXPRESSION   A -> B ($json) -> C ($node)
 9. MULTI-ITEM   A (3 items) -> B (per-item)
10. EMPTY INPUT  A (0 items) -> B (skipped)
11. TIMEOUT      workflow timeout kills a sleeping node
12. CANCELLATION cancel mid-execution
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
import pytest

from app.engine.executor import ExecutionResult, execute_workflow
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.engine.errors import NodeExecutionError, NodeCancelledError
from app.nodes.registry import register
from tests.conftest import conn, make_node, make_workflow


# ── helpers ──────────────────────────────────────────────────────────────────


class _PassThroughNode(BaseNode):
    """Echoes input_items as output (no-op transform)."""

    node_type = "pass_through"
    display_name = "Pass Through"
    version = 1
    output_handles = ["main"]
    input_handles = ["main"]

    async def run(self, ctx, params, input_items):
        return NodeResult(output_items=input_items)


class _AppendFieldNode(BaseNode):
    """Adds a fixed field to every input item."""

    node_type = "append_field"
    display_name = "Append Field"
    version = 1
    output_handles = ["main"]
    input_handles = ["main"]

    async def run(self, ctx, params, input_items):
        key = params.get("key", "extra")
        value = params.get("value", "ok")
        return NodeResult(output_items=[{**item, key: value} for item in input_items])


class _EmptyOutputNode(BaseNode):
    """Produces zero output items."""

    node_type = "empty_output"
    display_name = "Empty Output"
    version = 1
    output_handles = ["main"]
    input_handles = ["main"]

    async def run(self, ctx, params, input_items):
        return NodeResult(output_items=[])


class _CancellableSleepNode(BaseNode):
    """Sleeps for N seconds, polling cancel_event every 0.1s."""

    node_type = "cancellable_sleep"
    display_name = "Cancellable Sleep"
    version = 1
    output_handles = ["main"]
    input_handles = ["main"]

    async def run(self, ctx, params, input_items):
        import pydantic as _pydantic

        class SleepParams(_pydantic.BaseModel):
            seconds: float = 5.0

        p = SleepParams.model_validate(params if isinstance(params, dict) else {})
        total = p.seconds
        elapsed = 0.0
        step = 0.1
        while elapsed < total:
            await asyncio.sleep(step)
            elapsed += step
            if ctx.is_cancelled():
                raise NodeCancelledError(ctx.node_id)
        return NodeResult(output_items=input_items)


# Register custom nodes so validate_graph / NODE_REGISTRY picks them up.
register(_PassThroughNode)
register(_AppendFieldNode)
register(_EmptyOutputNode)
register(_CancellableSleepNode)


# ── 1. LINEAR: A -> B -> C ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_linear_a_to_b_to_c():
    """Three set_data nodes chain data: A sets x, B sets y, C reads both."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"x": 1}}),
            make_node("B", "set_data", parameters={"fields": {"y": 2}}),
            make_node("C", "set_data", parameters={"fields": {"z": "done"}}),
        ],
        [conn("trigger", "A"), conn("A", "B"), conn("B", "C")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    c_items = result.results["C"]["main"]
    assert len(c_items) == 1
    assert c_items[0]["x"] == 1
    assert c_items[0]["y"] == 2
    assert c_items[0]["z"] == "done"
    node_ids = [s["node_id"] for s in result.trace]
    assert "trigger" in node_ids
    assert "A" in node_ids
    assert "B" in node_ids
    assert "C" in node_ids


# ── 2. BRANCH: A -> IF -> TRUE / FALSE ──────────────────────────────────────


@pytest.mark.asyncio
async def test_branch_if_true_and_false():
    """IF node routes items to true/false based on a condition."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"val": 10}}),
            make_node(
                "IF",
                "if_condition",
                parameters={
                    "conditions": [
                        {
                            "id": "c1",
                            "left": "{{ $json.val }}",
                            "operator": "is greater than",
                            "right": 5,
                            "combinator": "AND",
                        }
                    ]
                },
            ),
            make_node("TRUE_PATH", "set_data", parameters={"fields": {"branch": "true"}}),
            make_node("FALSE_PATH", "set_data", parameters={"fields": {"branch": "false"}}),
        ],
        [
            conn("trigger", "A"),
            conn("A", "IF"),
            conn("IF", "TRUE_PATH", source_handle="true"),
            conn("IF", "FALSE_PATH", source_handle="false"),
        ],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    assert result.results["TRUE_PATH"]["main"][0]["branch"] == "true"
    assert "FALSE_PATH" in result.skipped


# ── 3. MERGE: A -> C, B -> C ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_two_parents():
    """Two branches feed into one merge node; both items arrive."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"from": "A"}}),
            make_node("B", "set_data", parameters={"fields": {"from": "B"}}),
            make_node("merge", "merge", parameters={"strategy": "concat"}),
        ],
        [
            conn("trigger", "A"),
            conn("trigger", "B"),
            conn("A", "merge"),
            conn("B", "merge"),
        ],
    )
    result = await execute_workflow(wf, [{"src": "trigger"}])

    assert result.status == "success"
    items = result.results["merge"]["main"]
    assert len(items) == 2
    from_values = {item["from"] for item in items}
    assert from_values == {"A", "B"}


# ── 4. LOOP: A -> Split -> Process -> Aggregate ─────────────────────────────


@pytest.mark.asyncio
async def test_loop_split_and_aggregate():
    """Split fans out 3 items, a node processes each, aggregate recombines."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"items": [{"v": 1}, {"v": 2}, {"v": 3}]}}),
            make_node("split", "split", parameters={"field": "items"}),
            make_node("process", "set_data", parameters={"fields": {"processed": True}}),
            make_node("agg", "aggregate", parameters={"field": "collected"}),
        ],
        [
            conn("trigger", "A"),
            conn("A", "split"),
            conn("split", "process"),
            conn("process", "agg"),
        ],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    proc_items = result.results["process"]["main"]
    assert len(proc_items) == 3
    assert all(item["processed"] is True for item in proc_items)
    agg_items = result.results["agg"]["main"]
    assert len(agg_items) == 1
    assert len(agg_items[0]["collected"]) == 3


# ── 5. PARALLEL BRANCHES: A -> [B, C] -> D ──────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_branches():
    """A fans into B and C (both run), then D waits for both.

    D receives one item from B and one from C (2 total) because set_data
    is a non-resolving node that merges fields onto each input item.
    """
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"seed": True}}),
            make_node("B", "set_data", parameters={"fields": {"from_b": 1}}),
            make_node("C", "set_data", parameters={"fields": {"from_c": 2}}),
            make_node(
                "D",
                "set_data",
                parameters={
                    "fields": {"combined": "{{ $node.B.json.from_b + $node.C.json.from_c }}"}
                },
            ),
        ],
        [
            conn("trigger", "A"),
            conn("A", "B"),
            conn("A", "C"),
            conn("B", "D"),
            conn("C", "D"),
        ],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    d_items = result.results["D"]["main"]
    assert len(d_items) == 2
    # Both items get combined = 1 + 2 = 3
    assert all(item["combined"] == 3 for item in d_items)
    # One from B's branch, one from C's branch
    from_values = {(item.get("from_b"), item.get("from_c")) for item in d_items}
    assert (1, None) in from_values
    assert (None, 2) in from_values


# ── 6. SKIPPED NODE: A -> B (fails) -> C ────────────────────────────────────


@pytest.mark.asyncio
async def test_skipped_node_on_failure():
    """When B fails, C is skipped; overall status is failed."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"ok": True}}),
            make_node("B", "boom"),
            make_node("C", "set_data", parameters={"fields": {"should_not_run": True}}),
        ],
        [conn("trigger", "A"), conn("A", "B"), conn("B", "C")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "failed"
    assert result.error is not None
    assert "kaboom" in str(result.error.message)
    assert "C" in result.skipped


# ── 7. CONTINUE_ON_ERROR: A -> B (fails, continue) -> C ────────────────────


@pytest.mark.asyncio
async def test_continue_on_error_propagates_error_item():
    """B fails but continue_on_error=true; C receives the $error item."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"val": 42}}),
            make_node("B", "boom", settings={"continue_on_error": True}),
            make_node("C", "set_data", parameters={"fields": {"checked": True}}),
        ],
        [conn("trigger", "A"), conn("A", "B"), conn("B", "C")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    b_items = result.results["B"]["main"]
    assert len(b_items) == 1
    assert "$error" in b_items[0]
    c_items = result.results["C"]["main"]
    assert len(c_items) == 1
    assert c_items[0]["checked"] is True
    b_step = next(s for s in result.trace if s["node_id"] == "B")
    assert b_step["status"] == "error"


# ── 8. EXPRESSION CHAIN: $json then $node ───────────────────────────────────


@pytest.mark.asyncio
async def test_expression_chain_json_then_node():
    """A produces data; B reads $json.field from A; C reads $node.A.json.field."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "A",
                "set_data",
                parameters={"fields": {"name": "Alice", "score": 100}},
            ),
            make_node(
                "B",
                "set_data",
                parameters={
                    "fields": {
                        "upper_name": "{{ $json.name | upper }}",
                        "doubled": "{{ $json.score * 2 }}",
                    }
                },
            ),
            make_node(
                "C",
                "set_data",
                parameters={
                    "fields": {
                        "original_name": "{{ $node.A.json.name }}",
                        "original_score": "{{ $node.A.json.score }}",
                    }
                },
            ),
        ],
        [conn("trigger", "A"), conn("A", "B"), conn("B", "C")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    b_items = result.results["B"]["main"]
    assert b_items[0]["upper_name"] == "ALICE"
    assert b_items[0]["doubled"] == 200

    c_items = result.results["C"]["main"]
    assert c_items[0]["original_name"] == "Alice"
    assert c_items[0]["original_score"] == 100


# ── 9. MULTI-ITEM: A produces 3 items -> B processes each ───────────────────


@pytest.mark.asyncio
async def test_multi_item_per_item_processing():
    """A produces 3 items; B processes each individually."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"data": [{"i": 1}, {"i": 2}, {"i": 3}]}}),
            make_node("split", "split", parameters={"field": "data"}),
            make_node("B", "set_data", parameters={"fields": {"processed": True}}),
        ],
        [conn("trigger", "A"), conn("A", "split"), conn("split", "B")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    b_items = result.results["B"]["main"]
    assert len(b_items) == 3
    assert all(item["processed"] is True for item in b_items)
    i_values = {item["i"] for item in b_items}
    assert i_values == {1, 2, 3}


# ── 10. EMPTY INPUT: A produces 0 items -> B skipped ────────────────────────


@pytest.mark.asyncio
async def test_empty_input_skips_downstream():
    """A produces zero items; B (connected) is skipped because no input arrives."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "empty_output"),
            make_node("B", "set_data", parameters={"fields": {"should_not_run": True}}),
        ],
        [conn("trigger", "A"), conn("A", "B")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert "B" in result.skipped


# ── 11. WORKFLOW TIMEOUT ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_timeout():
    """A workflow-level timeout kills a node that sleeps too long."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow", "cancellable_sleep", parameters={"seconds": 5}),
        ],
        [conn("trigger", "slow")],
        wf_id="wf_timeout",
    )
    wf.settings = {"timeout_seconds": 0.5}

    started = time.monotonic()
    result = await execute_workflow(wf, [{"start": True}])
    elapsed = time.monotonic() - started

    assert result.status == "timeout"
    assert elapsed < 5


# ── 12. CANCELLATION ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancellation_mid_execution():
    """Start a workflow, cancel it mid-execution; result is 'cancelled'."""
    cancel_event = asyncio.Event()

    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow", "cancellable_sleep", parameters={"seconds": 10}),
        ],
        [conn("trigger", "slow")],
        wf_id="wf_cancel",
    )

    async def cancel_later():
        await asyncio.sleep(0.2)
        cancel_event.set()

    asyncio.create_task(cancel_later())

    started = time.monotonic()
    result = await execute_workflow(wf, [{"start": True}], cancel_event=cancel_event)
    elapsed = time.monotonic() - started

    assert result.status == "cancelled"
    assert elapsed < 5


# ── Edge: MERGE with one branch failing ──────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_one_branch_fails():
    """In a fan-in merge, if one branch fails the child is skipped,
    but the other branch's output is still collected."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"ok": True}}),
            make_node("B", "boom"),
            make_node("merge", "merge", parameters={"strategy": "concat"}),
        ],
        [
            conn("trigger", "A"),
            conn("trigger", "B"),
            conn("A", "merge"),
            conn("B", "merge"),
        ],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "failed"
    assert "merge" in result.skipped


# ── Edge: PARALLEL branches with expressions ─────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_branches_with_independent_data():
    """Two independent branches produce different data, merge recombines."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("branch1", "set_data", parameters={"fields": {"x": 10, "label": "alpha"}}),
            make_node("branch2", "set_data", parameters={"fields": {"x": 20, "label": "beta"}}),
            make_node(
                "merge",
                "set_data",
                parameters={"fields": {"merged": True}},
            ),
        ],
        [
            conn("trigger", "branch1"),
            conn("trigger", "branch2"),
            conn("branch1", "merge"),
            conn("branch2", "merge"),
        ],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    items = result.results["merge"]["main"]
    assert len(items) == 2
    labels = {item["label"] for item in items}
    assert labels == {"alpha", "beta"}


# ── Edge: LOOP with per-item failure and continue_on_error ──────────────────


@pytest.mark.asyncio
async def test_loop_per_item_failure_with_continue():
    """Split fans out 3 items; the downstream boom node fails with
    continue_on_error. In the batch execution path the first item's
    failure immediately breaks the loop and _fail() produces a single
    $error item. C then receives that one item and runs."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"data": [{"i": 1}, {"i": 2}, {"i": 3}]}}),
            make_node("split", "split", parameters={"field": "data"}),
            make_node(
                "B",
                "boom",
                settings={"continue_on_error": True},
            ),
            make_node("C", "set_data", parameters={"fields": {"checked": True}}),
        ],
        [conn("trigger", "A"), conn("A", "split"), conn("split", "B"), conn("B", "C")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    # The batch path fails on the first item and _fail() stores one $error
    # item (not one per input). Downstream C sees that single item.
    b_items = result.results["B"]["main"]
    assert len(b_items) == 1
    assert "$error" in b_items[0]
    c_items = result.results["C"]["main"]
    assert len(c_items) == 1
    assert c_items[0]["checked"] is True


# ── Edge: expression evaluates to null/missing ────────────────────────────────


@pytest.mark.asyncio
async def test_expression_missing_field_is_graceful():
    """Referencing a non-existent field via $json yields an unresolvable
    expression (left as template) rather than crashing."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"only_this": "hello"}}),
            make_node(
                "B",
                "set_data",
                parameters={
                    "fields": {
                        "exists": "{{ $json.only_this }}",
                        "missing": "{{ $json.does_not_exist }}",
                    }
                },
            ),
        ],
        [conn("trigger", "A"), conn("A", "B")],
    )
    result = await execute_workflow(wf, [{"start": True}])

    assert result.status == "success"
    b_items = result.results["B"]["main"]
    assert b_items[0]["exists"] == "hello"
    assert b_items[0]["missing"] == "{{ $json.does_not_exist }}"


# ── Edge: empty trigger items ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_trigger_items():
    """Trigger with no items still runs the workflow successfully."""
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("A", "set_data", parameters={"fields": {"ok": True}}),
        ],
        [conn("trigger", "A")],
    )
    result = await execute_workflow(wf, [])

    assert result.status == "success"
    a_items = result.results["A"]["main"]
    assert len(a_items) == 1
    assert a_items[0]["ok"] is True
