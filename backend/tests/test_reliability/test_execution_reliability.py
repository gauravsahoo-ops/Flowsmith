"""Reliability, failure-injection, and engine resilience tests (Phase 3).

Comprehensive verification of:
1. Redis & DB Queue Reliability (eviction safety, duplicate delivery, atomic claiming, expired leases, retry backoff, dead-letter poison pills).
2. Workflow Engine & DAG Reliability (cycle tolerance, deterministic ordering, parallel branch state integrity, loop limits, sub-workflow depth recursion guards).
3. Lifecycle & Safety Guards (import/duplicate safety, non-execution on import, trigger disabling, credential stripping).
4. Distributed Coordination (advisory locks, skip-if-running scheduler guard).
5. Cancellation & Cooperative Recovery (CAS state transition race guards, durable approval pause/resume checkpointing).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db import get_session
from app.engine.errors import NodeExecutionError, WorkflowValidationError
from app.engine.executor import ExecutionResult, execute_workflow
from app.engine.graph import build_graph, topological_sort, validate_graph
from app.models import Execution, Job, ScheduleTrigger, User, WorkflowRecord
from app.models.job import DONE, FAILED, QUEUED
from app.nodes.loop_while import LoopWhileNode, LoopWhileParams
from app.nodes.sub_workflow import MAX_SUBWORKFLOW_DEPTH, SubWorkflowNode, SubWorkflowParams
from app.queue import redis_queue as rq
from app.queue.db_queue import DbJobQueue
from app.queue.worker import QueueWorker
from app.schemas.workflow import Connection, Workflow, WorkflowNode
from app.scheduler import SCHEDULER_LOCK_KEY, Scheduler


# ==============================================================================
# Fixtures and Helpers
# ==============================================================================

def _make_payload(workflow_id: str = "wf_rel_1", name: str = "Reliability Test") -> dict[str, Any]:
    return {
        "workflow_data": {
            "id": workflow_id,
            "name": name,
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "parameters": {}},
                {"id": "noop", "type": "noop", "parameters": {}},
            ],
            "connections": [{"source": "trig", "target": "noop", "sourceHandle": "main", "targetHandle": "main"}],
        },
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": workflow_id,
        "version": 1,
    }


@pytest.fixture
def fake_redis_queue(monkeypatch):
    """Hermetic RedisJobQueue instance backed by fakeredis."""
    server = fakeredis.FakeServer()
    r = fakeredis.FakeRedis(server=server, decode_responses=True)

    class TestRedisQueue(rq.RedisJobQueue):
        def __init__(self) -> None:
            self._conn = r
            self.verify_eviction_policy()

    monkeypatch.setattr("app.queue.redis_queue._now", lambda: str(time.time()))
    return TestRedisQueue()


@pytest.fixture
def db_session_clean():
    """Provides a clean DB session for test setup."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# 1. Redis Queue Configuration, Eviction Safety & Idempotency
# ==============================================================================

