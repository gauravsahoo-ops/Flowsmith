"""Worker tests (Phase 15, spec 34/58): claim -> execute -> complete,
durable events, crash recovery and cooperative cancellation."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy import select

from app.db import get_session
from app.engine.errors import NodeCancelledError
from app.engine.node_base import BaseNode, EmptyParams, NodeContext, NodeResult
from app.models import Execution, Job, User, WorkflowRecord
from app.models.job import DONE, QUEUED
from app.nodes.registry import NODE_REGISTRY
from app.queue.db_queue import DbJobQueue
from app.queue.worker import QueueWorker

SLOW_TYPE = "queue_slow_test_node"
pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_queue_node")]


@pytest.fixture
def slow_queue_node():
    """A node that sleeps until cancelled (cancel test)."""

    class SlowNode(BaseNode[EmptyParams]):
        node_type = SLOW_TYPE
        display_name = "Slow (queue test)"
        version = 1
        description = "Hangs until cancelled."
        category = "Test"
        icon = "🐌"
        parameters_schema = EmptyParams

        async def run(self, ctx: NodeContext, params: EmptyParams, input_items: list[dict[str, Any]]) -> NodeResult:
            for _ in range(2000):
                if ctx.is_cancelled():
                    raise NodeCancelledError()
                await asyncio.sleep(0.02)
            return NodeResult(output_items=[{"done": True}])

    NODE_REGISTRY[SLOW_TYPE] = SlowNode
    yield SLOW_TYPE
    NODE_REGISTRY.pop(SLOW_TYPE, None)


@pytest.fixture
def db_and_queue():
    from app.queue.worker import stop_embedded_consumer

    stop_embedded_consumer()
    db = get_session()
    db.add(User(id=1, email="q@b.com", password_hash="x"))
    db.add(WorkflowRecord(id="wf_1", user_id=1, name="W", data={}, active=False))
    db.commit()
    db.close()
    return DbJobQueue()


def _wf(settings: dict | None = None, nodes: list | None = None,
        connections: list | None = None) -> dict:
    return {
        "id": "wf_1",
        "name": "W",
        "nodes": nodes or [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "transform", "type": "set_data", "parameters": {"fields": {"greeting": "hi"}}},
        ],
        "connections": connections if connections is not None
            else [{"source": "trigger", "target": "transform"}],
        "settings": settings or {},
    }


def _enqueue(queue: DbJobQueue, workflow_data: dict, execution_id: str = "exec_1") -> None:
    db = get_session()
    try:
        db.add(Execution(
            id=execution_id,
            workflow_id="wf_1",
            user_id=1,
            workflow_version=1,
            workflow_data=workflow_data,
            trigger="manual",
            trigger_data=[{}],
            status=QUEUED,
        ))
        db.commit()
    finally:
        db.close()
    assert queue.enqueue(f"job_{execution_id}", execution_id, {
        "workflow_data": workflow_data,
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_1",
        "version": 1,
    })


def _execution(execution_id: str) -> Execution:
    db = get_session()
    try:
        rec = db.get(Execution, execution_id)
        assert rec is not None, f"Execution {execution_id!r} not found"
        return rec
    finally:
        db.close()


def test_worker_runs_job_and_completes_it(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _wf(), "exec_ok")
    worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                         poll_interval_s=0.01, heartbeat_s=0.01)
    assert asyncio.run(worker.consume_once()) is True

    rec = _execution("exec_ok")
    assert rec.status == "success"
    assert rec.results is not None
    assert rec.results["outputs"]["transform"]["main"] == [{"greeting": "hi"}]

    db = get_session()
    try:
        row = db.get(Job, "job_exec_ok")
        assert row is not None
        assert row.status == DONE
        assert row.attempts == 1
    finally:
        db.close()


def test_worker_transitions_queued_to_running(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _wf(), "exec_run")
    worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                         poll_interval_s=0.01, heartbeat_s=0.01)
    asyncio.run(worker.consume_once())
    assert _execution("exec_run").status == "success"


def test_worker_persists_events_to_db(db_and_queue):
    from app.models import ExecutionEvent

    queue = db_and_queue
    _enqueue(queue, _wf(), "exec_ev")
    worker = QueueWorker(queue=queue, poll_interval_s=0.01, heartbeat_s=0.01)
    asyncio.run(worker.consume_once())

    db = get_session()
    try:
        events = db.scalars(
            select(ExecutionEvent).where(ExecutionEvent.execution_id == "exec_ev")
            .order_by(ExecutionEvent.seq)
        ).all()
        names = [e.event for e in events]
        assert "execution.started" in names
        assert "node.completed" in names
        assert "execution.completed" in names
        assert events[-1].status == "success"
    finally:
        db.close()


def test_worker_cancels_via_db_flag(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _wf(nodes=[{"id": "slow", "type": SLOW_TYPE, "parameters": {}}], connections=[]), "exec_cancel")

    async def scenario():
        worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                             poll_interval_s=0.01, heartbeat_s=0.01)
        async def mark_cancelling():
            await asyncio.sleep(0.3)
            db = get_session()
            try:
                rec = db.get(Execution, "exec_cancel")
                assert rec is not None
                rec.status = "cancelling"
                db.commit()
            finally:
                db.close()
        task = asyncio.create_task(mark_cancelling())
        await worker.consume_once()
        task.cancel()
        return worker

    asyncio.run(scenario())
    rec = _execution("exec_cancel")
    assert rec.status == "cancelled"


def test_worker_cancelled_before_claim(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _wf(), "exec_early_cancel")
    db = get_session()
    try:
        rec = db.get(Execution, "exec_early_cancel")
        assert rec is not None
        rec.status = "cancelling"
        db.commit()
    finally:
        db.close()
    worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                         poll_interval_s=0.01, heartbeat_s=0.01)
    assert asyncio.run(worker.consume_once()) is True
    rec = _execution("exec_early_cancel")
    assert rec.status == "cancelled"


def test_crashed_worker_job_is_recovered(db_and_queue):
    """Simulate a worker crash: claim without heartbeat/complete; a second
    worker recovers and runs the job (spec 34.1)."""
    queue = db_and_queue
    _enqueue(queue, _wf(), "exec_crash")

    # The first worker claimed the job, then "crashed" before executing.
    claimed = queue.claim()
    assert claimed.id == "job_exec_crash"
    db = get_session()
    try:
        row = db.get(Job, "job_exec_crash")
        assert row is not None
        assert row.status == "claimed"
    finally:
        db.close()

    # A second worker (fresh process) recovers the stale claim and runs it.
    worker2 = QueueWorker(queue=queue, event_sink=lambda ev: None,
                          poll_interval_s=0.01, heartbeat_s=0.01)
    assert asyncio.run(worker2.recover_stale_once(0)) == 1
    assert asyncio.run(worker2.consume_once()) is True
    assert _execution("exec_crash").status == "success"

    db = get_session()
    try:
        row = db.get(Job, "job_exec_crash")
        assert row is not None
        assert row.status == DONE
        assert row.attempts == 2
    finally:
        db.close()


def test_worker_idle_does_nothing(db_and_queue):
    worker = QueueWorker(queue=db_and_queue, event_sink=lambda ev: None,
                         poll_interval_s=0.01, heartbeat_s=0.01)
    assert asyncio.run(worker.consume_once()) is False


def test_failed_workflow_marks_job_failed(db_and_queue):
    queue = db_and_queue
    from app.models.job import FAILED

    _enqueue(queue, {
        "id": "wf_1",
        "name": "W",
        "nodes": [{"id": "http", "type": "http_request",
                   "parameters": {"url": "http://127.0.0.1:9/nope", "method": "GET"}}],
        "connections": [],
        "settings": {},
    }, "exec_fail")
    worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                         poll_interval_s=0.01, heartbeat_s=0.01)
    asyncio.run(worker.consume_once())
    assert _execution("exec_fail").status == "failed"

    db = get_session()
    try:
        row = db.get(Job, "job_exec_fail")
        assert row is not None
        assert row.status == FAILED
    finally:
        db.close()


def test_worker_heartbeat_refreshes_claim(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _wf(nodes=[{"id": "slow", "type": SLOW_TYPE, "parameters": {}}], connections=[]), "exec_beat")

    async def scenario():
        worker = QueueWorker(queue=queue, event_sink=lambda ev: None,
                             poll_interval_s=0.01, heartbeat_s=0.05)
        async def cancel_later():
            await asyncio.sleep(1.0)
            db = get_session()
            try:
                rec = db.get(Execution, "exec_beat")
                assert rec is not None
                rec.status = "cancelling"
                db.commit()
            finally:
                db.close()
        task = asyncio.create_task(cancel_later())
        await worker.consume_once()
        task.cancel()

    asyncio.run(scenario())
    db = get_session()
    try:
        row = db.get(Job, "job_exec_beat")
        assert row is not None
        assert row.heartbeat_at is not None
    finally:
        db.close()
