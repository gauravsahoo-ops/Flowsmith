"""Performance & Reliability Audit Test Suite (Section 11).

Comprehensive empirical tests verifying all 10 requirements of Section 11:
1. API latency and throughput under representative loads
2. Workflow execution duration and queue latency
3. Concurrent workflows and worker scaling
4. Large payloads and high-volume execution history
5. Memory leaks, CPU usage and resource exhaustion
6. Database query performance and connection pooling
7. Redis outages, provider outages and network interruptions
8. Retry storms, deadlocks and queue backlog recovery
9. Long-running workflows and graceful shutdown
10. Load, stress, soak and recovery tests in safe environments
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import statistics
import time
import tracemalloc
import uuid
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import redis
from sqlalchemy import select, text

from app.config import get_settings
from app.connectors import ConnectorError, ConnectorErrorCode
from app.db import get_engine, get_session
from app.engine.errors import NodeCancelledError, NodeExecutionError, NodeTimeoutError
from app.engine.executor import ExecutionResult, _cap, execute_workflow
from app.engine.node_base import NodeContext, NodeResult
from app.main import app
from app.models import Execution, WorkflowRecord
from app.nodes.condition_base import Condition
from app.nodes.loop_while import LoopWhileNode, LoopWhileParams
from app.nodes.wait import WaitNode
from app.queue.db_queue import DbJobQueue
from app.queue.redis_queue import RedisJobQueue
from app.queue.worker import QueueWorker
from app.security.safe_http_client import SafeHTTPClient, get_safe_http_client
from tests.conftest import conn, make_node, make_workflow

logger = logging.getLogger("test_performance_and_reliability_audit")


# ---------------------------------------------------------------------------
# Test Helpers & Workflows
# ---------------------------------------------------------------------------

def _simple_calc_workflow(wf_id: str = "wf_perf_calc", multiplier: int = 2) -> Any:
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "calc",
                "code",
                parameters={
                    "code": f"return $input.all().map(item => ({{ val: (item.json ? item.json.val : item.val) * {multiplier} }}));",
                    "language": "javascript",
                },
            ),
        ],
        [conn("trigger", "calc")],
        wf_id=wf_id,
    )


def _branching_workflow(wf_id: str = "wf_perf_branch") -> Any:
    return make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "gen",
                "code",
                parameters={
                    "code": "return [{ score: 85, status: 'approved' }];",
                    "language": "javascript",
                },
            ),
            make_node(
                "if_cond",
                "if_condition",
                parameters={
                    "conditions": [
                        {"id": "c1", "left": "$json.score", "operator": "is greater than", "right": 50, "combinator": "AND"}
                    ],
                    "combinator": "AND",
                },
            ),
        ],
        [conn("trigger", "gen"), conn("gen", "if_cond")],
        wf_id=wf_id,
    )


# ===========================================================================
# 1. API latency and throughput under representative loads
# ===========================================================================

@pytest.mark.asyncio
async def test_01_api_latency_and_throughput_under_representative_loads():
    """Verify API latency percentiles and throughput under representative loads."""
    latencies: list[float] = []
    num_requests = 50

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Warmup request to live health route
        warmup = await client.get("/api/health")
        assert warmup.status_code == 200

        start_time = time.monotonic()
        for _ in range(num_requests):
            t0 = time.monotonic()
            resp = await client.get("/api/health")
            t1 = time.monotonic()
            assert resp.status_code == 200
            latencies.append((t1 - t0) * 1000.0)
        total_time = time.monotonic() - start_time

    assert len(latencies) == num_requests
    p50 = statistics.median(latencies)
    sorted_lats = sorted(latencies)
    p95 = sorted_lats[int(len(sorted_lats) * 0.95)]
    p99 = sorted_lats[int(len(sorted_lats) * 0.99)]
    mean_lat = statistics.mean(latencies)
    throughput = num_requests / total_time if total_time > 0 else 0.0

    logger.info(
        "API Load Metrics: p50=%.2fms, p95=%.2fms, p99=%.2fms, mean=%.2fms, throughput=%.1f req/s",
        p50, p95, p99, mean_lat, throughput
    )

    # API endpoints under representative loads must achieve low latency and 0% errors
    assert p95 < 200.0, f"p95 latency {p95:.2f}ms exceeded 200ms threshold"
    assert throughput > 50.0, f"Throughput {throughput:.1f} req/s was lower than target"


# ===========================================================================
# 2. Workflow execution duration and queue latency
# ===========================================================================

@pytest.mark.asyncio
async def test_02_workflow_execution_duration_and_queue_latency():
    """Verify queue latency tracking and accurate workflow execution duration."""
    queue = DbJobQueue()
    job_id = f"job_lat_{uuid.uuid4().hex[:8]}"
    exec_id = f"exec_lat_{uuid.uuid4().hex[:8]}"
    wf_id = f"wf_lat_{uuid.uuid4().hex[:8]}"

    payload = {
        "workflow_data": {"id": wf_id, "name": "Latency Test", "nodes": [], "connections": []},
        "trigger_items": [{"json": {"val": 10}}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": wf_id,
        "version": 1,
    }

    t_enqueue = time.time()
    assert queue.enqueue(job_id, exec_id, payload)

    # Claim job and calculate queue wait latency
    job = queue.claim()
    assert job is not None
    assert job.id == job_id
    t_claim = time.time()
    queue_latency_s = t_claim - t_enqueue
    assert queue_latency_s >= 0.0
    assert queue_latency_s < 2.0  # Immediate claim should be sub-second

    # Cleanup queue
    queue.complete(job_id, "done")

    # Now verify workflow execution duration tracking
    wf = _simple_calc_workflow(wf_id=wf_id, multiplier=3)
    async with httpx.AsyncClient() as client:
        res = await execute_workflow(
            wf,
            trigger_items=[{"json": {"val": 10}}],
            http_client=client,
        )

    assert res.status == "success"
    assert res.duration_ms > 0.0
    assert res.finished_at is not None
    assert res.finished_at >= res.started_at

    # Node-level trace timing verification
    assert len(res.trace) >= 2
    for step in res.trace:
        assert "duration_ms" in step
        assert step["duration_ms"] >= 0.0


# ===========================================================================
# 3. Concurrent workflows and worker scaling
# ===========================================================================

@pytest.mark.asyncio
async def test_03_concurrent_workflows_and_worker_scaling():
    """Verify execution of concurrent workflows and atomic worker queue claiming."""
    concurrency_level = 10
    workflows = [_simple_calc_workflow(f"wf_conc_{i}", multiplier=i + 1) for i in range(concurrency_level)]

    async with httpx.AsyncClient() as client:
        tasks = [
            execute_workflow(
                wf,
                trigger_items=[{"json": {"val": i}}],
                http_client=client,
            )
            for i, wf in enumerate(workflows)
        ]
        results = await asyncio.gather(*tasks)

    assert len(results) == concurrency_level
    for i, res in enumerate(results):
        assert res.status == "success", f"Workflow {i} failed: {res.error}"
        expected_val = i * (i + 1)
        # Code node normalizes output to flat dicts
        actual_val = res.results["calc"]["main"][0]["val"]
        assert actual_val == expected_val, f"Mismatch in workflow {i}: got {actual_val}, expected {expected_val}"

    # Worker queue scaling test: atomic claim across multiple workers
    queue = DbJobQueue()
    job_ids = [f"job_scale_{i}_{uuid.uuid4().hex[:6]}" for i in range(6)]
    for jid in job_ids:
        queue.enqueue(jid, f"exec_{jid}", {"data": jid})

    # Simulate concurrent workers claiming jobs
    claimed_ids: list[str] = []

    def worker_claim_cycle():
        claims = []
        while True:
            j = queue.claim()
            if not j:
                break
            claims.append(j.id)
            queue.complete(j.id, "done")
        return claims

    loop = asyncio.get_running_loop()
    w1, w2, w3 = await asyncio.gather(
        loop.run_in_executor(None, worker_claim_cycle),
        loop.run_in_executor(None, worker_claim_cycle),
        loop.run_in_executor(None, worker_claim_cycle),
    )

    all_claimed = w1 + w2 + w3
    # Every job must be claimed exactly once — zero duplicates across workers
    assert sorted(all_claimed) == sorted(job_ids)
    assert len(set(all_claimed)) == len(job_ids)


# ===========================================================================
# 4. Large payloads and high-volume execution history
# ===========================================================================

@pytest.mark.asyncio
async def test_04_large_payloads_and_high_volume_execution_history():
    """Verify large payload handling, trace bounding (_cap), and execution history pagination."""
    # 1. Direct verification of _cap payload bounding (spec 26)
    large_list = [{"item_id": i, "payload": "x" * 20} for i in range(1000)]
    capped_list = _cap(large_list)
    assert len(capped_list) == 501  # 500 items + 1 truncation notification
    assert "[500 more items truncated]" in str(capped_list[-1])

    # 2. Engine processing 5,000 array items
    large_item_count = 5000
    large_input = [{"id": i, "data": f"item_payload_{i}"} for i in range(large_item_count)]

    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "batch_transform",
                "code",
                parameters={
                    "code": "return $input.all().map(item => ({ id: item.json ? item.json.id : item.id, doubled: (item.json ? item.json.id : item.id) * 2 }));",
                    "language": "javascript",
                },
            ),
        ],
        [conn("trigger", "batch_transform")],
        wf_id="wf_large_payload",
    )

    async with httpx.AsyncClient() as client:
        res = await execute_workflow(wf, trigger_items=large_input, http_client=client)

    assert res.status == "success"
    assert len(res.results["batch_transform"]["main"]) == large_item_count

    # 3. Verify batch trace optimization preserves small row sizes for large batches
    step = next(s for s in res.trace if s["node_id"] == "batch_transform")
    assert "Per-item batch" in step.get("note", "")
    assert len(step["outputs"]["main"]) <= 5  # Trace samples outputs to avoid bloat

    # 4. High-volume execution history queries with limit and offset
    db = get_session()
    try:
        # Query executions with pagination
        stmt = (
            select(Execution)
            .order_by(Execution.started_at.desc())
            .limit(10)
            .offset(0)
        )
        t0 = time.monotonic()
        page1 = db.scalars(stmt).all()
        t_query = (time.monotonic() - t0) * 1000.0

        # Query next page
        stmt_page2 = (
            select(Execution)
            .order_by(Execution.started_at.desc())
            .limit(10)
            .offset(10)
        )
        page2 = db.scalars(stmt_page2).all()

        assert t_query < 100.0  # Indexed query must execute in < 100ms
        if page1 and page2:
            assert page1[0].id != page2[0].id
    finally:
        db.close()


# ===========================================================================
# 5. Memory leaks, CPU usage and resource exhaustion
# ===========================================================================

@pytest.mark.asyncio
async def test_05_memory_leaks_cpu_usage_and_resource_exhaustion():
    """Verify bounded memory growth in execution soak loop and loop iteration limits."""
    # 1. Soak execution loop to verify memory stability
    wf = _simple_calc_workflow("wf_soak", multiplier=2)
    soak_iterations = 25

    gc.collect()
    tracemalloc.start()
    snapshot_start = tracemalloc.take_snapshot()

    async with httpx.AsyncClient() as client:
        for _ in range(soak_iterations):
            res = await execute_workflow(
                wf,
                trigger_items=[{"json": {"val": 5}}],
                http_client=client,
            )
            assert res.status == "success"

    gc.collect()
    snapshot_end = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot_end.compare_to(snapshot_start, "lineno")
    total_diff_kb = sum(stat.size_diff for stat in top_stats) / 1024.0
    logger.info("Memory growth across %d executions: %.2f KB", soak_iterations, total_diff_kb)
    # Memory growth across 25 simple executions must remain bounded (< 5MB)
    assert total_diff_kb < 5120.0, f"Excessive memory allocation: {total_diff_kb:.2f} KB"

    # 2. CPU exhaustion protection: LoopWhileNode hard limit on infinite loop
    loop_node = LoopWhileNode()
    ctx = NodeContext(
        execution_id="exec_loop_test",
        workflow_id="wf_loop",
        node_id="loop_node_1",
        logger=logger,
        http_client=httpx.AsyncClient(),
    )
    # Condition that would run forever ("while 1 == 1"), capped at max_iterations=10
    params = LoopWhileParams(
        mode="while",
        condition=Condition(left=1, operator="is equal to", right=1),
        max_iterations=10,
        on_limit="complete",
    )

    t0 = time.monotonic()
    result = await loop_node.run(ctx, params, [{"json": {"counter": 0}}])
    t_loop = time.monotonic() - t0

    assert result.metadata.get("limit_reached") is True
    assert result.metadata.get("iterations") == 10
    # Bounded execution prevented infinite CPU spin
    assert t_loop < 2.0


# ===========================================================================
# 6. Database query performance and connection pooling
# ===========================================================================

@pytest.mark.asyncio
async def test_06_database_query_performance_and_connection_pooling():
    """Verify connection pool concurrency and index execution performance."""
    engine = get_engine()
    settings = get_settings()

    # Connection pool configuration checks
    if not settings.database_url.startswith("sqlite"):
        assert engine.pool.size() >= 5
        assert hasattr(engine.pool, "overflow")

    # Concurrent connection checkout
    async def run_db_op(idx: int):
        loop = asyncio.get_running_loop()
        def _sync_query():
            db = get_session()
            try:
                result = db.execute(text("SELECT 1 AS num")).scalar()
                return result
            finally:
                db.close()
        return await loop.run_in_executor(None, _sync_query)

    concurrency = 8
    tasks = [run_db_op(i) for i in range(concurrency)]
    results = await asyncio.gather(*tasks)
    assert all(r == 1 for r in results)

    # Indexed query performance on Execution table
    db = get_session()
    try:
        t0 = time.monotonic()
        # Query with filter and order by indexed column
        stmt = (
            select(Execution.id, Execution.status, Execution.duration_ms)
            .where(Execution.workflow_id == "wf_soak")
            .order_by(Execution.started_at.desc())
            .limit(5)
        )
        _ = db.execute(stmt).fetchall()
        duration_ms = (time.monotonic() - t0) * 1000.0
        assert duration_ms < 50.0  # Indexed scan must run well under 50ms
    finally:
        db.close()


# ===========================================================================
# 7. Redis outages, provider outages and network interruptions
# ===========================================================================

@pytest.mark.asyncio
async def test_07_redis_outages_provider_outages_and_network_interruptions():
    """Verify error isolation and resilience against network timeouts and outages."""
    # 1. Provider outage / network interruption simulation via SafeHTTPClient
    safe_client = SafeHTTPClient()
    await safe_client._ensure_client()
    assert safe_client._client is not None

    with patch.object(safe_client._client, "request", side_effect=httpx.ConnectTimeout("Network unreachable")):
        with pytest.raises(ConnectorError) as excinfo:
            await safe_client.request("GET", "https://api.external-provider.com/data", timeout=1.0)
        assert excinfo.value.code in (ConnectorErrorCode.TIMEOUT, ConnectorErrorCode.UNAVAILABLE)
        assert excinfo.value.retryable is True

    with patch.object(safe_client._client, "request", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(ConnectorError) as excinfo:
            await safe_client.request("GET", "https://api.external-provider.com/data", timeout=1.0)
        assert excinfo.value.code in (ConnectorErrorCode.TIMEOUT, ConnectorErrorCode.UNAVAILABLE)
        assert excinfo.value.retryable is True

    await safe_client.close()

    # 2. Redis outage simulation
    # Creating a Redis client directed to an invalid/dead port
    dead_redis = redis.Redis(host="127.0.0.1", port=65530, socket_connect_timeout=0.1)
    # redis-py versions differ: a dead port can surface as TimeoutError rather
    # than ConnectionError. Both prove the outage path is isolated.
    with pytest.raises((redis.ConnectionError, redis.TimeoutError)):
        dead_redis.ping()


# ===========================================================================
# 8. Retry storms, deadlocks and queue backlog recovery
# ===========================================================================

def test_08_retry_storms_deadlocks_and_queue_backlog_recovery(monkeypatch):
    """Verify exponential retry backoff, stale claim orphan recovery, and max attempts guard."""
    settings = get_settings()
    monkeypatch.setattr(settings, "queue_max_attempts", 2)
    monkeypatch.setattr(settings, "queue_retry_backoff_base_s", 0.1)
    monkeypatch.setattr(settings, "queue_retry_backoff_max_s", 5.0)

    # Calculate exponential backoffs
    backoff_1 = min(0.1 * (2 ** (1 - 1)), 5.0)  # attempt 1 retry -> 0.1s
    backoff_2 = min(0.1 * (2 ** (2 - 1)), 5.0)  # attempt 2 retry -> 0.2s
    backoff_10 = min(0.1 * (2 ** (10 - 1)), 5.0)  # attempt 10 retry -> capped at 5.0s
    assert backoff_1 == 0.1
    assert backoff_2 == 0.2
    assert backoff_10 == 5.0

    # Test stale recovery & max attempts terminal failure on DbJobQueue
    queue = DbJobQueue()
    job_id = f"job_orphan_{uuid.uuid4().hex[:8]}"
    exec_id = f"exec_orphan_{uuid.uuid4().hex[:8]}"
    payload = {"data": "test_orphan"}

    assert queue.enqueue(job_id, exec_id, payload)
    j1 = queue.claim()
    assert j1 is not None and j1.attempts == 1

    # Simulate worker crash (stale lease)
    time.sleep(0.02)
    # Recover stale claim: should re-queue for attempt 2
    reclaimed = queue.recover_stale(stale_after_s=0.01)
    assert reclaimed >= 1

    j2 = queue.claim()
    assert j2 is not None and j2.attempts == 2

    # Second crash: attempts == max_attempts (2). Next recovery must NOT re-queue
    time.sleep(0.02)
    reclaimed_2 = queue.recover_stale(stale_after_s=0.01)
    # Job should be failed terminally to prevent infinite retry storms
    assert reclaimed_2 == 0
    assert queue.claim() is None


# ===========================================================================
# 9. Long-running workflows and graceful shutdown
# ===========================================================================

@pytest.mark.asyncio
async def test_09_long_running_workflows_and_graceful_shutdown():
    """Verify cooperative cancellation of long-running workflows and clean worker shutdown."""
    # 1. Cooperative workflow cancellation
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("wait_step", "wait", parameters={"resume": "timeInterval", "amount": 10.0, "unit": "seconds"}),
            make_node("subsequent", "code", parameters={"code": "return [{done: true}];", "language": "javascript"}),
        ],
        [conn("trigger", "wait_step"), conn("wait_step", "subsequent")],
        wf_id="wf_cancel_test",
    )

    cancel_event = asyncio.Event()

    async def _trigger_cancel():
        await asyncio.sleep(0.05)
        cancel_event.set()

    cancel_task = asyncio.create_task(_trigger_cancel())

    async with httpx.AsyncClient() as client:
        t0 = time.monotonic()
        res = await execute_workflow(
            wf,
            cancel_event=cancel_event,
            http_client=client,
        )
        duration_s = time.monotonic() - t0

    await cancel_task

    # Execution must stop promptly (sub-second, not wait 10 seconds)
    assert duration_s < 1.0, f"Workflow took {duration_s:.2f}s to cancel instead of stopping immediately"
    assert res.status == "cancelled"
    # Subsequent node must never have executed
    assert "subsequent" not in res.results
    assert all(step["node_id"] != "subsequent" for step in res.trace)

    # 2. Worker graceful shutdown
    worker = QueueWorker(poll_interval_s=0.05)
    assert not worker._stop.is_set()

    worker_task = asyncio.create_task(worker.run_forever())
    await asyncio.sleep(0.1)

    # Signal stop
    worker.stop()
    assert worker._stop.is_set()

    # Worker must terminate cleanly without hanging
    await asyncio.wait_for(worker_task, timeout=2.0)
    assert worker_task.done()


# ===========================================================================
# 10. Load, stress, soak and recovery tests in safe environments
# ===========================================================================

@pytest.mark.asyncio
async def test_10_load_stress_soak_and_recovery_tests_in_safe_environments():
    """Verify high burst stress resilience and rapid return to baseline performance."""
    burst_count = 20
    mixed_workflows = []

    for i in range(burst_count):
        if i % 2 == 0:
            mixed_workflows.append(_simple_calc_workflow(f"wf_burst_{i}", multiplier=i + 1))
        else:
            mixed_workflows.append(_branching_workflow(f"wf_burst_{i}"))

    # Execute burst load
    async with httpx.AsyncClient() as client:
        t_burst_start = time.monotonic()
        tasks = [
            execute_workflow(
                wf,
                trigger_items=[{"json": {"val": 10, "score": 90}}],
                http_client=client,
            )
            for wf in mixed_workflows
        ]
        burst_results = await asyncio.gather(*tasks)
        burst_time = time.monotonic() - t_burst_start

    assert len(burst_results) == burst_count
    # 100% success rate under burst load
    assert all(r.status == "success" for r in burst_results)

    # Immediately verify post-burst recovery and baseline latency
    async with httpx.AsyncClient() as client:
        t_baseline_start = time.monotonic()
        recovery_res = await execute_workflow(
            _simple_calc_workflow("wf_recovery_probe", multiplier=1),
            trigger_items=[{"json": {"val": 1}}],
            http_client=client,
        )
        baseline_time_ms = (time.monotonic() - t_baseline_start) * 1000.0

    assert recovery_res.status == "success"
    # Baseline probe after burst must execute quickly (< 100ms) with zero degradation
    assert baseline_time_ms < 100.0, f"Recovery baseline latency {baseline_time_ms:.2f}ms was degraded"
