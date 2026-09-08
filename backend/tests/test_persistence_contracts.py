"""Persistence, worker-statelessness and queue-boundary regressions
(Phase 40).

- PostgreSQL executions are the authoritative record: job-row mutations
  cannot rewrite execution history (spec 25.3).
- Concurrent workers never receive the same queued job twice (atomic
  claims, spec 58) — verified with real threads on the DB queue.
- The queue is a pure transport: what a worker claims equals exactly
  what was enqueued.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.db import get_session
from app.models import Execution
from app.queue import get_queue


pytestmark = pytest.mark.timing

def test_executions_authoritative_over_job_rows(client):
    """Flipping a terminal job row to 'failed' must NOT change the
    execution's recorded success."""
    from tests.test_api.conftest import auth_headers, make_workflow, register

    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    eid = client.post("/api/workflows/wf_1/run", json={}, headers=headers).json()["data"]["execution_id"]

    import time
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
        if data["status"] not in ("queued", "running", "cancelling"):
            break
        time.sleep(0.05)
    assert data["status"] == "success"

    # Sabotage the transport layer only.
    db = get_session()
    try:
        from sqlalchemy import update

        from app.models import Job

        db.execute(update(Job).where(Job.execution_id == eid).values(status="failed"))
        db.commit()
    finally:
        db.close()

    after = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
    assert after["status"] == "success"


def test_queue_payload_boundary_passthrough():
    """A claimed job returns byte-equal payload to what was enqueued
    (queue = transport; runtime trusts nothing else)."""
    payload = {
        "workflow_data": {"id": "wf_x", "nodes": [], "connections": []},
        "trigger_items": [{"n": 1}],
        "trigger": "manual",
        "user_id": 7,
        "workflow_id": "wf_x",
        "version": 3,
        "workspace_id": None,
    }
    queue = get_queue()
    assert queue.enqueue("job_passthrough", "exec_passthrough", payload) is True
    job = queue.claim()
    try:
        assert job is not None
        assert job.id == "job_passthrough"
        assert job.execution_id == "exec_passthrough"
        assert job.payload == payload
    finally:
        queue.complete(job.id)


def test_concurrent_workers_never_double_claim():
    """Two workers racing claims split the queue with zero overlap.

    Workers poll until the queue is fully drained (like real consumers);
    transient empty claims are retried, so a busy machine cannot strand
    jobs. The hard assertions are: no duplicates and every job delivered
    exactly once.
    """
    import time

    total = 12
    for i in range(total):
        assert get_queue().enqueue(f"job_race_{i}", f"exec_race_{i}", {"i": i}) is True

    claimed_by: dict[str, list[str]] = {"w1": [], "w2": []}
    lock = threading.Lock()

    def worker(name: str) -> None:
        empty_streak = 0
        while True:
            job = get_queue().claim()
            if job is not None:
                empty_streak = 0
                with lock:
                    claimed_by[name].append(job.execution_id)
                get_queue().complete(job.id)
                with lock:
                    done = len(claimed_by["w1"]) + len(claimed_by["w2"])
                if done >= total:
                    return
                continue
            # No job claimed — check if other worker finished everything
            with lock:
                done = len(claimed_by["w1"]) + len(claimed_by["w2"])
            if done >= total:
                return
            empty_streak += 1
            if empty_streak > 10000:  # ~20 s: give up
                return
            time.sleep(0.002)

    t1 = threading.Thread(target=worker, args=("w1",))
    t2 = threading.Thread(target=worker, args=("w2",))
    deadline = time.time() + 30
    t1.start(); t2.start()
    while (t1.is_alive() or t2.is_alive()) and time.time() < deadline:
        time.sleep(0.05)

    all_ids = claimed_by["w1"] + claimed_by["w2"]
    assert len(all_ids) == total, f"delivered {len(all_ids)}/{total}: {sorted(all_ids)}"
    assert len(set(all_ids)) == total, f"double claim: {all_ids}"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    return TestClient(fastapi_app)
