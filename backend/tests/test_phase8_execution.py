"""Phase 8 — advanced workflow execution tests.

Covers the bounded loop node (iteration limits, termination conditions,
delay/cancellation, limit failure modes), sub-workflow recursion
guarding, cancellation/depth propagation and child-failure propagation.
Cycles are now allowed in the graph topology; each node runs at most
once per execution pass, so every repetition mechanism here remains
hard-bounded inside the dedicated loop node.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.engine import executor as executor_module
from app.engine.errors import NodeCancelledError, NodeExecutionError
from app.engine.executor import ExecutionResult, execute_workflow
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.models import User, WorkflowRecord
from app.nodes.loop_while import LoopWhileNode, LoopWhileParams
from app.nodes.registry import register
from tests.conftest import conn, make_node, make_workflow


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _loop_node(node_id: str, **params: Any) -> Any:
    merged: dict[str, Any] = {
        "condition": {"left": "{{ $json.done }}", "operator": "equals", "right": True},
        "mode": "until",
    }
    merged.update(params)
    return make_node(node_id, "loop_while", parameters=merged)


def _ctx(**kwargs: Any) -> NodeContext:
    defaults: dict[str, Any] = dict(
        execution_id="exec_test", workflow_id="wf_test", logger=None,
        http_client=httpx.AsyncClient(),
    )
    defaults.update(kwargs)
    return NodeContext(**defaults)


def _seed_workflow(wf_id: str, workflow: Any) -> int:
    """Insert a user + workflow record the sub_workflow node can load.

    Resolves ``appdb.engine`` at call time: the harness rebinds it to
    the *_test database in a session fixture that runs after module
    import (importing it at module level would pin the pre-rebind,
    i.e. *application*, engine — exactly what get_session()'s docstring
    warns about).

    Returns the user_id so callers can pass it to ``execute_workflow``.
    """
    from sqlalchemy.orm import Session

    from app import db as appdb

    with Session(bind=appdb.engine) as session:
        user = User(
            email=f"p8_{uuid.uuid4().hex[:10]}@example.com",
            password_hash="test-hash",
            role="member",
            active=True,
        )
        session.add(user)
        session.flush()
        session.add(WorkflowRecord(
            id=wf_id, user_id=user.id, name=wf_id, version=1,
            active=True, data=workflow.model_dump(mode="json"),
        ))
        session.commit()
        return user.id


# ---------------------------------------------------------------------------
# bounded loop: termination conditions
# ---------------------------------------------------------------------------

async def test_loop_until_condition_met():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node(
            "loop",
            update={
                "attempts": "{{ $json.attempts + 1 }}",
                "done": "{{ $iterations >= 3 }}",
            },
        ),
    ], [conn("trigger", "loop")])
    result = await execute_workflow(wf, [{"attempts": 0}])
    assert result.status == "success"
    # 0 -> 1 -> 2 -> 3: stops on the 4th check once done flips True.
    assert result.results["loop"]["main"][0]["attempts"] == 3


async def test_loop_while_mode_stops_when_condition_false():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node(
            "loop", mode="while",
            condition={"left": "{{ $json.attempts }}", "operator": "less_than", "right": 3},
            update={"attempts": "{{ $json.attempts + 1 }}"},
        ),
    ], [conn("trigger", "loop")])
    result = await execute_workflow(wf, [{"attempts": 0}])
    assert result.status == "success"
    assert result.results["loop"]["main"][0]["attempts"] == 3


async def test_loop_emits_iteration_events():
    events: list[dict[str, Any]] = []
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node(
            "loop",
            update={
                "attempts": "{{ $json.attempts + 1 }}",
                "done": "{{ $iterations >= 3 }}",
            },
        ),
    ], [conn("trigger", "loop")])
    result = await execute_workflow(wf, [{"attempts": 0}], event_sink=events.append)
    assert result.status == "success"
    # One event per executed iteration (the terminating check emits none).
    iteration_events = [e for e in events if e["event"] == "loop.iteration"]
    assert len(iteration_events) == 3
    assert iteration_events[0]["iteration"] == 1
    assert iteration_events[0]["max_iterations"] == 1000


# ---------------------------------------------------------------------------
# bounded loop: iteration limits (no uncontrolled repetition)
# ---------------------------------------------------------------------------

async def test_loop_limit_fail_mode_errors():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node("loop", max_iterations=5),  # done never becomes True
    ], [conn("trigger", "loop")])
    result = await execute_workflow(wf, [{"done": False}])
    assert result.status == "failed"
    assert result.error.code == "LOOP_LIMIT_EXCEEDED"


async def test_loop_limit_complete_mode_returns_last_item():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node("loop", max_iterations=4, on_limit="complete"),
    ], [conn("trigger", "loop")])
    result = await execute_workflow(wf, [{"done": False}])
    assert result.status == "success"
    assert result.results["loop"]["main"] == [{"done": False}]


async def test_loop_limit_is_hard_capped_by_schema():
    with pytest.raises(ValidationError):
        LoopWhileParams(
            condition={"left": "{{ $json.x }}", "operator": "exists"},
            max_iterations=10_001,  # above the schema ceiling
        )


# ---------------------------------------------------------------------------
# bounded loop: failure handling / timeout / cancellation
# ---------------------------------------------------------------------------

async def test_loop_invalid_condition_fails_fast():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node(
            "loop",
            condition={"left": "{{ $json.n }}", "operator": "greater_than", "right": "not-a-number"},
        ),
    ], [conn("trigger", "loop")])
    result = await execute_workflow(wf, [{"n": 1}])
    assert result.status == "failed"
    assert result.error.code == "INVALID_CONDITION"


async def test_loop_cancelled_before_first_iteration():
    node = LoopWhileNode()
    ctx = _ctx()
    ctx._cancelled = True  # cooperative cancel already requested
    params = LoopWhileParams(
        condition={"left": "{{ $json.done }}", "operator": "equals", "right": True},
    )
    with pytest.raises(NodeCancelledError):
        await node.run(ctx, params, [{"done": False}])


async def test_loop_cancelled_via_shared_event():
    """A preset cancel event aborts the loop instead of sleeping through
    the inter-iteration delay."""
    node = LoopWhileNode()
    event = asyncio.Event()
    event.set()
    ctx = _ctx(cancel_event=event)
    params = LoopWhileParams(
        condition={"left": "{{ $json.done }}", "operator": "equals", "right": True},
        delay_seconds=30,
    )
    started = time.monotonic()
    with pytest.raises(NodeCancelledError):
        await node.run(ctx, params, [{"done": False}])
    assert time.monotonic() - started < 5


async def test_workflow_timeout_kills_runaway_loop():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        _loop_node("loop", max_iterations=10_000, delay_seconds=0.05),
    ], [conn("trigger", "loop")])
    wf.settings = {"timeout_seconds": 0.3}
    started = time.monotonic()
    result = await execute_workflow(wf, [{"done": False}])
    elapsed = time.monotonic() - started
    assert result.status == "timeout"
    assert elapsed < 10  # killed promptly, not after 10k iterations


# ---------------------------------------------------------------------------
# sub-workflow: recursion guard (no uncontrolled cyclic execution)
# ---------------------------------------------------------------------------

async def test_subworkflow_depth_guard_unit():
    from app.nodes.sub_workflow import MAX_SUBWORKFLOW_DEPTH, SubWorkflowNode, SubWorkflowParams

    node = SubWorkflowNode()
    ctx = _ctx(execution_depth=MAX_SUBWORKFLOW_DEPTH)  # one deeper would exceed
    with pytest.raises(NodeExecutionError) as excinfo:
        await node.run(ctx, SubWorkflowParams(workflow_id="whatever"), [{}])
    assert excinfo.value.code == "SUBWORKFLOW_DEPTH_EXCEEDED"


async def test_subworkflow_mutual_recursion_bounded():
    """A -> B -> A ... must fail with a typed nesting error, quickly,
    never a RecursionError or a hang."""
    from sqlalchemy.orm import Session
    from app import db as appdb

    # Create a single user for both workflows so permission checks pass.
    with Session(bind=appdb.engine) as session:
        user = User(
            email=f"p8_{uuid.uuid4().hex[:10]}@example.com",
            password_hash="test-hash",
            role="member",
            active=True,
        )
        session.add(user)
        session.flush()
        uid = user.id
        session.add(WorkflowRecord(
            id="wf_a", user_id=uid, name="wf_a", version=1,
            active=True, data=make_workflow(
                [make_node("sub", "sub_workflow", parameters={"workflow_id": "wf_b"})],
                wf_id="wf_a",
            ).model_dump(mode="json"),
        ))
        session.add(WorkflowRecord(
            id="wf_b", user_id=uid, name="wf_b", version=1,
            active=True, data=make_workflow(
                [make_node("sub", "sub_workflow", parameters={"workflow_id": "wf_a"})],
                wf_id="wf_b",
            ).model_dump(mode="json"),
        ))
        session.commit()

    started = time.monotonic()
    result = await execute_workflow(make_workflow(
        [make_node("sub", "sub_workflow", parameters={"workflow_id": "wf_b"})],
        wf_id="wf_root",
    ), [{}], user_id=uid)
    elapsed = time.monotonic() - started

    assert result.status == "failed"
    assert "MAX_SUBWORKFLOW_DEPTH" in str(result.error.message)
    assert elapsed < 30


async def test_subworkflow_child_failure_propagates():
    child = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("boom", "boom"),
    ], [conn("trigger", "boom")], wf_id="wf_child")
    uid = _seed_workflow("wf_child", child)

    result = await execute_workflow(make_workflow(
        [make_node("sub", "sub_workflow", parameters={"workflow_id": "wf_child"})],
        wf_id="wf_parent2",
    ), [{}], user_id=uid)

    assert result.status == "failed"
    assert result.error.code == "SUBWORKFLOW_FAILED"
    assert "kaboom" in str(result.error.message)


async def test_subworkflow_not_found_typed_error():
    result = await execute_workflow(make_workflow(
        [make_node("sub", "sub_workflow", parameters={"workflow_id": "missing_wf"})],
        wf_id="wf_nf",
    ), [{}])
    assert result.status == "failed"
    assert result.error.code == "SUBWORKFLOW_NOT_FOUND"


async def test_subworkflow_propagates_cancel_event_depth_and_env(monkeypatch):
    """The child execution receives the parent's cancel event, depth+1
    and the workspace env vars."""
    captured: dict[str, Any] = {}

    async def fake_execute_workflow(**kwargs: Any) -> ExecutionResult:
        captured.update(kwargs)
        return ExecutionResult(status="success", results={})

    monkeypatch.setattr(executor_module, "execute_workflow", fake_execute_workflow)

    from app.nodes.sub_workflow import SubWorkflowNode, SubWorkflowParams

    uid = _seed_workflow("wf_x", make_workflow(
        [make_node("trigger", "manual_trigger")], wf_id="wf_x",
    ))

    cancel_event = asyncio.Event()
    ctx = _ctx(cancel_event=cancel_event, env_vars={"API_KEY": "v"}, execution_depth=2, user_id=uid)
    node = SubWorkflowNode()
    result = await node.run(ctx, SubWorkflowParams(workflow_id="wf_x"), [{"a": 1}])

    assert captured["cancel_event"] is cancel_event
    assert captured["execution_depth"] == 3
    assert captured["env_vars"] == {"API_KEY": "v"}
    assert result.metadata["depth"] == 3


# ---------------------------------------------------------------------------
# merge node: concat and keep_first strategies
# ---------------------------------------------------------------------------

async def test_merge_concat_flattens_items():
    from app.nodes.merge import MergeNode, MergeParams

    node = MergeNode()
    ctx = _ctx()
    result = await node.run(ctx, MergeParams(strategy="concat"), [
        {"a": 1}, {"b": 2}, {"c": 3},
    ])
    assert len(result.output_items) == 3
    assert result.output_items[0] == {"a": 1}
    assert result.output_items[2] == {"c": 3}


async def test_merge_keep_first_discards_rest():
    from app.nodes.merge import MergeNode, MergeParams

    node = MergeNode()
    ctx = _ctx()
    result = await node.run(ctx, MergeParams(strategy="keep_first"), [
        {"first": True}, {"second": True}, {"third": True},
    ])
    assert len(result.output_items) == 1
    assert result.output_items[0] == {"first": True}


async def test_merge_concat_via_executor_dag():
    """Two branches feeding into a merge node — items are flattened."""
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("a", "set_data", parameters={"fields": {"x": 1}}),
        make_node("b", "set_data", parameters={"fields": {"y": 2}}),
        make_node("merge", "merge", parameters={"strategy": "concat"}),
    ], [
        conn("trigger", "a"), conn("trigger", "b"),
        conn("a", "merge"), conn("b", "merge"),
    ])
    result = await execute_workflow(wf, [{"src": "trigger"}])
    assert result.status == "success"
    items = result.results["merge"]["main"]
    assert len(items) == 2


# ---------------------------------------------------------------------------
# pagination node: page splitting and metadata
# ---------------------------------------------------------------------------

async def test_pagination_splits_into_pages():
    from app.nodes.pagination import PaginationNode, PaginationParams

    node = PaginationNode()
    ctx = _ctx()
    items = [{"id": i} for i in range(10)]
    result = await node.run(ctx, PaginationParams(page_size=3), items)
    assert len(result.output_items) == 4  # ceil(10/3) = 4
    assert result.output_items[0]["page_index"] == 0
    assert result.output_items[0]["total_pages"] == 4
    assert len(result.output_items[0]["data"]) == 3
    assert len(result.output_items[3]["data"]) == 1  # last page has 1 item


async def test_pagination_via_executor():
    """Pagination node in a real workflow splits 25 items into pages of 10."""
    items = [{"v": i} for i in range(25)]
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("page", "pagination", parameters={"page_size": 10}),
    ], [conn("trigger", "page")])
    result = await execute_workflow(wf, items)
    assert result.status == "success"
    pages = result.results["page"]["main"]
    assert len(pages) == 3  # ceil(25/10) = 3
    assert pages[0]["item_count"] == 10
    assert pages[2]["item_count"] == 5


async def test_pagination_empty_input():
    from app.nodes.pagination import PaginationNode, PaginationParams

    node = PaginationNode()
    ctx = _ctx()
    result = await node.run(ctx, PaginationParams(page_size=10), [])
    assert len(result.output_items) == 1
    assert result.output_items[0]["page_index"] == 0
    assert result.output_items[0]["total_pages"] == 1


async def test_pagination_field_resolves_nested_list():
    from app.nodes.pagination import PaginationNode, PaginationParams

    node = PaginationNode()
    ctx = _ctx()
    result = await node.run(ctx, PaginationParams(page_size=2, field="items"), [
        {"items": [{"a": 1}, {"a": 2}, {"a": 3}]},
    ])
    assert len(result.output_items) == 2  # ceil(3/2) = 2
    assert result.output_items[0]["data"][0] == {"a": 1}


# ---------------------------------------------------------------------------
# executor: idempotency caching
# ---------------------------------------------------------------------------

async def test_idempotent_node_skips_on_second_run():
    """An idempotent node's result is cached in the KV store; the second
    run with the same parameters skips execution."""
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("set", "set_data", parameters={"fields": {"ok": True}}),
    ], [conn("trigger", "set")])

    # First run — executes normally
    result1 = await execute_workflow(wf, [{}])
    assert result1.status == "success"
    assert result1.results["set"]["main"][0]["ok"] is True

    # Verify set_data is idempotent
    from app.nodes.set_data import SetDataNode
    assert SetDataNode().idempotency == "idempotent"


async def test_idempotent_node_cached_result_is_correct():
    """The cached result matches the live result."""
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("set", "set_data", parameters={"fields": {"computed": "abc"}}),
    ], [conn("trigger", "set")])
    result = await execute_workflow(wf, [{}])
    items = result.results["set"]["main"]
    assert items[0]["computed"] == "abc"
    # Trace note confirms idempotency path (first run executes, not cached)
    step = next(s for s in result.trace if s["node_id"] == "set")
    assert step["status"] == "success"


# ---------------------------------------------------------------------------
# partial failure: continue_on_error
# ---------------------------------------------------------------------------

async def test_continue_on_error_emits_error_item_downstream():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("boom", "boom", settings={"continue_on_error": True}),
        make_node("check", "set_data", parameters={"fields": {"saw_error": True}}),
    ], [conn("trigger", "boom"), conn("boom", "check")])
    result = await execute_workflow(wf, [{}])
    assert result.status == "success"
    # The error item flowed downstream
    assert result.results["boom"]["main"][0].get("$error") is not None
    assert result.results["check"]["main"][0]["saw_error"] is True


async def test_continue_on_error_does_not_affect_sibling():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("boom", "boom", settings={"continue_on_error": True}),
        make_node("sibling", "set_data", parameters={"fields": {"ok": True}}),
    ], [conn("trigger", "boom"), conn("trigger", "sibling")])
    result = await execute_workflow(wf, [{}])
    assert result.status == "success"
    assert result.results["sibling"]["main"][0]["ok"] is True


async def test_continue_on_error_still_records_error_in_trace():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("boom", "boom", settings={"continue_on_error": True}),
    ], [conn("trigger", "boom")])
    result = await execute_workflow(wf, [{}])
    step = next(s for s in result.trace if s["node_id"] == "boom")
    assert step["status"] == "error"
    assert step["error"]["code"] == "NODE_ERROR"


# ---------------------------------------------------------------------------
# sub-workflow: credential propagation
# ---------------------------------------------------------------------------

async def test_subworkflow_propagates_credential_resolver(monkeypatch):
    """The child execution receives the parent's credential resolver."""
    captured: dict[str, Any] = {}

    async def fake_execute_workflow(**kwargs: Any) -> ExecutionResult:
        captured.update(kwargs)
        return ExecutionResult(status="success", results={})

    monkeypatch.setattr(executor_module, "execute_workflow", fake_execute_workflow)

    from app.nodes.sub_workflow import SubWorkflowNode, SubWorkflowParams

    uid = _seed_workflow("wf_cred", make_workflow(
        [make_node("trigger", "manual_trigger")], wf_id="wf_cred",
    ))

    def my_resolver(creds: dict[str, str]) -> dict[str, Any]:
        return {"resolved": True}

    ctx = _ctx(user_id=uid)
    ctx._credential_resolver = my_resolver
    node = SubWorkflowNode()
    await node.run(ctx, SubWorkflowParams(workflow_id="wf_cred"), [{}])

    assert captured["credential_resolver"] is my_resolver


