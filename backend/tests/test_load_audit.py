"""Load / stress tests for the workflow engine (5 scenarios).

Covers: sequential throughput, concurrent execution, mixed workload,
DB-queue processing, and expression engine scaling.
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid
from typing import Any

import httpx
import pytest

from app.engine.executor import execute_workflow
from app.engine.expressions import build_context, resolve
from app.schemas.workflow import Connection, Workflow, WorkflowNode
from tests.conftest import conn, make_node, make_workflow

# ---------------------------------------------------------------------------
# Timeout: 300s for the entire file
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.timeout(300)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_code_workflow(wf_id: str = "wf_load", code: str = "return [{json: {result: 'ok'}}];") -> Workflow:
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("code1", "code", parameters={"code": code, "language": "javascript"}),
        ],
        [conn("trigger", "code1")],
        wf_id=wf_id,
    )


def _expression_code_workflow(wf_id: str, code: str) -> Workflow:
    """Workflow: trigger → code node (generates items) → code node (processes)."""
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("gen", "code", parameters={"code": code, "language": "javascript"}),
        ],
        [conn("trigger", "gen")],
        wf_id=wf_id,
    )


def _if_branch_workflow(wf_id: str = "wf_if") -> Workflow:
    """Workflow: trigger → code (set value) → IF condition."""
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("code1", "code", parameters={
                "code": "return [{json: {value: 42, label: 'yes'}}];",
                "language": "javascript",
            }),
            make_node("if1", "if_condition", parameters={
                "conditions": [
                    {"id": "c1", "left": "$json.value", "operator": "is greater than", "right": 10, "combinator": "AND"}
                ],
                "combinator": "AND",
            }),
        ],
        [conn("trigger", "code1"), conn("code1", "if1")],
        wf_id=wf_id,
    )


def _http_mock_workflow(wf_id: str, mock_url: str, mock_response: dict) -> Workflow:
    """Workflow: trigger → HTTP request (will be mocked)."""
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("http1", "http_request", parameters={
                "method": "GET",
                "url": mock_url,
                "options": {"response": {"response": {"fullResponse": False}}},
            }),
        ],
        [conn("trigger", "http1")],
        wf_id=wf_id,
    )


def _percentile(data: list[float], p: float) -> float:
    """Calculate the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def _report(label: str, times: list[float], total: float) -> None:
    """Print timing statistics."""
    avg = statistics.mean(times)
    p50 = _percentile(times, 50)
    p95 = _percentile(times, 95)
    p99 = _percentile(times, 99)
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total time:   {total:.3f}s")
    print(f"  Count:        {len(times)}")
    print(f"  Avg per exec: {avg:.4f}s")
    print(f"  Min:          {min(times):.4f}s")
    print(f"  Max:          {max(times):.4f}s")
    print(f"  P50:          {p50:.4f}s")
    print(f"  P95:          {p95:.4f}s")
    print(f"  P99:          {p99:.4f}s")
    print(f"{'='*60}")


# ===========================================================================
# LOAD TEST 1 — SEQUENTIAL (200 executions)
# ===========================================================================


@pytest.mark.asyncio
async def test_load_sequential_200():
    """Execute 200 workflows sequentially and verify timing."""
    wf = _simple_code_workflow(wf_id="wf_load_seq200")
    times: list[float] = []

    async with httpx.AsyncClient() as client:
        wall_start = time.perf_counter()
        for i in range(200):
            t0 = time.perf_counter()
            result = await execute_workflow(
                wf, execution_id=f"seq200_{i}", http_client=client,
            )
            t1 = time.perf_counter()
            times.append(t1 - t0)
            assert result.status == "success", f"Execution {i} failed: {result.error}"
            assert result.results.get("code1", {}).get("main") is not None
        wall_total = time.perf_counter() - wall_start

    _report("LOAD TEST 1 — SEQUENTIAL (200)", times, wall_total)

    avg = statistics.mean(times)
    p99 = _percentile(times, 99)
    assert len(times) == 200
    assert avg < 1.0, f"Average {avg:.4f}s exceeds 1s threshold"
    assert p99 < 5.0, f"P99 {p99:.4f}s exceeds 5s threshold"


# ===========================================================================
# LOAD TEST 2 — CONCURRENT (50 concurrent)
# ===========================================================================


