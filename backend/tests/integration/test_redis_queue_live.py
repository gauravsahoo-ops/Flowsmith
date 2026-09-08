"""Real Redis queue integration tests (skipped when Redis is down).

Run `docker compose up -d` from the repo root, then these run against
the live server instead of fakeredis. They validate the actual Redis
list/hash protocol contract (LMOVE claim atomicity, stale recovery).
"""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.queue import get_queue, reset_queue

REDIS_URL = os.environ.get("REDIS_URL", get_settings().redis_url or "redis://localhost:6379/0")

_PREV_QUEUE_BACKEND = os.environ.get("QUEUE_BACKEND")
_PREV_REDIS_URL = os.environ.get("REDIS_URL")


def _use_redis_backend() -> None:
    """Force the real Redis backend regardless of the ambient settings."""
    os.environ["QUEUE_BACKEND"] = "redis"
    os.environ["REDIS_URL"] = REDIS_URL
    get_settings.cache_clear()
    reset_queue()


def _restore_ambient_backend() -> None:
    """Put the ambient QUEUE_BACKEND/REDIS_URL back so later tests see the
    settings the environment actually declares (not the forced values)."""
    if _PREV_QUEUE_BACKEND is None:
        os.environ.pop("QUEUE_BACKEND", None)
    else:
        os.environ["QUEUE_BACKEND"] = _PREV_QUEUE_BACKEND
    if _PREV_REDIS_URL is None:
        os.environ.pop("REDIS_URL", None)
    else:
        os.environ["REDIS_URL"] = _PREV_REDIS_URL
    get_settings.cache_clear()
    reset_queue()


@pytest.fixture
def redis_queue():
    _use_redis_backend()
    try:
        import redis as redis_lib

        conn = redis_lib.Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3)
        conn.ping()
    except Exception as exc:
        _restore_ambient_backend()
        pytest.skip(f"Redis not reachable at {REDIS_URL}: {exc}")
    from app.queue.redis_queue import EXECS_KEY, META_PREFIX, PROCESSING_KEY, QUEUE_KEY

    conn.flushdb()
    reset_queue()
    yield get_queue()
    conn.flushdb()
    reset_queue()
    _restore_ambient_backend()


def test_redis_enqueue_claim_complete(redis_queue) -> None:
    job_id = "job_r1"
    assert redis_queue.enqueue(job_id, "exec_r1", {"workflow_id": "wf", "user_id": 1}) is True
    assert redis_queue.enqueue(job_id, "exec_r1", {"workflow_id": "wf", "user_id": 1}) is False  # idempotent

    job = redis_queue.claim()
    assert job is not None
    assert job.id == job_id
    assert job.execution_id == "exec_r1"
    assert job.attempts == 1
    assert job.claimed_by  # worker id set

    redis_queue.complete(job_id)
    assert redis_queue.claim() is None  # queue drained


def test_redis_heartbeat_and_stale_recovery(redis_queue) -> None:
    import time

    from app.queue.redis_queue import PROCESSING_KEY

    redis_queue.enqueue("job_s1", "exec_s1", {"workflow_id": "wf"})
    job = redis_queue.claim()
    assert job is not None
    redis_queue.heartbeat(job.id)
    time.sleep(0.01)  # let the heartbeat age past the sub-second clock tick
    assert redis_queue.recover_stale(stale_after_s=3600) == 0  # fresh -> untouched
    assert redis_queue.recover_stale(stale_after_s=0) == 1  # stale -> re-queued

    recovered = redis_queue.claim()
    assert recovered is not None
    assert recovered.execution_id == "exec_s1"
    assert recovered.attempts == 2