class TestRedisQueueReliability:
    """Verifies Redis queue eviction safety, idempotency, lease recovery, and poison-job handling."""

    def test_redis_eviction_policy_verification(self):
        """Verify that RedisJobQueue inspects eviction policy and flags unsafe configurations."""
        server = fakeredis.FakeServer()
        r = fakeredis.FakeRedis(server=server, decode_responses=True)

        class TestRedisQueue(rq.RedisJobQueue):
            def __init__(self, conn) -> None:
                self._conn = conn
                self.verification = self.verify_eviction_policy()

        # Case A: allkeys-lru (unsafe — can silently evict queues)
        with patch.object(r, "config_get", return_value={"maxmemory-policy": "allkeys-lru"}):
            q_unsafe = TestRedisQueue(r)
            assert q_unsafe.verification["policy"] == "allkeys-lru"
            assert q_unsafe.verification["safe"] is False

        # Case B: noeviction (safe — durable queue policy)
        with patch.object(r, "config_get", return_value={"maxmemory-policy": "noeviction"}):
            q_safe = TestRedisQueue(r)
            assert q_safe.verification["policy"] == "noeviction"
            assert q_safe.verification["safe"] is True

    def test_redis_duplicate_delivery_idempotency(self, fake_redis_queue):
        """Duplicate enqueues of the same execution_id are rejected by the SADD guard."""
        q = fake_redis_queue
        exec_id = "exec_idemp_101"
        payload = _make_payload("wf_idemp", "Idempotency Flow")

        # First delivery succeeds
        assert q.enqueue("job_first", exec_id, payload) is True
        assert bool(q._conn.sismember(rq.EXECS_KEY, exec_id)) is True

        # Second delivery (e.g., duplicate transport or retry) must be rejected
        assert q.enqueue("job_second", exec_id, payload) is False

        # Exactly 1 job exists in queue
        assert q._conn.llen(rq.QUEUE_KEY) == 1
        claimed = q.claim()
        assert claimed is not None
        assert claimed.execution_id == exec_id
        assert q.claim() is None

        # Clean completion releases idempotency guard
        q.complete(claimed.id, "done")
        assert not bool(q._conn.sismember(rq.EXECS_KEY, exec_id))

    def test_redis_stale_claim_recovery_and_retry_backoff(self, monkeypatch, fake_redis_queue):
        """A crashed worker holding a job is detected via stale heartbeat and rescheduled with backoff."""
        q = fake_redis_queue
        monkeypatch.setattr(get_settings(), "queue_max_attempts", 5)
        monkeypatch.setattr(get_settings(), "queue_retry_backoff_base_s", 0.1)
        monkeypatch.setattr(get_settings(), "queue_retry_backoff_max_s", 2.0)

        exec_id = "exec_stale_102"
        q.enqueue("job_stale", exec_id, _make_payload())

        # Worker 1 claims job
        claimed = q.claim()
        assert claimed.attempts == 1
        assert q._conn.llen(rq.PROCESSING_KEY) == 1

        # Simulate crash: time elapses without heartbeat refresh
        time.sleep(0.02)
        recovered = q.recover_stale(stale_after_s=0.01)
        assert recovered == 1

        # Immediately after recovery attempt 1, job was re-queued (0s initial delay)
        claimed_2 = q.claim()
        assert claimed_2 is not None
        assert claimed_2.attempts == 2

        # Simulate second crash
        time.sleep(0.02)
        recovered_2 = q.recover_stale(stale_after_s=0.01)
        assert recovered_2 == 1

        # Now job is in scheduled zset awaiting backoff
        assert q.claim() is None
        assert q._conn.zcard(rq.SCHEDULED_KEY) == 1

        # Wait for backoff to expire
        time.sleep(0.15)
        promoted = q.claim()
        assert promoted is not None
        assert promoted.attempts == 3

    def test_redis_poison_job_max_attempts_dead_letter(self, monkeypatch, fake_redis_queue):
        """Jobs repeatedly crashing workers are terminally failed when reaching max_attempts."""
        q = fake_redis_queue
        monkeypatch.setattr(get_settings(), "queue_max_attempts", 2)

        exec_id = "exec_poison_103"
        q.enqueue("job_poison", exec_id, _make_payload())

        # Attempt 1
        job1 = q.claim()
        assert job1.attempts == 1

        # Crash 1 -> recovered to attempt 2
        time.sleep(0.02)
        assert q.recover_stale(stale_after_s=0.01) == 1

        # Attempt 2
        job2 = q.claim()
        assert job2.attempts == 2

        # Crash 2 -> attempts reached cap (2); should NOT be re-queued
        time.sleep(0.02)
        recovered = q.recover_stale(stale_after_s=0.01)
        assert recovered == 0  # 0 requeued

        # Job is removed from processing and marked failed
        assert q.claim() is None
        meta = q._conn.hgetall(rq._meta_key("job_poison"))
        assert meta.get("status") == "failed"
        assert "MAX_ATTEMPTS_EXCEEDED" in meta.get("error", "")