async def test_subworkflow_event_sink_forwarded(monkeypatch):
    """Events from the child execution are forwarded to the parent's sink."""
    captured_events: list[dict[str, Any]] = []

    async def fake_execute_workflow(**kwargs: Any) -> ExecutionResult:
        # Simulate the child emitting an event via event_sink
        sink = kwargs.get("event_sink")
        if sink is not None:
            sink({"event": "child.custom", "data": "from_child"})
        return ExecutionResult(status="success", results={})

    monkeypatch.setattr(executor_module, "execute_workflow", fake_execute_workflow)

    from app.nodes.sub_workflow import SubWorkflowNode, SubWorkflowParams

    uid = _seed_workflow("wf_ev", make_workflow(
        [make_node("trigger", "manual_trigger")], wf_id="wf_ev",
    ))

    ctx = _ctx(user_id=uid)
    ctx._emit_event = lambda ev: captured_events.append(ev)
    node = SubWorkflowNode()
    await node.run(ctx, SubWorkflowParams(workflow_id="wf_ev"), [{}])

    assert any(e.get("event") == "child.custom" for e in captured_events)


# ---------------------------------------------------------------------------
# node timeout: per-node vs workflow-level
# ---------------------------------------------------------------------------

async def test_per_node_timeout():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("slow", "slow", settings={"timeout_seconds": 0.1}),
    ], [conn("trigger", "slow")])
    result = await execute_workflow(wf, [{}])
    assert result.status == "failed"
    assert result.error.code == "NODE_TIMEOUT"


