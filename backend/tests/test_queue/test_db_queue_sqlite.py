"""SQLite portability regression for the database job queue.

The live Salesforce acceptance harness boots the real API/worker stack on a
temporary SQLite database. The queue therefore must support SQLite without
PostgreSQL-only ``FOR UPDATE SKIP LOCKED`` or array binding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.queue.db_queue as db_queue_module
from app.models import Job
from app.models.job import CLAIMED, QUEUED
from app.queue.db_queue import DbJobQueue


def _payload() -> dict:
    return {
        "workflow_data": {"id": "wf_sqlite", "name": "SQLite", "nodes": [], "connections": []},
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_sqlite",
        "version": 1,
    }


def _sqlite_queue(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'queue.db'}",
        connect_args={"check_same_thread": False},
    )
    Job.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db_queue_module, "get_session", lambda: session_factory())
    return DbJobQueue(), session_factory


def test_sqlite_claim_is_fifo_and_exclusive(tmp_path, monkeypatch):
    queue, _ = _sqlite_queue(tmp_path, monkeypatch)

    assert queue.enqueue("job_0", "exec_0", _payload())
    assert queue.enqueue("job_1", "exec_1", _payload())

    first = queue.claim()
    assert first is not None
    assert first.id == "job_0"
    assert first.status == "claimed"
    assert first.attempts == 1

    second = queue.claim()
    assert second is not None
    assert second.id == "job_1"

    assert queue.claim() is None


def test_sqlite_recover_stale_requeues_portably(tmp_path, monkeypatch):
    queue, session_factory = _sqlite_queue(tmp_path, monkeypatch)
    assert queue.enqueue("job_stale", "exec_stale", _payload())

    claimed = queue.claim()
    assert claimed is not None

    session = session_factory()
    try:
        row = session.get(Job, "job_stale")
        row.status = CLAIMED
        row.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()
    finally:
        session.close()

    assert queue.recover_stale(stale_after_s=1) == 1

    recovered = queue.claim()
    assert recovered is not None
    assert recovered.id == "job_stale"
    assert recovered.attempts == 2


def test_sqlite_claim_skips_future_retry(tmp_path, monkeypatch):
    queue, session_factory = _sqlite_queue(tmp_path, monkeypatch)
    assert queue.enqueue("job_later", "exec_later", _payload())

    session = session_factory()
    try:
        row = session.get(Job, "job_later")
        row.status = QUEUED
        row.next_retry_at = datetime.now(UTC) + timedelta(hours=1)
        session.commit()
    finally:
        session.close()

    assert queue.claim() is None