# ==============================================================================
# 2. Database Queue Reliability & Atomic Claiming
# ==============================================================================

class TestDatabaseQueueReliability:
    """Verifies PostgreSQL-backed transactional queue with SELECT FOR UPDATE SKIP LOCKED."""

    def test_db_queue_atomic_claim_and_skip_locked(self, db_session_clean):
        """DbJobQueue claims jobs atomically and safely without double-claims."""
        q = DbJobQueue()
        db = db_session_clean

        # Setup user, workflow, executions
        user = User(email=f"rel_db_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        wf = WorkflowRecord(
            id=f"wf_db_q_{int(time.time()*1000)}",
            user_id=user.id,
            name="DB Queue Test",
            data={"id": "wf", "nodes": [], "connections": []},
        )
        db.add(wf)
        db.flush()

        exec1 = Execution(
            id=f"exec_db_1_{int(time.time()*1000)}",
            workflow_id=wf.id,
            user_id=user.id,
            workflow_version=1,
            workflow_data=wf.data,
            trigger="manual",
            status="queued",
        )
        exec2 = Execution(
            id=f"exec_db_2_{int(time.time()*1000)}",
            workflow_id=wf.id,
            user_id=user.id,
            workflow_version=1,
            workflow_data=wf.data,
            trigger="manual",
            status="queued",
        )
        db.add_all([exec1, exec2])
        db.commit()

        # Enqueue two jobs
        assert q.enqueue(f"job_{exec1.id}", exec1.id, _make_payload(wf.id)) is True
        assert q.enqueue(f"job_{exec2.id}", exec2.id, _make_payload(wf.id)) is True

        # Claim job 1
        claimed1 = q.claim()
        assert claimed1 is not None
        assert claimed1.id == f"job_{exec1.id}"
        assert claimed1.attempts == 1

        # Claim job 2
        claimed2 = q.claim()
        assert claimed2 is not None
        assert claimed2.id == f"job_{exec2.id}"
        assert claimed2.attempts == 1

        # Queue is empty
        assert q.claim() is None

        # Clean up completed jobs
        q.complete(claimed1.id, "done")
        q.complete(claimed2.id, "done")

        row1 = db.get(Job, claimed1.id)
        assert row1.status == "done"

    def test_db_queue_duplicate_enqueue_rejected(self, db_session_clean):
        """Duplicate enqueue of the same execution_id returns False."""
        q = DbJobQueue()
        db = db_session_clean

        user = User(email=f"dup_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        wf = WorkflowRecord(
            id=f"wf_dup_{int(time.time()*1000)}",
            user_id=user.id,
            name="Duplicate Test",
            data={"id": "wf", "nodes": [], "connections": []},
        )
        db.add(wf)
        db.flush()
        exec_id = f"exec_dup_{int(time.time()*1000)}"
        db.add(Execution(
            id=exec_id, workflow_id=wf.id, user_id=user.id, workflow_version=1,
            workflow_data=wf.data, trigger="manual", status="queued",
        ))
        db.commit()

        # Enqueue once
        assert q.enqueue(f"job_{exec_id}", exec_id, _make_payload(wf.id)) is True
        # Enqueue twice
        assert q.enqueue(f"job_alt_{exec_id}", exec_id, _make_payload(wf.id)) is False

        claimed = q.claim()
        assert claimed is not None
        assert claimed.execution_id == exec_id
        q.complete(claimed.id, "done")


# ==============================================================================
# 3. Workflow Engine, DAG Validation, Cycles, and Execution Limits
# ==============================================================================

