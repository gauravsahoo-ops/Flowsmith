"""Redis queue backend tests (Phase 15, spec 34/58) against fakeredis.

The same contract as the DB backend: FIFO order, atomic single claim,
completion, duplicate guard and stale-claim recovery.
"""

from __future__ import annotations

import time
from typing import Any

import fakeredis
import pytest

from app.queue import QueueBackend, get_queue
from app.queue import redis_queue as rq


@pytest.fixture
def redis_queue(monkeypatch):
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeRedis(server=server, decode_responses=True)

    class QueueForTest(rq.RedisJobQueue):
        def __init__(self) -> None:
            self._conn = redis

    monkeypatch.setattr("app.queue.redis_queue._now", lambda: str(time.time()))
    yield QueueForTest()


def _payload(name: str = "wf_1") -> dict[str, Any]:
    return {
        "workflow_data": {"id": "wf_1", "name": name, "nodes": [], "connections": []},
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_1",
        "version": 1,
    }


def test_fifo_order(redis_queue):
    for i in range(3):
        assert redis_queue.enqueue(f"job_{i}", f"exec_{i}", _payload(name=f"wf_{i}"))
    got = [redis_queue.claim().id for _ in range(3)]
    assert got == ["job_0", "job_1", "job_2"]
    assert redis_queue.claim() is None


def test_claim_is_exclusive(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    first = redis_queue.claim()
    assert first.id == "job_a"
    assert first.status == "claimed"
    assert redis_queue.claim() is None


def test_claim_increments_attempts(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    job = redis_queue.claim()
    assert job.attempts == 1
    redis_queue.complete(job.id, "done")
    redis_queue.enqueue("job_b", "exec_b", _payload())
    job2 = redis_queue.claim()
    assert job2.attempts == 1


def test_duplicate_execution_rejected(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    assert redis_queue.enqueue("job_b", "exec_a", _payload()) is False


def test_complete_removes_from_processing(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    job = redis_queue.claim()
    assert redis_queue._conn.llen(rq.PROCESSING_KEY) == 1
    redis_queue.complete(job.id, "done")
    assert redis_queue._conn.llen(rq.PROCESSING_KEY) == 0


def test_heartbeat_refreshes_claim(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    job = redis_queue.claim()
    redis_queue.heartbeat(job.id)
    meta = redis_queue._conn.hgetall(rq._meta_key(job.id))
    assert float(meta["heartbeat_at"]) > 0


def test_recover_stale_requeues(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    redis_queue.claim()  # claimed, no heartbeat refresh
    time.sleep(0.05)  # let the claim heartbeat age past the threshold
    assert redis_queue.recover_stale(stale_after_s=0.01) == 1
    recovered = redis_queue.claim()
    assert recovered is not None
    assert recovered.id == "job_a"
    assert recovered.attempts == 2


def test_recover_stale_skips_fresh_claims(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    job = redis_queue.claim()
    redis_queue.heartbeat(job.id)
    assert redis_queue.recover_stale(stale_after_s=60) == 0
    assert redis_queue.claim() is None


def test_recover_stale_treats_future_heartbeat_as_stale(redis_queue):
    assert redis_queue.enqueue("job_a", "exec_a", _payload())
    job = redis_queue.claim()
    redis_queue._conn.hset(rq._meta_key(job.id), "heartbeat_at", str(time.time() + 100))
    assert redis_queue.recover_stale(stale_after_s=60) == 1  # clock skew -> stale