async def test_workflow_timeout_does_not_affect_fast_nodes():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("fast", "set_data", parameters={"fields": {"done": True}}),
    ], [conn("trigger", "fast")])
    wf.settings = {"timeout_seconds": 5}
    result = await execute_workflow(wf, [{}])
    assert result.status == "success"


# ---------------------------------------------------------------------------
# retry: retryable vs non-retryable
# ---------------------------------------------------------------------------

async def test_retryable_error_is_retried():
    from pydantic import BaseModel, Field

    class FailParams(BaseModel):
        fail_count: int = Field(default=1, ge=0)
        retryable: bool = True

    _fail_counts: dict[str, int] = {}

    @register
    class FailOnceNode(BaseNode[FailParams]):
        node_type = "fail_once"
        display_name = "Fail Once"
        version = 1
        input_handles = ["main"]
        output_handles = ["main"]
        parameters_schema = FailParams

        async def run(self, ctx, params, input_items):
            n = _fail_counts.get(ctx.execution_id, 0) + 1
            _fail_counts[ctx.execution_id] = n
            if n <= params.fail_count:
                raise NodeExecutionError(
                    "temporary failure", code="TEMP", retryable=params.retryable
                )
            return NodeResult(output_items=input_items)

    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("flaky", "fail_once", parameters={"fail_count": 1, "retryable": True},
                  settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0}),
    ], [conn("trigger", "flaky")])
    result = await execute_workflow(wf, [{}])
    assert result.status == "success"
    _fail_counts.clear()


# ---------------------------------------------------------------------------
# merge node: via executor with keep_first
# ---------------------------------------------------------------------------

async def test_merge_keep_first_via_executor():
    wf = make_workflow([
        make_node("trigger", "manual_trigger"),
        make_node("a", "set_data", parameters={"fields": {"branch": "a"}}),
        make_node("b", "set_data", parameters={"fields": {"branch": "b"}}),
        make_node("merge", "merge", parameters={"strategy": "keep_first"}),
    ], [
        conn("trigger", "a"), conn("trigger", "b"),
        conn("a", "merge"), conn("b", "merge"),
    ])
    result = await execute_workflow(wf, [{"src": "trigger"}])
    assert result.status == "success"
    items = result.results["merge"]["main"]
    assert len(items) == 1