class TestWorkflowEngineReliability:
    """Verifies graph validation, cycle tolerance, deterministic ordering, and execution limits."""

    def test_cycle_tolerance_and_deterministic_topological_sort(self):
        """Visual loop cycles are tolerated without crashing; ordering is deterministic."""
        nodes = [
            WorkflowNode(id="start", type="manual_trigger", parameters={}),
            WorkflowNode(id="node_a", type="noop", parameters={}),
            WorkflowNode(id="node_b", type="noop", parameters={}),
            WorkflowNode(id="node_c", type="noop", parameters={}),
        ]
        # Feedback cycle: a -> b -> c -> a, with start -> a
        connections = [
            Connection(source="start", target="node_a", sourceHandle="main", targetHandle="main"),
            Connection(source="node_a", target="node_b", sourceHandle="main", targetHandle="main"),
            Connection(source="node_b", target="node_c", sourceHandle="main", targetHandle="main"),
            Connection(source="node_c", target="node_a", sourceHandle="main", targetHandle="main"),
        ]
        wf = Workflow(id="wf_cycle", name="Cycle Flow", nodes=nodes, connections=connections)

        # Graph validation passes without raising WorkflowValidationError
        graph = build_graph(wf)
        validate_graph(wf, graph, validate_params=False)

        # Topological sort terminates deterministically
        order = topological_sort(graph)
        assert len(order) == 4
        assert order[0] == "start"
        assert set(order) == {"start", "node_a", "node_b", "node_c"}

    @pytest.mark.asyncio
    async def test_cycle_workflow_executes_each_node_at_most_once(self):
        """Cyclic workflow graph runs all nodes with cycle-breaking semantics (at most once)."""
        nodes = [
            WorkflowNode(id="trig", type="manual_trigger", parameters={}),
            WorkflowNode(id="step1", type="set_data", parameters={"values": {"v": 1}}),
            WorkflowNode(id="step2", type="set_data", parameters={"values": {"v": 2}}),
        ]
        connections = [
            Connection(source="trig", target="step1", sourceHandle="main", targetHandle="main"),
            Connection(source="step1", target="step2", sourceHandle="main", targetHandle="main"),
            Connection(source="step2", target="step1", sourceHandle="main", targetHandle="main"),
        ]
        wf = Workflow(id="wf_exec_cycle", name="Cycle Exec", nodes=nodes, connections=connections)

        res = await execute_workflow(workflow=wf, trigger_items=[{"input": "ok"}])
        assert res.status == "success"
        # All 3 nodes ran exactly once
        assert set(res.results.keys()) == {"trig", "step1", "step2"}
        assert len(res.trace) == 3

    @pytest.mark.asyncio
    async def test_loop_while_hard_iteration_cap_terminates_run(self):
        """LoopWhileNode terminates non-terminating loops at max_iterations with LOOP_LIMIT_EXCEEDED."""
        node = LoopWhileNode()
        ctx = MagicMock()
        ctx.is_cancelled.return_value = False
        ctx.cancel_event = None
        ctx.node_id = "loop_node"

        params = LoopWhileParams(
            condition={"left": "{{ $json.never }}", "operator": "is equal to", "right": "true"},
            mode="until",  # never reaches true -> will hit max_iterations
            max_iterations=15,
            delay_seconds=0.0,
            on_limit="fail",
        )

        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [{"never": "false"}])

        assert exc_info.value.code == "LOOP_LIMIT_EXCEEDED"
        assert "exceeded max_iterations=15" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_subworkflow_nesting_depth_guard(self):
        """Sub-workflow nesting beyond MAX_SUBWORKFLOW_DEPTH is blocked."""
        sub_node = SubWorkflowNode()
        ctx = MagicMock()
        ctx.execution_depth = MAX_SUBWORKFLOW_DEPTH  # already at maximum depth
        ctx.node_id = "sub_node_1"

        params = SubWorkflowParams(source="defineBelow", workflow_json={"nodes": [], "connections": []})

        with pytest.raises(NodeExecutionError) as exc_info:
            await sub_node.run(ctx, params, [{}])

        assert exc_info.value.code == "SUBWORKFLOW_DEPTH_EXCEEDED"
        assert "MAX_SUBWORKFLOW_DEPTH" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_parallel_branch_concurrency_state_integrity(self):
        """Parallel fan-out execution preserves output and trace integrity without corruption."""
        nodes = [
            WorkflowNode(id="trig", type="manual_trigger", parameters={}),
            WorkflowNode(id="branch_1", type="set_data", parameters={"values": {"b1": 100}}),
            WorkflowNode(id="branch_2", type="set_data", parameters={"values": {"b2": 200}}),
            WorkflowNode(id="branch_3", type="set_data", parameters={"values": {"b3": 300}}),
            WorkflowNode(id="branch_4", type="set_data", parameters={"values": {"b4": 400}}),
            WorkflowNode(id="merge", type="noop", parameters={}, settings={"merge_mode": "wait_for_all"}),
        ]
        connections = [
            Connection(source="trig", target="branch_1", sourceHandle="main", targetHandle="main"),
            Connection(source="trig", target="branch_2", sourceHandle="main", targetHandle="main"),
            Connection(source="trig", target="branch_3", sourceHandle="main", targetHandle="main"),
            Connection(source="trig", target="branch_4", sourceHandle="main", targetHandle="main"),
            Connection(source="branch_1", target="merge", sourceHandle="main", targetHandle="main"),
            Connection(source="branch_2", target="merge", sourceHandle="main", targetHandle="main"),
            Connection(source="branch_3", target="merge", sourceHandle="main", targetHandle="main"),
            Connection(source="branch_4", target="merge", sourceHandle="main", targetHandle="main"),
        ]
        wf = Workflow(
            id="wf_parallel",
            name="Parallel Flow",
            nodes=nodes,
            connections=connections,
            settings={"max_parallelism": 4},
        )

        res = await execute_workflow(workflow=wf, trigger_items=[{}])
        assert res.status == "success"
        # All branches completed
        for b in ("branch_1", "branch_2", "branch_3", "branch_4", "merge"):
            assert b in res.results
            assert res.results[b]["main"] is not None

        # Trace steps are sorted chronologically
        started_times = [s["started_at"] for s in res.trace]
        assert started_times == sorted(started_times)


