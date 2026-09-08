"""Phase 9 engine tests: parallel branches (spec 8.2), merge modes,
retry policy (spec 8.3) and the global workflow timeout."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.executor import execute_workflow
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from tests.conftest import conn, make_node, make_workflow


class SleepParams(BaseModel):
    seconds: float = Field(default=0.2, ge=0)
    fail_attempts: int = Field(default=0, ge=0)
    fail_retryable: bool = False


_attempts: dict[str, int] = {}


@register
class SleepStubNode(BaseNode[SleepParams]):
    """Sleeps `seconds`; fails the first `fail_attempts` attempts."""

    node_type = "sleep_stub"
    display_name = "Sleep (test stub)"
    version = 1
    category = "Test"
    icon = "💤"
    parameters_schema = SleepParams

    async def run(self, ctx: NodeContext, params: SleepParams, input_items: list[dict[str, Any]]) -> NodeResult:
        await asyncio.sleep(params.seconds)
        if params.fail_attempts > 0:
            key = ctx.execution_id
            n = _attempts.get(key, 0) + 1
            _attempts[key] = n
            if n <= params.fail_attempts:
                raise NodeExecutionError(
                    f"boom (attempt={n}/{params.fail_attempts})",
                    code="STUB_FAIL", retryable=params.fail_retryable,
                )
        return NodeResult(output_items=input_items)


@pytest.fixture(autouse=True)
def _reset_attempts():
    _attempts.clear()


def _events(result) -> list[dict]:
    return result.events


async def test_parallel_branches_run_concurrently(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("a", "sleep_stub", parameters={"seconds": 0.4}),
            make_node("b", "sleep_stub", parameters={"seconds": 0.4}),
        ],
        [conn("trigger", "a"), conn("trigger", "b")],
    )
    started = time.monotonic()
    result = await execute_workflow(wf, http_client=http_client)
    elapsed = time.monotonic() - started
    assert result.status == "success"
    assert elapsed < 0.7  # branches ran in parallel, not 0.4 + 0.4


async def test_parallel_branches_respect_dependencies(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("a", "sleep_stub", parameters={"seconds": 0.2}),
            make_node("b", "sleep_stub", parameters={"seconds": 0.2}),
            make_node("c", "sleep_stub", parameters={"seconds": 0.2}),
        ],
        [conn("trigger", "a"), conn("a", "c"), conn("trigger", "b")],
    )
    result = await execute_workflow(wf, http_client=http_client)
    assert result.status == "success"
    order = [s["node_id"] for s in result.trace]
    assert order.index("a") < order.index("c")
    assert all(s in order for s in ["a", "b", "c"])


async def test_wait_for_one_runs_on_first_parent(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow_parent", "sleep_stub", parameters={"seconds": 0.5}),
            make_node("fast_parent", "sleep_stub", parameters={"seconds": 0.05}),
            make_node("merge", "sleep_stub", parameters={"seconds": 0.0},
                      settings={"merge_mode": "wait_for_one"}),
        ],
        [
            conn("trigger", "slow_parent"), conn("trigger", "fast_parent"),
            conn("slow_parent", "merge"), conn("fast_parent", "merge"),
        ],
    )
    result = await execute_workflow(wf, http_client=http_client)
    assert result.status == "success"
    # merge ran before the slow parent finished (waited for the first parent only)
    slow = next(s for s in result.trace if s["node_id"] == "slow_parent")
    merge = next(s for s in result.trace if s["node_id"] == "merge")
    end_slow = datetime.fromisoformat(slow["started_at"]) + timedelta(milliseconds=slow["duration_ms"])
    assert datetime.fromisoformat(merge["started_at"]) < end_slow
    assert merge["status"] == "success"


async def test_wait_for_all_default_waits_for_both_parents(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow_parent", "sleep_stub", parameters={"seconds": 0.4}),
            make_node("fast_parent", "sleep_stub", parameters={"seconds": 0.05}),
            make_node("merge", "sleep_stub", parameters={"seconds": 0.0}),
        ],
        [
            conn("trigger", "slow_parent"), conn("trigger", "fast_parent"),
            conn("slow_parent", "merge"), conn("fast_parent", "merge"),
        ],
    )
    started = time.monotonic()
    result = await execute_workflow(wf, http_client=http_client)
    elapsed = time.monotonic() - started
    assert result.status == "success"
    assert elapsed >= 0.35  # waited for the slow parent


async def test_retry_retries_then_succeeds(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("flaky", "sleep_stub", parameters={"seconds": 0.0, "fail_attempts": 1, "fail_retryable": True},
                      settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0}),
        ],
        [conn("trigger", "flaky")],
    )
    result = await execute_workflow(wf, http_client=http_client)
    assert result.status == "success"
    retries = [ev for ev in _events(result) if ev.get("event") == "node.retry"]
    assert len(retries) == 1
    assert retries[0]["node_id"] == "flaky"
    note = next(s for s in result.trace if s["node_id"] == "flaky").get("note")
    assert note is not None and "1 retry" in note


async def test_retry_exhausts_attempts(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("doomed", "sleep_stub", parameters={"seconds": 0.0, "fail_attempts": 99, "fail_retryable": True},
                      settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0}),
        ],
        [conn("trigger", "doomed")],
    )
    result = await execute_workflow(wf, http_client=http_client)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "STUB_FAIL"
    attempts = 1 + len([ev for ev in _events(result) if ev.get("event") == "node.retry" and ev.get("node_id") == "doomed"])
    assert attempts == 4  # 1 initial attempt + 3 retries
    note = next(s for s in result.trace if s["node_id"] == "doomed").get("note")
    assert note is not None and "4 attempt" in note


async def test_non_retryable_error_not_retried(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("hard", "sleep_stub", parameters={"seconds": 0.0, "fail_attempts": 1, "fail_retryable": False},
                      settings={"retry_max_attempts": 5, "retry_backoff_seconds": 0}),
        ],
        [conn("trigger", "hard")],
    )
    result = await execute_workflow(wf, http_client=http_client)
    assert result.status == "failed"
    attempts = len([ev for ev in _events(result) if ev.get("event") == "node.started" and ev.get("node_id") == "hard"])
    assert attempts == 1


async def test_retry_backoff_is_exponential(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("flaky", "sleep_stub", parameters={"seconds": 0.0, "fail_attempts": 2, "fail_retryable": True},
                      settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.05}),
        ],
        [conn("trigger", "flaky")],
    )
    started = time.monotonic()
    result = await execute_workflow(wf, http_client=http_client)
    elapsed = time.monotonic() - started
    assert result.status == "success"
    assert elapsed >= 0.14  # 0.05 + 0.10 backoff


async def test_sibling_branch_continues_after_error(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("bad", "sleep_stub", parameters={"seconds": 0.05, "fail_attempts": 1, "fail_retryable": False}),
            make_node("good", "sleep_stub", parameters={"seconds": 0.05}),
        ],
        [conn("trigger", "bad"), conn("trigger", "good")],
    )
    result = await execute_workflow(wf, http_client=http_client)
    assert result.status == "failed"
    assert "good" in result.results
    assert next(s for s in result.trace if s["node_id"] == "good")["status"] == "success"


async def test_workflow_timeout_kills_run(http_client):
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("slow", "sleep_stub", parameters={"seconds": 10}),
        ],
        [conn("trigger", "slow")],
        wf_id="wf_timeout",
    )
    wf.settings["timeout_seconds"] = 0.15
    started = time.monotonic()
    result = await execute_workflow(wf, http_client=http_client)
    elapsed = time.monotonic() - started
    assert result.status == "timeout"
    assert elapsed < 3
    assert any(ev.get("event") == "execution.timeout" for ev in _events(result))
