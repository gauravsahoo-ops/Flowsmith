"""Job queue tests (Phase 15, spec 34/58): FIFO order, atomic single
claim, completion, duplicate guard and stale-claim recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.models import Execution, Job, User, WorkflowRecord
from app.models.job import DONE, FAILED, QUEUED
from app.queue import QueueBackend, get_queue
from app.queue.db_queue import DbJobQueue


@pytest.fixture
def db_queue():
    # The embedded consumer may have been started by API tests earlier
    # in the suite; it polls the *current* engine and would steal jobs,
    # making claim tests flaky.
    from app.queue.worker import stop_embedded_consumer

    stop_embedded_consumer()
    queue = DbJobQueue()
    yield queue


def _payload(name: str = "wf_1") -> dict[str, Any]:
    return {
        "workflow_data": {"id": "wf_1", "name": name, "nodes": [], "connections": []},
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_1",
        "version": 1,
    }


def _seed_user_and_workflow():
    from app.db import get_session

    db = get_session()
    try:
        user = User(id=1, email="a@b.com", password_hash="x")
        db.add(user)
        db.add(WorkflowRecord(id="wf_1", user_id=1, name="W", data={}, active=False))
        db.commit()
    finally:
        db.close()


def test_fifo_order(db_queue):
    for i in range(3):
        assert db_queue.enqueue(f"job_{i}", f"exec_{i}", _payload(name=f"wf_{i}"))
    got = [db_queue.claim().id for _ in range(3)]
    assert got == ["job_0", "job_1", "job_2"]
    assert db_queue.claim() is None


def test_claim_is_exclusive(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    first = db_queue.claim()
    assert first.id == "job_a"
    assert first.status == "claimed"
    # A second consumer (simulated by claiming again) must not see it.
    assert db_queue.claim() is None


def test_claim_marks_attempts(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    job = db_queue.claim()
    assert job.attempts == 1
    db_queue.heartbeat(job.id)
    job2 = db_queue.claim()
    assert job2 is None


def test_complete_terminates_job(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    job = db_queue.claim()
    db_queue.complete(job.id, DONE)
    assert db_queue.claim() is None
    from app.db import get_session

    db = get_session()
    try:
        row = db.get(Job, "job_a")
        assert row is not None
        assert row.status == DONE
        assert row.finished_at is not None
    finally:
        db.close()


def test_duplicate_execution_rejected(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    assert db_queue.enqueue("job_b", "exec_a", _payload()) is False


def test_recover_stale_requeues(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    job = db_queue.claim()
    # Simulate a crashed worker: no heartbeat, claim is old.
    from app.db import get_session

    db = get_session()
    try:
        row = db.get(Job, job.id)
        assert row is not None
        row.claimed_at = datetime.now(UTC) - timedelta(minutes=5)
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    assert db_queue.recover_stale(stale_after_s=60) == 1
    recovered = db_queue.claim()
    assert recovered is not None
    assert recovered.id == "job_a"
    assert recovered.attempts == 2  # claim count survived the crash


def test_recover_stale_skips_fresh_claims(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    job = db_queue.claim()
    db_queue.heartbeat(job.id)
    assert db_queue.recover_stale(stale_after_s=60) == 0
    assert db_queue.claim() is None


def test_failed_job_is_terminal(db_queue):
    assert db_queue.enqueue("job_a", "exec_a", _payload())
    job = db_queue.claim()
    db_queue.complete(job.id, FAILED, {"code": "NODE_ERROR", "message": "boom"})
    from app.db import get_session

    db = get_session()
    try:
        row = db.get(Job, job.id)
        assert row is not None
        assert row.status == FAILED
        assert row.error is not None
        assert row.error["code"] == "NODE_ERROR"
    finally:
        db.close()


def test_factory_selects_db_by_default(tmp_path, monkeypatch):
    from app.queue import reset_queue

    reset_queue()
    assert get_queue().name == "db"
