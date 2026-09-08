"""Queue & worker audit tests (10 scenarios).

Covers: DB queue lifecycle, Redis queue (skip if unavailable),
duplicate enqueue idempotency, stale/timeout recovery, execution
lifecycle, crash recovery, concurrent enqueue, failed job status,
and retry behaviour.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.db import get_session
from app.models import Execution, Job, User, WorkflowRecord
from app.models.job import DONE, FAILED, QUEUED, CLAIMED
from app.queue import QueueJob, reset_queue, get_queue
from app.queue.db_queue import DbJobQueue
from app.queue.worker import QueueWorker, stop_embedded_consumer

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_payload_counter = 0


def _next_id() -> int:
    global _payload_counter
    _payload_counter += 1
    return _payload_counter


def _payload(name: str = "wf_1", wf_id: str = "wf_1") -> dict[str, Any]:
    return {
        "workflow_data": {"id": wf_id, "name": name, "nodes": [], "connections": []},
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": wf_id,
        "version": 1,
    }


def _simple_workflow(wf_id: str = "wf_audit") -> dict:
    return {
        "id": wf_id,
        "name": "Audit WF",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "set", "type": "set_data", "parameters": {"fields": {"ok": True}}},
        ],
        "connections": [{"source": "trigger", "target": "set"}],
        "settings": {},
    }


def _seed_user_and_workflow(user_id: int = 1, wf_id: str = "wf_audit") -> None:
    db = get_session()
    try:
        existing = db.get(User, user_id)
        if existing is None:
            db.add(User(id=user_id, email=f"audit_{user_id}@b.com", password_hash="x"))
        existing_wf = db.get(WorkflowRecord, wf_id)
        if existing_wf is None:
            db.add(WorkflowRecord(id=wf_id, user_id=user_id, name="A", data={}, active=False))
        db.commit()
    finally:
        db.close()


def _enqueue_simple(queue: DbJobQueue, exec_id: str, wf_id: str = "wf_audit",
                    user_id: int = 1) -> None:
    _seed_user_and_workflow(user_id, wf_id)
    db = get_session()
    try:
        db.add(Execution(
            id=exec_id,
            workflow_id=wf_id,
            user_id=user_id,
            workflow_version=1,
            workflow_data={"id": wf_id, "nodes": [], "connections": []},
            trigger="manual",
            trigger_data=[{}],
            status="queued",
        ))
        db.commit()
    finally:
        db.close()
    queue.enqueue(f"job_{exec_id}", exec_id, _payload(wf_id=wf_id))


def _job_row(job_id: str) -> Job:
    db = get_session()
    try:
        row = db.get(Job, job_id)
        assert row is not None
        return row
    finally:
        db.close()


def _exec_row(exec_id: str) -> Execution:
    db = get_session()
    try:
        rec = db.get(Execution, exec_id)
        assert rec is not None
        return rec
    finally:
        db.close()


def _queue() -> DbJobQueue:
    stop_embedded_consumer()
    return DbJobQueue()


# ---------------------------------------------------------------------------
# 1. DB QUEUE: enqueue -> claim -> complete lifecycle
# ---------------------------------------------------------------------------

def test_db_queue_lifecycle():
    queue = _queue()
    _seed_user_and_workflow(1, "wf_1")
    assert queue.enqueue("job_l1", "exec_l1", _payload())
    job = queue.claim()
    assert job is not None
    assert job.id == "job_l1"
    assert job.status == CLAIMED
    assert job.attempts == 1
    assert job.execution_id == "exec_l1"

    queue.complete(job.id, DONE)

    row = _job_row("job_l1")
    assert row.status == DONE
    assert row.finished_at is not None

    # Nothing left to claim
    assert queue.claim() is None


# ---------------------------------------------------------------------------
# 2. REDIS QUEUE: enqueue -> claim -> complete (skip if no Redis)
# ---------------------------------------------------------------------------

def test_redis_queue_lifecycle():
    try:
        import redis as _redis_mod
        from app.config import get_settings
        settings = get_settings()
        if not settings.redis_url:
            pytest.skip("REDIS_URL not configured")
        conn = _redis_mod.Redis.from_url(settings.redis_url, decode_responses=True)
        conn.ping()
    except Exception:
        pytest.skip("Redis not available")

    try:
        from app.queue.redis_queue import RedisJobQueue
        reset_queue()
        queue = RedisJobQueue()
        # Clean any leftover keys
        queue._conn.delete("queue:jobs", "queue:jobs:processing", "queue:execs",
                           "queue:meta:job_r1", "queue:meta:exec_to_job")
        assert queue.enqueue("job_r1", "exec_r1", _payload())
        job = queue.claim()
        assert job is not None
        assert job.id == "job_r1"
        assert job.status == "claimed"
        assert job.attempts == 1

        queue.complete(job.id, "done")

        meta = queue._conn.hgetall(f"queue:meta:job_r1")
        assert meta.get("status") == "done"
        assert queue.claim() is None
    finally:
        queue._conn.delete("queue:jobs", "queue:jobs:processing", "queue:execs",
                           "queue:meta:job_r1", "queue:meta:exec_to_job")
        reset_queue()


# ---------------------------------------------------------------------------
# 3. DUPLICATE ENQUEUE: same execution_id twice should be idempotent
# ---------------------------------------------------------------------------

def test_duplicate_enqueue_is_idempotent():
    queue = _queue()
    _seed_user_and_workflow(1, "wf_1")
    assert queue.enqueue("job_dup1", "exec_dup", _payload()) is True
    assert queue.enqueue("job_dup2", "exec_dup", _payload()) is False

    # Only one job claimable
    job = queue.claim()
    assert job is not None
    assert job.id == "job_dup1"
    assert queue.claim() is None
    queue.complete(job.id, DONE)


# ---------------------------------------------------------------------------
# 4. WORKER CLAIM TIMEOUT: claimed job not completed should be reclaimable
# ---------------------------------------------------------------------------

def test_claim_timeout_recovery():
    queue = _queue()
    _enqueue_simple(queue, "exec_timeout")

    job = queue.claim()
    assert job is not None
    assert job.id == "job_exec_timeout"

    # Simulate stale: set heartbeat to the distant past
    db = get_session()
    try:
        row = db.get(Job, "job_exec_timeout")
        row.heartbeat_at = datetime(2000, 1, 1, tzinfo=UTC)
        row.claimed_at = datetime(2000, 1, 1, tzinfo=UTC)
        db.commit()
    finally:
        db.close()

    recovered = queue.recover_stale(stale_after_s=1)
    assert recovered == 1

    job2 = queue.claim()
    assert job2 is not None
    assert job2.id == "job_exec_timeout"
    assert job2.attempts == 2
    queue.complete(job2.id, DONE)


# ---------------------------------------------------------------------------
# 5. STALE JOB: job in "claimed" state with no heartbeat is recoverable
# ---------------------------------------------------------------------------

def test_stale_job_recovery():
    queue = _queue()
    _enqueue_simple(queue, "exec_stale")

    job = queue.claim()
    assert job is not None

    # Worker dies: no heartbeat, no complete. Claimed_at is 10 minutes ago.
    db = get_session()
    try:
        row = db.get(Job, "job_exec_stale")
        row.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
    finally:
        db.close()

    # Sweep should recover it
    assert queue.recover_stale(stale_after_s=60) == 1

    # Fresh worker can claim it
    job2 = queue.claim()
    assert job2 is not None
    assert job2.id == "job_exec_stale"
    assert job2.attempts == 2
    queue.complete(job2.id, DONE)


# ---------------------------------------------------------------------------
# 6. EXECUTION LIFECYCLE: create -> enqueue -> run_job -> verify transitions
# ---------------------------------------------------------------------------

def test_execution_lifecycle_via_run_job():
    queue = _queue()
    exec_id = "exec_lifecycle"
    wf_data = _simple_workflow()
    uid = _next_id()

    db = get_session()
    try:
        db.add(User(id=uid, email=f"lc_{uid}@b.com", password_hash="x"))
        db.add(WorkflowRecord(id="wf_audit", user_id=uid, name="LC", data={}, active=False))
        db.add(Execution(
            id=exec_id,
            workflow_id="wf_audit",
            user_id=uid,
            workflow_version=1,
            workflow_data=wf_data,
            trigger="manual",
            trigger_data=[{}],
            status="queued",
        ))
        db.commit()
    finally:
        db.close()

    payload = {
        "workflow_data": wf_data,
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": uid,
        "workflow_id": "wf_audit",
        "version": 1,
    }
    queue.enqueue(f"job_{exec_id}", exec_id, payload)

    # Before run: execution is queued
    rec = _exec_row(exec_id)
    assert rec.status == "queued"

    # Claim + run
    job = queue.claim()
    assert job is not None
    from app.execution_runtime import run_job

    events: list[dict] = []
    status = asyncio.run(run_job(job, lambda ev: events.append(ev)))
    assert status == "success"

    queue.complete(job.id, DONE)

    rec = _exec_row(exec_id)
    assert rec.status == "success"
    assert rec.finished_at is not None
    assert rec.results is not None

    job_row = _job_row(f"job_{exec_id}")
    assert job_row.status == DONE


# ---------------------------------------------------------------------------
# 7. WORKER CRASH RECOVERY: claim but don't complete -> reclaimable
# ---------------------------------------------------------------------------

def test_worker_crash_recovery():
    queue = _queue()
    _enqueue_simple(queue, "exec_crash")

    # Worker claims the job
    job = queue.claim()
    assert job is not None

    # Worker crashes: no heartbeat, no complete. Claimed_at is old.
    db = get_session()
    try:
        row = db.get(Job, "job_exec_crash")
        row.claimed_at = datetime.now(UTC) - timedelta(seconds=5)
        row.heartbeat_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()
    finally:
        db.close()

    worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                         poll_interval_s=0.01, heartbeat_s=0.01)
    recovered = asyncio.run(worker.recover_stale_once(0))
    assert recovered == 1

    # Second worker can now claim and run
    assert asyncio.run(worker.consume_once()) is True
    rec = _exec_row("exec_crash")
    assert rec.status == "success"


# ---------------------------------------------------------------------------
# 8. CONCURRENT ENQUEUE: 10 jobs, verify all complete
# ---------------------------------------------------------------------------

def test_concurrent_enqueue_and_complete():
    queue = _queue()
    n = 10
    uid = _next_id()

    db = get_session()
    try:
        db.add(User(id=uid, email=f"conc_{uid}@b.com", password_hash="x"))
        db.add(WorkflowRecord(id="wf_audit", user_id=uid, name="C", data={}, active=False))
        db.commit()
    finally:
        db.close()

    for i in range(n):
        exec_id = f"exec_conc_{i}"
        db = get_session()
        try:
            db.add(Execution(
                id=exec_id,
                workflow_id="wf_audit",
                user_id=uid,
                workflow_version=1,
                workflow_data={"id": "wf_audit", "nodes": [], "connections": []},
                trigger="manual",
                trigger_data=[{}],
                status="queued",
            ))
            db.commit()
        finally:
            db.close()
        assert queue.enqueue(f"job_{exec_id}", exec_id, _payload(wf_id="wf_audit"))

    # Claim all
    claimed = []
    for _ in range(n):
        j = queue.claim()
        assert j is not None
        claimed.append(j)

    # All claimed, nothing left
    assert queue.claim() is None

    # Complete all
    for j in claimed:
        queue.complete(j.id, DONE)

    # Verify all done
    for i in range(n):
        row = _job_row(f"job_exec_conc_{i}")
        assert row.status == DONE


# ---------------------------------------------------------------------------
# 9. DB QUEUE FAILED: job that fails -> status is "failed" not stuck
# ---------------------------------------------------------------------------

def test_failed_job_not_stuck():
    queue = _queue()
    uid = _next_id()
    _seed_user_and_workflow(uid, "wf_boom")
    _enqueue_simple(queue, "exec_fail", wf_id="wf_boom", user_id=uid)

    job = queue.claim()
    assert job is not None

    error = {"code": "EXECUTION_CRASHED", "message": "boom"}
    queue.complete(job.id, FAILED, error)

    row = _job_row("job_exec_fail")
    assert row.status == FAILED
    assert row.finished_at is not None
    assert row.error is not None
    assert row.error["code"] == "EXECUTION_CRASHED"

    # Cannot re-claim a failed job
    assert queue.claim() is None


# ---------------------------------------------------------------------------
# 10. JOB RETRY: stale claim -> recover with backoff -> verify retry
# ---------------------------------------------------------------------------

def test_job_retry_with_backoff(monkeypatch):
    from app.config import get_settings
    # Use tiny backoff so the test finishes quickly
    monkeypatch.setattr(get_settings(), "queue_retry_backoff_base_s", 0.05)
    monkeypatch.setattr(get_settings(), "queue_retry_backoff_max_s", 1.0)
    monkeypatch.setattr(get_settings(), "queue_max_attempts", 10)

    queue = _queue()
    _enqueue_simple(queue, "exec_retry")

    job = queue.claim()
    assert job is not None
    assert job.attempts == 1

    # Simulate stale claim
    db = get_session()
    try:
        row = db.get(Job, "job_exec_retry")
        row.claimed_at = datetime(2000, 1, 1, tzinfo=UTC)
        row.heartbeat_at = datetime(2000, 1, 1, tzinfo=UTC)
        db.commit()
    finally:
        db.close()

    # First recovery: requeued (attempt 1 -> will be attempt 2 on next claim)
    assert queue.recover_stale(stale_after_s=1) == 1

    # With retry backoff, the job may have next_retry_at set.
    # Wait briefly then claim.
    time.sleep(0.1)

    job2 = queue.claim()
    assert job2 is not None
    assert job2.attempts == 2

    # Make stale again for second retry
    db = get_session()
    try:
        row = db.get(Job, "job_exec_retry")
        row.claimed_at = datetime(2000, 1, 1, tzinfo=UTC)
        row.heartbeat_at = datetime(2000, 1, 1, tzinfo=UTC)
        db.commit()
    finally:
        db.close()

    assert queue.recover_stale(stale_after_s=1) == 1
    time.sleep(0.15)

    job3 = queue.claim()
    assert job3 is not None
    assert job3.attempts == 3
    queue.complete(job3.id, DONE)

    row = _job_row("job_exec_retry")
    assert row.status == DONE
    assert row.attempts == 3
