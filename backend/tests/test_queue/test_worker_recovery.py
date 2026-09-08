"""Phase 19: the Salesforce workflow under asynchronous execution.

Worker-level acceptance for the queue + stateless worker — the exact
code path the embedded consumer and `python -m app.queue.worker` run:

- queue execution: queued -> claimed -> done; execution queued -> success
- worker execution + persistence: results / node_statuses / trace
- worker restart: a stale claim is recovered by a fresh worker
  (attempts survive; the job is rebuilt from its payload snapshot)
- worker restart mid-execution: the snapshot is re-run from scratch
  and the record ends with ONE consistent outcome
- retry: 429 -> engine retry -> success (job claim count unaffected)
- timeout: workflow timeout_seconds -> execution "timeout", job done
- cancellation: durable cancel flag -> cooperative cancel, job done
- duplicate job delivery: execution_id dedup -> executed exactly once

Preserves the stateless-worker architecture: workers hold no state,
every job is re-executed from its payload snapshot after a crash.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.timing
from sqlalchemy import func, select

from app.connectors import get_registry, register_builtin_connectors
from app.credentials import service as credential_service
from app.db import get_session
from app.models import Credential, Execution, Job, User, WorkflowRecord
from app.models.job import DONE, QUEUED
from app.queue.db_queue import DbJobQueue
from app.queue.worker import QueueWorker, stop_embedded_consumer

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

SECRET_MARKERS = ["S3CR3T_CLIENT_SECRET_ZZZ", "P4SS_+_TOK3N_ZZZ", "cid_123"]

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}
LEAD_RECORD = {"Id": "00Qabc123", "Name": "Jane Doe", "Email": "jane@example.com", "Company": "Acme"}
INPUT_EMAIL = "jane@example.com"


class FakeSFHTTPClient:
    """Scripted SafeHTTPClient replacement: token + data API responses."""

    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class HangingFakeSFHTTPClient(FakeSFHTTPClient):
    """Serves the token, then blocks the data call (workflow timeout test)."""

    def __init__(self, responses: list[httpx.Response], hang_s: float):
        super().__init__(responses)
        self.hang_s = hang_s

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        if len(self.calls) >= 2:
            await asyncio.sleep(self.hang_s)
        return self.responses.pop(0)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses: list[httpx.Response], client_cls=FakeSFHTTPClient, **kwargs):
    from unittest.mock import AsyncMock, MagicMock, patch

    fake = client_cls(responses, **kwargs)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


def _assert_no_secrets(value: Any, where: str) -> None:
    text = json.dumps(value, default=str)
    for marker in SECRET_MARKERS:
        assert marker not in text, f"secret {marker!r} leaked into {where}"


def _search_responses() -> list[httpx.Response]:
    return [
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]}),
        _json_response(200, LEAD_RECORD),
    ]


@pytest.fixture(autouse=True)
def _connectors_registered():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield


@pytest.fixture
def db_and_queue():
    """Isolated DB + queue with a user, workflow and an encrypted SF credential."""
    stop_embedded_consumer()
    db = get_session()
    db.add(User(id=1, email="q@b.com", password_hash="x"))
    db.add(WorkflowRecord(id="wf_1", user_id=1, name="SF Pipeline", data={}, active=False))
    credential_service.create_for_user(db, 1, "SF Prod", "salesforce", SF_DATA)
    db.commit()
    db.close()
    return DbJobQueue()


def _credential_id() -> str:
    db = get_session()
    try:
        return db.scalar(select(Credential).where(Credential.user_id == 1)).id
    finally:
        db.close()


def _sf_workflow(credential_id: str, *, sf_settings: dict | None = None,
                 settings: dict | None = None) -> dict:
    return {
        "id": "wf_1",
        "name": "SF Pipeline",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sf",
                "type": "salesforce",
                "parameters": {
                    "operation": "search",
                    "resource": "Search",
                    "object_name": "Lead",
                    "search_field": "Email",
                    "search_value": INPUT_EMAIL,
                },
                "settings": sf_settings or {},
                "credentials": {"salesforce": credential_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "sf"}],
        "settings": settings or {},
    }


def _enqueue(queue: DbJobQueue, workflow_data: dict, execution_id: str = "exec_1") -> bool:
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
    return queue.enqueue(f"job_{execution_id}", execution_id, {
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


def _job(job_id: str) -> Job:
    db = get_session()
    try:
        row = db.get(Job, job_id)
        assert row is not None, f"Job {job_id!r} not found"
        return row
    finally:
        db.close()


def _worker(queue: DbJobQueue) -> QueueWorker:
    return QueueWorker(queue=queue, event_sink=lambda ev: None,
                       poll_interval_s=0.01, heartbeat_s=0.01)


# ----------------------------------------------------------------------
# Queue execution + worker execution (with persistence)
# ----------------------------------------------------------------------


def test_queue_execution_runs_salesforce_workflow(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _sf_workflow(_credential_id()), "exec_q1")

    # Queue execution: the job is queued, not yet claimed.
    row = _job("job_exec_q1")
    assert row.status == QUEUED
    assert row.attempts == 0
    assert _execution("exec_q1").status == QUEUED

    patcher, fake = _patch_client(_search_responses())
    try:
        assert asyncio.run(_worker(queue).consume_once()) is True
    finally:
        patcher.stop()

    # Worker execution: the Salesforce search ran to success.
    rec = _execution("exec_q1")
    assert rec.status == "success"
    assert rec.node_statuses == {"trigger": "success", "sf": "success"}
    sf_output = rec.results["outputs"]["sf"]["main"][0]
    assert sf_output["found"] is True
    assert sf_output["record"]["Email"] == INPUT_EMAIL

    # Execution persistence: trace steps in order; no secrets stored.
    assert [s["node_type"] for s in rec.trace] == ["manual_trigger", "salesforce"]
    _assert_no_secrets(rec.results, "results")
    _assert_no_secrets(rec.trace, "trace")

    # Queue execution: the job went queued -> claimed -> done (one claim).
    row = _job("job_exec_q1")
    assert row.status == DONE
    assert row.attempts == 1
    assert row.finished_at is not None

    # The worker really hit the org: token, query, record fetch.
    assert [c[0] for c in fake.calls] == ["POST", "GET", "GET"]
    query_call = next(c for c in fake.calls if "/query" in c[1])
    assert query_call[2]["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"


# ----------------------------------------------------------------------
# Worker restart (stateless recovery)
# ----------------------------------------------------------------------


def test_worker_restart_recovers_stale_claim(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _sf_workflow(_credential_id()), "exec_crash")

    # The first worker claimed the job, then "crashed" before executing.
    claimed = queue.claim()
    assert claimed.id == "job_exec_crash"
    assert _job("job_exec_crash").status == "claimed"

    # A fresh worker (new process) recovers the stale claim and runs it.
    patcher, _fake = _patch_client(_search_responses())
    try:
        assert asyncio.run(_worker(queue).recover_stale_once(0)) == 1
        assert asyncio.run(_worker(queue).consume_once()) is True
    finally:
        patcher.stop()

    # Stateless: the execution was rebuilt from the payload snapshot.
    rec = _execution("exec_crash")
    assert rec.status == "success"
    assert rec.results["outputs"]["sf"]["main"][0]["found"] is True
    assert rec.node_statuses == {"trigger": "success", "sf": "success"}

    # Exactly one execution and one job; the claim was re-queued (attempt 2).
    row = _job("job_exec_crash")
    assert row.status == DONE
    assert row.attempts == 2
    assert row.claimed_by is not None
    db = get_session()
    try:
        count = db.scalar(
            select(func.count()).select_from(Execution).where(Execution.workflow_id == "wf_1")
        )
    finally:
        db.close()
    assert count == 1


def test_worker_restart_mid_execution_reruns_snapshot(db_and_queue):
    queue = db_and_queue
    _enqueue(queue, _sf_workflow(_credential_id()), "exec_mid")

    # The first worker claimed the job, started executing, then crashed.
    claimed = queue.claim()
    assert claimed.id == "job_exec_mid"
    db = get_session()
    try:
        rec = db.get(Execution, "exec_mid")
        assert rec is not None
        rec.status = "running"
        db.commit()
    finally:
        db.close()

    # A fresh worker re-runs the workflow from the snapshot.
    patcher, _fake = _patch_client(_search_responses())
    try:
        assert asyncio.run(_worker(queue).recover_stale_once(0)) == 1
        assert asyncio.run(_worker(queue).consume_once()) is True
    finally:
        patcher.stop()

    # The record holds ONE consistent outcome (the re-run), not a mix.
    rec = _execution("exec_mid")
    assert rec.status == "success"
    assert rec.finished_at is not None
    assert [s["node_type"] for s in rec.trace] == ["manual_trigger", "salesforce"]
    assert set(rec.node_statuses) == {"trigger", "sf"}
    assert _job("job_exec_mid").attempts == 2


# ----------------------------------------------------------------------
# Retry through the worker
# ----------------------------------------------------------------------


def test_worker_retries_salesforce_429_and_succeeds(db_and_queue):
    queue = db_and_queue
    workflow = _sf_workflow(
        _credential_id(),
        sf_settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
    )
    _enqueue(queue, workflow, "exec_retry")

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}],
                       request=httpx.Request("GET", "http://fake")),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]}),
        _json_response(200, LEAD_RECORD),
    ])
    try:
        assert asyncio.run(_worker(queue).consume_once()) is True
    finally:
        patcher.stop()

    rec = _execution("exec_retry")
    assert rec.status == "success"
    assert rec.node_statuses["sf"] == "success"
    query_calls = [c for c in fake.calls if "/query" in c[1]]
    assert len(query_calls) == 2  # failed attempt + retried attempt
    sf_step = next(s for s in rec.trace if s["node_id"] == "sf")
    assert "1 retries" in sf_step["note"]

    # Engine-level retry does not touch the job's claim count.
    assert _job("job_exec_retry").status == DONE
    assert _job("job_exec_retry").attempts == 1


# ----------------------------------------------------------------------
# Timeout through the worker
# ----------------------------------------------------------------------


def test_worker_timeout_marks_execution_timeout(db_and_queue):
    queue = db_and_queue
    workflow = _sf_workflow(_credential_id(), settings={"timeout_seconds": 0.4})
    _enqueue(queue, workflow, "exec_to")

    patcher, _fake = _patch_client(
        [_json_response(200, TOKEN_BODY)],
        client_cls=HangingFakeSFHTTPClient, hang_s=30.0,
    )
    try:
        assert asyncio.run(_worker(queue).consume_once()) is True
    finally:
        patcher.stop()

    rec = _execution("exec_to")
    assert rec.status == "timeout"
    assert rec.finished_at is not None
    assert rec.results is not None  # partial results persisted
    assert _job("job_exec_to").status == DONE  # timeout is terminal
    assert _job("job_exec_to").attempts == 1


# ----------------------------------------------------------------------
# Cancellation through the worker
# ----------------------------------------------------------------------


def test_worker_cancellation_is_cooperative(db_and_queue):
    queue = db_and_queue
    workflow = _sf_workflow(
        _credential_id(),
        sf_settings={"retry_max_attempts": 5, "retry_backoff_seconds": 2.0},
    )
    _enqueue(queue, workflow, "exec_cancel")

    async def scenario():
        worker = _worker(queue)

        async def mark_cancelling():
            await asyncio.sleep(0.4)
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

    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}],
                       request=httpx.Request("GET", "http://fake")),
    ])
    try:
        asyncio.run(scenario())
    finally:
        patcher.stop()

    # The search 429 is retryable; during the backoff the durable cancel
    # flag flips and the retry loop raises NodeCancelledError.
    rec = _execution("exec_cancel")
    assert rec.status == "cancelled"
    assert rec.finished_at is not None
    assert _job("job_exec_cancel").status == DONE


# ----------------------------------------------------------------------
# Duplicate job delivery
# ----------------------------------------------------------------------


def test_duplicate_job_delivery_executes_once(db_and_queue):
    queue = db_and_queue
    workflow = _sf_workflow(_credential_id())

    # Two deliveries of the same execution id: the second is rejected by
    # the queue's execution_id dedup guard (the execution row already
    # exists — only the job delivery repeats).
    assert _enqueue(queue, workflow, "exec_dup") is True
    assert queue.enqueue("job_exec_dup_2", "exec_dup", {
        "workflow_data": workflow,
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_1",
        "version": 1,
    }) is False

    patcher, _fake = _patch_client(_search_responses())
    try:
        worker = _worker(queue)
        assert asyncio.run(worker.consume_once()) is True
        assert asyncio.run(worker.consume_once()) is False  # nothing left
    finally:
        patcher.stop()

    rec = _execution("exec_dup")
    assert rec.status == "success"

    # Exactly one job and one execution; a single claim, a single run.
    db = get_session()
    try:
        jobs = db.scalars(select(Job).where(Job.execution_id == "exec_dup")).all()
        executions = db.scalars(select(Execution).where(Execution.id == "exec_dup")).all()
    finally:
        db.close()
    assert len(jobs) == 1
    assert len(executions) == 1
    assert jobs[0].status == DONE
    assert jobs[0].attempts == 1
