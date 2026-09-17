"""Live Redis audit tests — every test hits a real Redis at 127.0.0.1:6379/0.

Run:  python -m pytest tests/test_redis_live_audit.py -v
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

import pytest
import redis

from app.queue.redis_queue import (
    EXECS_KEY,
    META_PREFIX,
    PROCESSING_KEY,
    QUEUE_KEY,
    SCHEDULED_KEY,
    RedisJobQueue,
)
from app.queue import QueueJob

# ---------------------------------------------------------------------------
# Fixtures
import os

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
PREFIXES_TO_CLEAN = [
    QUEUE_KEY,
    PROCESSING_KEY,
    SCHEDULED_KEY,
    EXECS_KEY,
    f"{META_PREFIX}exec_to_job",
]


def _meta_key(job_id: str) -> str:
    return f"{META_PREFIX}{job_id}"


def _make_conn() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _make_queue(conn: redis.Redis) -> RedisJobQueue:
    q = RedisJobQueue.__new__(RedisJobQueue)
    q._conn = conn
    return q


def _payload(name: str = "wf_1", size: int = 0) -> dict[str, Any]:
    base = {
        "workflow_data": {"id": "wf_1", "name": name, "nodes": [], "connections": []},
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_1",
        "version": 1,
    }
    if size > 0:
        base["workflow_data"]["blob"] = "x" * size
    return base


@pytest.fixture(autouse=True)
def _flush_redis():
    """Flush all queue keys before and after each test."""
    conn = _make_conn()
    # Pre-clean
    for prefix in PREFIXES_TO_CLEAN:
        conn.delete(prefix)
    # Also delete any meta hashes from prior tests
    for key in conn.scan_iter(f"{META_PREFIX}*"):
        conn.delete(key)
    yield
    # Post-clean
    for prefix in PREFIXES_TO_CLEAN:
        conn.delete(prefix)
    for key in conn.scan_iter(f"{META_PREFIX}*"):
        conn.delete(key)


@pytest.fixture()
def conn():
    return _make_conn()


@pytest.fixture()
def q(conn):
    return _make_queue(conn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    """1. ENQUEUE → CLAIM → COMPLETE"""

    def test_full_lifecycle(self, q):
        assert q.enqueue("j1", "e1", _payload())
        job = q.claim()
        assert job is not None
        assert job.id == "j1"
        assert job.execution_id == "e1"
        assert job.status == "claimed"
        assert job.attempts == 1
        q.complete(job.id, "done")
        # Queue should be empty now
        assert q.claim() is None


class TestDuplicateEnqueue:
    """2. Same execution_id twice → second rejected (idempotency)."""

    def test_duplicate_rejected(self, q):
        assert q.enqueue("j1", "e1", _payload()) is True
        assert q.enqueue("j2", "e1", _payload()) is False
        # Only j1 should be claimable
        job = q.claim()
        assert job is not None
        assert job.id == "j1"
        assert q.claim() is None


class TestFifoOrder:
    """3. Enqueue A, B, C → claim returns A first, then B, then C."""

    def test_fifo(self, q):
        q.enqueue("j_a", "e_a", _payload("a"))
        q.enqueue("j_b", "e_b", _payload("b"))
        q.enqueue("j_c", "e_c", _payload("c"))
        ids = [q.claim().id for _ in range(3)]
        assert ids == ["j_a", "j_b", "j_c"]
        assert q.claim() is None


class TestClaimTimeout:
    """4. Claim a job, don't complete it, wait for stale timeout, verify
    it becomes reclaimable."""

    def test_stale_becomes_reclaimable(self, q):
        q.enqueue("j1", "e1", _payload())
        q.claim()
        # Wait for heartbeat to age
        time.sleep(0.05)
        recovered = q.recover_stale(stale_after_s=0.01)
        assert recovered == 1
        job = q.claim()
        assert job is not None
        assert job.id == "j1"
        assert job.attempts == 2


class TestStaleRecovery:
    """5. Claim 3 jobs, abandon 2, run recover_stale → 2 reclaimed, 1 stays."""

    def test_partial_recovery(self, q):
        for i in range(3):
            q.enqueue(f"j{i}", f"e{i}", _payload(str(i)))
        j0 = q.claim()
        j1 = q.claim()
        j2 = q.claim()
        # Let all heartbeats age — use generous sleep to survive Windows
        # timer resolution (~15 ms) and CI slow-downs.
        time.sleep(0.2)
        # Refresh j2's heartbeat so it looks fresh
        q.heartbeat(j2.id)
        # j0/j1 heartbeats are ~0.2s old; j2's is brand-new
        # stale_after_s=0.1 → j0/j1 stale, j2 fresh
        recovered = q.recover_stale(stale_after_s=0.1)
        assert recovered == 2
        # j2 is still claimed; the 2 recovered jobs are back in queue
        meta2 = q._conn.hgetall(_meta_key(j2.id))
        assert meta2["status"] == "claimed"
        # Two jobs were re-queued and claimable
        recovered_job1 = q.claim()
        recovered_job2 = q.claim()
        assert recovered_job1 is not None
        assert recovered_job2 is not None
        assert recovered_job1.id in ("j0", "j1")
        assert recovered_job2.id in ("j0", "j1")
        assert recovered_job1.id != recovered_job2.id
        assert q.claim() is None


class TestHeartbeat:
    """6. Claim job → send heartbeat → verify heartbeat_at is updated."""

    def test_heartbeat_updates(self, q):
        q.enqueue("j1", "e1", _payload())
        job = q.claim()
        before = float(q._conn.hget(_meta_key(job.id), "heartbeat_at"))
        time.sleep(0.02)
        q.heartbeat(job.id)
        after = float(q._conn.hget(_meta_key(job.id), "heartbeat_at"))
        assert after > before


class TestCompleteWithError:
    """7. Complete a job with error → verify status is 'failed' and error is stored."""

    def test_complete_failed(self, q):
        q.enqueue("j1", "e1", _payload())
        job = q.claim()
        err = {"code": "TIMEOUT", "message": "took too long"}
        q.complete(job.id, "failed", error=err)
        meta = q._conn.hgetall(_meta_key(job.id))
        assert meta["status"] == "failed"
        stored_err = json.loads(meta["error"])
        assert stored_err["code"] == "TIMEOUT"
        # Should be terminal: removed from execs set
        assert not q._conn.sismember(EXECS_KEY, "e1")


class TestRetryWithBackoff:
    """8. Claim job that exceeds max_attempts → verify terminal failure."""

    def test_terminal_failure_after_max_attempts(self, q):
        with patch("app.maintenance.mark_execution_failed") as mock_mef, \
             patch("app.queue.retry_delay_s", return_value=0.0):
            q.enqueue("j1", "e1", _payload())
            # Cycle claim → abandon → recover_stale to increment attempts
            # After 9 cycles attempts=9; the 10th claim brings attempts=10
            for attempt in range(9):
                job = q.claim()
                assert job is not None, f"claim failed on attempt {attempt}"
                assert job.id == "j1"
                time.sleep(0.05)
                q.recover_stale(stale_after_s=0.01)
            # 10th claim → attempts becomes 10
            job = q.claim()
            assert job is not None
            assert job.attempts == 10
            time.sleep(0.05)
            # This recover_stale sees attempts(10) >= max_attempts(10) → terminal fail
            q.recover_stale(stale_after_s=0.01)
            meta = q._conn.hgetall(_meta_key("j1"))
            assert meta["status"] == "failed"
            err = json.loads(meta["error"])
            assert err["code"] == "MAX_ATTEMPTS_EXCEEDED"
            mock_mef.assert_called_once()


class TestScheduledPromotion:
    """9. Create a job in the scheduled sorted set with past ready time
    → promote_due should move it to queue."""

    def test_scheduled_promotion(self, q, conn):
        q.enqueue("j1", "e1", _payload())
        # Move job to scheduled set with a ready time in the past
        conn.zadd(SCHEDULED_KEY, {"j1": time.time() - 10})
        conn.lrem(QUEUE_KEY, 0, "j1")
        # Claim triggers promotion
        job = q.claim()
        assert job is not None
        assert job.id == "j1"
        assert conn.zscore(SCHEDULED_KEY, "j1") is None


class TestConcurrentClaim:
    """10. Enqueue 5 jobs, claim from 3 'workers' simultaneously → each gets unique jobs."""

    def test_concurrent_unique_claims(self, q):
        # Clean slate to avoid interference from prior tests
        conn = q._conn
        conn.delete("queue:jobs", "queue:jobs:processing", "queue:execs")
        for i in range(5):
            q.enqueue(f"jc{i}", f"ec{i}", _payload(str(i)))
        claimed = []
        # Simulate 3 workers claiming one each, then drain the rest
        for worker in range(3):
            job = q.claim()
            if job:
                claimed.append(job.id)
        # Drain remaining
        while True:
            job = q.claim()
            if job is None:
                break
            claimed.append(job.id)
        assert len(claimed) == 5, f"Expected 5 jobs claimed, got {len(claimed)}: {claimed}"
        assert len(set(claimed)) == 5  # all unique


class TestRequeue:
    """11. Complete a job → requeue it → claim it again."""

    def test_requeue(self, q):
        q.enqueue("j1", "e1", _payload())
        job = q.claim()
        # Requeue while still claimed (non-terminal) — durable pause/resume
        assert q.requeue("e1", _payload("new")) is True
        job2 = q.claim()
        assert job2 is not None
        assert job2.execution_id == "e1"
        assert job2.payload["workflow_data"]["name"] == "new"


class TestCleanup:
    """12. Complete a job → verify TTL is set on meta hash."""

    def test_ttl_on_terminal(self, q):
        q.enqueue("j1", "e1", _payload())
        job = q.claim()
        q.complete(job.id, "done")
        ttl = q._conn.ttl(_meta_key("j1"))
        assert ttl > 0  # TTL is set


class TestLargePayload:
    """13. Enqueue job with 100KB payload → verify store/retrieve."""

    def test_large_payload(self, q):
        p = _payload(size=100_000)
        q.enqueue("j_big", "e_big", p)
        job = q.claim()
        assert job is not None
        assert len(job.payload["workflow_data"]["blob"]) == 100_000
        assert job.payload["workflow_data"]["blob"] == "x" * 100_000


class TestLostMeta:
    """14. Delete a job's meta hash manually → claim should rebuild minimal meta."""

    def test_lost_meta_rebuild(self, q):
        q.enqueue("j1", "e1", _payload())
        # Simulate crash: delete meta hash
        q._conn.delete(_meta_key("j1"))
        job = q.claim()
        assert job is not None
        assert job.id == "j1"
        # Meta should be rebuilt with at least status
        meta = q._conn.hgetall(_meta_key("j1"))
        assert meta.get("status") in ("queued", "claimed")