@pytest.mark.asyncio
async def test_load_concurrent_50():
    """Execute 50 workflows concurrently and verify no deadlocks."""
    wf = _simple_code_workflow(wf_id="wf_load_conc50")
    times: list[float] = []

    async with httpx.AsyncClient() as client:
        async def run_one(idx: int) -> tuple[float, Any]:
            t0 = time.perf_counter()
            result = await execute_workflow(
                wf, execution_id=f"conc50_{idx}", http_client=client,
            )
            t1 = time.perf_counter()
            return t1 - t0, result

        wall_start = time.perf_counter()
        outcomes = await asyncio.gather(*[run_one(i) for i in range(50)])
        wall_total = time.perf_counter() - wall_start

    for elapsed, result in outcomes:
        times.append(elapsed)
        assert result.status == "success", f"Concurrent execution failed: {result.error}"

    _report("LOAD TEST 2 — CONCURRENT (50)", times, wall_total)

    assert len(times) == 50
    # No individual execution should hang (guarded by 300s file timeout)


# ===========================================================================
# LOAD TEST 3 — MIXED WORKLOAD (100 concurrent)
# ===========================================================================


@pytest.mark.asyncio
async def test_load_mixed_100():
    """50 simple + 25 HTTP-mock + 25 IF-branch workflows, all concurrent.

    Total: 100 concurrent executions.
    """
    import json as _json

    # --- Build workflows ---
    simple_wfs = [
        _simple_code_workflow(wf_id=f"wf_mixed_simple_{i}")
        for i in range(50)
    ]

    # IF-branch workflows
    if_wfs = [_if_branch_workflow(wf_id=f"wf_mixed_if_{i}") for i in range(25)]

    # HTTP mock workflows — we'll mock the httpx client to avoid real network
    http_wfs = [
        _http_mock_workflow(
            wf_id=f"wf_mixed_http_{i}",
            mock_url="http://localhost:9999/test",
            mock_response={"status": "ok"},
        )
        for i in range(25)
    ]

    all_wfs = simple_wfs + if_wfs + http_wfs

    # --- Mock HTTP client that returns canned responses ---
    def _mock_response() -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"status": "ok"},
            text='{"status": "ok"}',
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "http://localhost:9999/test"),
        )

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, url, **kwargs):
            return _mock_response()

        async def get(self, url, **kwargs):
            return _mock_response()

        async def post(self, url, **kwargs):
            return _mock_response()

    # --- Run all 100 concurrently ---
    results: list[tuple[int, Any]] = []

    async def run_idx(idx: int, wf: Workflow) -> tuple[int, Any]:
        # Use mock client for HTTP workflows, real client for others
        if idx >= 75:  # HTTP workflows
            client = MockAsyncClient()
        else:
            client = httpx.AsyncClient()
        try:
            result = await execute_workflow(
                wf, execution_id=f"mixed_{idx}", http_client=client,
            )
            return idx, result
        finally:
            if hasattr(client, "aclose"):
                await client.aclose()

    wall_start = time.perf_counter()
    outcomes = await asyncio.gather(*[run_idx(i, wf) for i, wf in enumerate(all_wfs)])
    wall_total = time.perf_counter() - wall_start

    simple_count = 0
    if_count = 0
    http_count = 0

    for idx, result in outcomes:
        assert result.status == "success", f"Mixed workflow {idx} failed: {result.error}"
        if idx < 50:
            simple_count += 1
            assert result.results.get("code1", {}).get("main") is not None
        elif idx < 75:
            if_count += 1
            # IF node should have produced output on true or false branch
            assert result.results.get("if1") is not None
        else:
            http_count += 1
            # HTTP node should have produced output (from mock)
            assert result.results.get("http1") is not None

    print(f"\n  MIXED WORKLOAD: {simple_count} simple + {if_count} IF + {http_count} HTTP = {len(outcomes)} total")
    print(f"  Wall time: {wall_total:.3f}s")

    assert simple_count == 50
    assert if_count == 25
    assert http_count == 25
    assert len(outcomes) == 100


# ===========================================================================
# LOAD TEST 4 — QUEUE STRESS (100 queued jobs)
# ===========================================================================