# ==============================================================================
# 4. Workflow Import & Duplication Safety
# ==============================================================================

class TestImportAndDuplicateSafety:
    """Ensures workflows are never automatically executed upon import or duplication,
    credentials and runtime state are stripped, and triggers remain disabled."""

    def test_import_workflow_is_draft_inactive_and_zero_executions(self, db_session_clean):
        from app.api.workflows import import_workflow

        db = db_session_clean
        user = User(email=f"import_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.commit()

        # Import payload with credentials and active state
        import_payload = {
            "name": "Imported Webhook Flow",
            "active": True,  # Attacker payload trying to auto-activate
            "status": "published",
            "nodes": [
                {
                    "id": "wh1",
                    "type": "webhook",
                    "parameters": {"path": "my-hook-123", "http_method": "POST"},
                },
                {
                    "id": "step1",
                    "type": "noop",
                    "parameters": {},
                    "credentials": {"salesforce": "cred_secret_123"},
                },
            ],
            "connections": [{"source": "wh1", "target": "step1", "sourceHandle": "main", "targetHandle": "main"}],
        }

        resp = import_workflow(import_payload, user=user, db=db)
        imported_wf = resp["data"]
        wf_id = imported_wf["id"]

        # 1. State must be Draft and Inactive
        rec = db.get(WorkflowRecord, wf_id)
        assert rec.active is False
        assert rec.data.get("status") == "draft"

        # 2. Webhook path must be regenerated with entropy to prevent hijacking
        wh_node = next(n for n in rec.data["nodes"] if n["type"] == "webhook")
        assert wh_node["parameters"]["path"] != "my-hook-123"
        assert len(wh_node["parameters"]["path"]) >= 24

        # 3. Exactly zero executions must have been created or queued
        exec_count = db.scalar(
            select(Execution).where(Execution.workflow_id == wf_id)
        )
        assert exec_count is None

    def test_duplicate_workflow_strips_credentials_and_never_executes(self, db_session_clean):
        from app.api.workflows import duplicate_workflow

        db = db_session_clean
        user = User(email=f"dup_safe_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.commit()

        # Create original workflow with credentials
        orig_wf = WorkflowRecord(
            id=f"wf_orig_{int(time.time()*1000)}",
            user_id=user.id,
            name="Prod Pipeline",
            active=True,
            data={
                "id": "wf_orig",
                "name": "Prod Pipeline",
                "status": "published",
                "active": True,
                "nodes": [
                    {
                        "id": "n1",
                        "type": "schedule",
                        "parameters": {"cron": "0 * * * *", "timezone": "UTC"},
                    },
                    {
                        "id": "n2",
                        "type": "http_request",
                        "parameters": {"url": "https://api.example.com"},
                        "credentials": {"http": "cred_sensitive_key"},
                    },
                ],
                "connections": [{"source": "n1", "target": "n2", "sourceHandle": "main", "targetHandle": "main"}],
            },
        )
        db.add(orig_wf)
        db.commit()

        resp = duplicate_workflow(orig_wf.id, user=user, db=db)
        dup_wf = resp["data"]
        dup_id = dup_wf["id"]

        # Duplicate must be distinct, inactive, and draft
        assert dup_id != orig_wf.id
        dup_rec = db.get(WorkflowRecord, dup_id)
        assert dup_rec.active is False
        assert dup_rec.data.get("status") == "draft"
        assert "(Copy)" in dup_rec.name

        # Credentials must be stripped
        http_node = next(n for n in dup_rec.data["nodes"] if n["id"] == "n2")
        assert not http_node.get("credentials")

        # Zero executions created
        exec_count = db.scalar(select(Execution).where(Execution.workflow_id == dup_id))
        assert exec_count is None


# ==============================================================================
# 5. Distributed Scheduler Locking & Overlapping Execution Guards
# ==============================================================================

class TestSchedulerReliability:
    """Verifies advisory locking and overlapping run suppression."""

    def test_scheduler_skips_when_workflow_already_running(self, db_session_clean):
        """Spec 8.4: never start a second execution if the workflow is queued or running."""
        db = db_session_clean
        user = User(email=f"sched_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.flush()

        wf = WorkflowRecord(
            id=f"wf_sched_{int(time.time()*1000)}",
            user_id=user.id,
            name="Sched Flow",
            active=True,
            data={"id": "wf_sched", "nodes": [], "connections": []},
        )
        db.add(wf)
        db.flush()

        # Add active running execution
        active_exec = Execution(
            id=f"exec_running_{int(time.time()*1000)}",
            workflow_id=wf.id,
            user_id=user.id,
            workflow_version=1,
            workflow_data=wf.data,
            trigger="schedule",
            status="running",
        )
        db.add(active_exec)

        rule = ScheduleTrigger(
            id=f"rule_{int(time.time()*1000)}",
            workflow_id=wf.id,
            node_id="sched_1",
            user_id=user.id,
            workflow_version=1,
            workflow_data=wf.data,
            cron="* * * * *",
            status="active",
        )
        db.add(rule)
        db.commit()

        sched = Scheduler()
        # Fire should return False because workflow is already running
        started = sched._try_start(rule, {"timestamp": datetime.now(UTC).isoformat()}, db, datetime.now(UTC))
        assert started is False

        # Mark execution finished
        active_exec.status = "success"
        db.commit()

        # Now scheduling should be permitted (or succeed up to billing check)
        with patch("app.api.executions.start_execution", return_value="exec_new") as mock_start:
            started_after = sched._try_start(rule, {"timestamp": datetime.now(UTC).isoformat()}, db, datetime.now(UTC))
            assert started_after is True
            mock_start.assert_called_once()

    def test_scheduler_distributed_advisory_lock_single_runner(self):
        """Scheduler acquires PostgreSQL advisory lock key 0x7EED01; failure to acquire skips tick."""
        sched = Scheduler()
        # Mock _try_acquire_lock returning False (another replica holds lock)
        with patch.object(sched, "_try_acquire_lock", return_value=(None, False)):
            fired = sched._tick_sync(datetime.now(UTC))
            # Must skip tick completely without running queries or double-firing
            assert fired == 0


# ==============================================================================
# 6. Cancellation CAS Guards & Durable Approval Checkpoints
# ==============================================================================

class TestCancellationAndCheckpointing:
    """Verifies CAS cancellation races and durable human approval pause/resume checkpointing."""

    def test_cancellation_cas_state_transition(self, db_session_clean):
        """Cancellation endpoint performs CAS transition (running -> cancelling, queued -> cancelled)."""
        from app.api.executions import cancel_execution

        db = db_session_clean
        user = User(email=f"cancel_cas_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.flush()

        wf = WorkflowRecord(
            id=f"wf_cancel_{int(time.time()*1000)}",
            user_id=user.id,
            name="Cancel Flow",
            data={},
        )
        db.add(wf)
        db.flush()

        # Scenario A: Queued execution cancelled directly to cancelled
        exec_queued = Execution(
            id=f"exec_q_cancel_{int(time.time()*1000)}",
            workflow_id=wf.id,
            user_id=user.id,
            workflow_version=1,
            workflow_data={},
            trigger="manual",
            status="queued",
        )
        db.add(exec_queued)
        db.commit()

        res_q = cancel_execution(exec_queued.id, user=user, db=db)
        assert res_q["data"]["status"] == "cancelled"
        assert db.get(Execution, exec_queued.id).status == "cancelled"

        # Scenario B: Running execution transitioned to cancelling
        exec_running = Execution(
            id=f"exec_r_cancel_{int(time.time()*1000)}",
            workflow_id=wf.id,
            user_id=user.id,
            workflow_version=1,
            workflow_data={},
            trigger="manual",
            status="running",
        )
        db.add(exec_running)
        db.commit()

        res_r = cancel_execution(exec_running.id, user=user, db=db)
        assert res_r["data"]["status"] == "cancelling"
        assert db.get(Execution, exec_running.id).status == "cancelling"

        # Scenario C: Calling cancel on already cancelling triggers immediate force cancel
        res_force = cancel_execution(exec_running.id, user=user, db=db)
        assert res_force["data"]["status"] == "cancelled"
        assert db.get(Execution, exec_running.id).status == "cancelled"

    def test_human_approval_pause_checkpoint_and_resume(self, db_session_clean):
        """Execution in waiting_approval holds checkpoint in DB; resume safely re-enqueues."""
        from app.api.executions import resume_execution

        db = db_session_clean
        user = User(email=f"approval_{int(time.time()*1000)}@example.com", password_hash="x")
        db.add(user)
        db.flush()

        wf = WorkflowRecord(
            id=f"wf_apprv_{int(time.time()*1000)}",
            user_id=user.id,
            name="Approval Flow",
            data={"id": "wf_apprv", "nodes": [], "connections": []},
        )
        db.add(wf)
        db.flush()

        exec_apprv = Execution(
            id=f"exec_apprv_{int(time.time()*1000)}",
            workflow_id=wf.id,
            user_id=user.id,
            workflow_version=1,
            workflow_data=wf.data,
            trigger="manual",
            status="waiting_approval",
            pause_state={"node_id": "approve_node", "approvers": [user.id]},
            results={"outputs": {"prev_step": {"main": [{"amount": 500}]}}},
        )
        db.add(exec_apprv)
        db.commit()

        # Resume execution with approval
        with patch("app.api.executions.get_queue") as mock_get_q:
            mock_queue = MagicMock()
            mock_get_q.return_value = mock_queue

            resp = resume_execution(exec_apprv.id, approved=True, user=user, db=db)
            assert resp["data"]["status"] == "queued"

            # Check that job was re-enqueued with pre-seeded checkpoint payload
            mock_queue.requeue.assert_called_once()
            call_args = mock_queue.requeue.call_args[0]
            assert call_args[0] == exec_apprv.id
            payload = call_args[1]
            assert payload["_approval_data"]["approved"] is True
            assert payload["_approval_data"]["node_id"] == "approve_node"
            assert payload["_approval_data"]["approved_by"] == user.id