@pytest.mark.asyncio
async def test_load_queue_stress_100():
    """Enqueue 100 jobs, process one at a time, verify throughput."""
    from app.db import get_session
    from app.models import Execution, Job, User, WorkflowRecord
    from app.models.job import DONE, QUEUED
    from app.queue.db_queue import DbJobQueue

    queue = DbJobQueue()
    wf_id = "wf_queue_stress"
    user_id = 99999

    # Seed user and workflow
    db = get_session()
    try:
        existing = db.get(User, user_id)
        if existing is None:
            db.add(User(id=user_id, email=f"queue_stress_{user_id}@test.com", password_hash="x"))
        existing_wf = db.get(WorkflowRecord, wf_id)
        if existing_wf is None:
            db.add(WorkflowRecord(id=wf_id, user_id=user_id, name="Queue Stress", data={}, active=False))
        db.commit()
    finally:
        db.close()

    # Enqueue 100 jobs
    wf_data = {
        "id": wf_id,
        "name": "Queue Stress WF",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "code1", "type": "code", "parameters": {"code": "return [{json: {result: 'ok'}}];", "language": "javascript"}},
        ],
        "connections": [{"source": "trigger", "target": "code1"}],
        "settings": {},
    }
    payload = {
        "workflow_data": wf_data,
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": user_id,
        "workflow_id": wf_id,
        "version": 1,
    }

    job_ids: list[str] = []
    exec_ids: list[str] = []

    for i in range(100):
        exec_id = f"queue_stress_{i}"
        job_id = f"job_queue_stress_{i}"
        db = get_session()
        try:
            db.add(Execution(
                id=exec_id,
                workflow_id=wf_id,
                user_id=user_id,
                workflow_version=1,
                workflow_data=wf_data,
                trigger="manual",
                trigger_data=[{}],
                status="queued",
            ))
            db.commit()
        finally:
            db.close()
        ok = queue.enqueue(job_id, exec_id, payload)
        assert ok, f"Failed to enqueue job {i}"
        job_ids.append(job_id)
        exec_ids.append(exec_id)

    # Process one at a time (single worker)
    processed = 0
    wall_start = time.perf_counter()

    claim_timeout = 60.0
    async with httpx.AsyncClient() as client:
        while processed < 100:
            if time.perf_counter() - wall_start > claim_timeout:
                break
            claimed = queue.claim()
            if claimed is None:
                await asyncio.sleep(0.01)
                continue

            # Run the workflow via execute_workflow
            from app.schemas.workflow import Workflow as WF
            workflow = WF.model_validate(claimed.workflow_data)
            result = await execute_workflow(
                workflow,
                claimed.trigger_items,
                execution_id=claimed.execution_id,
                http_client=client,
            )
            status = "done" if result.status == "success" else "failed"
            queue.complete(claimed.id, status=status)
            processed += 1

    wall_total = time.perf_counter() - wall_start
    throughput = processed / wall_total if wall_total > 0 else float("inf")

    print(f"\n  QUEUE STRESS: {processed} jobs in {wall_total:.3f}s")
    print(f"  Throughput: {throughput:.2f} jobs/second")

    assert processed == 100
    assert throughput > 10.0, f"Throughput {throughput:.2f} jobs/s below 10 jobs/s threshold"


# ===========================================================================
# LOAD TEST 5 — EXPRESSION STRESS (1000 items)
# ===========================================================================


@pytest.mark.asyncio
async def test_load_expression_stress_1000():
    """Code node produces 1000 items; downstream processes each with expressions."""
    gen_code = (
        "var items = [];\n"
        "for (var i = 0; i < 1000; i++) {\n"
        "  items.push({json: {id: i, name: 'item_' + i, value: i * 2}});\n"
        "}\n"
        "return items;\n"
    )

    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("gen", "code", parameters={"code": gen_code, "language": "javascript"}),
        ],
        [conn("trigger", "gen")],
        wf_id="wf_expr_stress",
    )

    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        result = await execute_workflow(wf, execution_id="expr_stress_0", http_client=client)
        t1 = time.perf_counter()

    elapsed = t1 - t0
    print(f"\n  EXPRESSION STRESS: 1000 items generated in {elapsed:.4f}s")

    assert result.status == "success", f"Expression stress failed: {result.error}"
    gen_output = result.results.get("gen", {}).get("main", [])
    assert len(gen_output) == 1000, f"Expected 1000 items, got {len(gen_output)}"

    # Verify content of first and last items
    assert gen_output[0]["id"] == 0
    assert gen_output[0]["name"] == "item_0"
    assert gen_output[0]["value"] == 0
    assert gen_output[999]["id"] == 999
    assert gen_output[999]["name"] == "item_999"
    assert gen_output[999]["value"] == 1998

    # Verify expression resolution on all items
    t_expr_start = time.perf_counter()
    ctx = build_context(gen_output, {}, "wf_expr_stress", "expr_stress_0")
    for item in gen_output:
        ctx["$json"] = item
        name_result = resolve("{{ $json.name }}", ctx)
        assert name_result == item["name"]
        val_result = resolve("{{ $json.value + 1 }}", ctx)
        assert val_result == item["value"] + 1
    t_expr_end = time.perf_counter()

    expr_elapsed = t_expr_end - t_expr_start
    print(f"  Expression resolution (1000 items × 2 expressions): {expr_elapsed:.4f}s")
    print(f"  Per-item resolution: {expr_elapsed / 1000 * 1000:.2f}ms")

    # All 1000 items processed correctly
    assert len(gen_output) == 1000
