"""Phase 19: async execution + recovery through the API process.

Verifies that the API never executes workflows synchronously: /run
returns 202 and the job flows through the queue to the embedded
consumer; an API-process restart is absorbed by the stateless worker
(queued jobs survive and are picked up by a fresh consumer); and the
execution history stays consistent across failures, retries and
restarts. The Salesforce connector runs through the whole stack.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.timing
from sqlalchemy import func, select

from app.connectors import get_registry, register_builtin_connectors
from app.db import get_session
from app.models import Execution, Job, User
from app.models.job import DONE, FAILED, QUEUED
from app.queue import get_queue
from app.queue.worker import ensure_embedded_consumer, stop_embedded_consumer
from tests.test_api.conftest import auth_headers, register

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

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
    """Serves the token, then blocks the data call for `hang_s` seconds."""

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


def _setup(client):
    data = register(client)
    return auth_headers(data["token"]), data["user"]["id"]


def _create_sf_credential(client, headers):
    resp = client.post("/api/credentials", json={"name": "SF Prod", "type": "salesforce", "data": SF_DATA}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _sf_workflow(credential_id: str, workflow_id: str, *, settings: dict | None = None) -> dict:
    return {
        "id": workflow_id,
        "name": "SF Pipeline",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sf",
                "type": "salesforce",
                "parameters": {
                    "operation": "search",
                    "object_name": "Lead",
                    "search_field": "Email",
                    "search_value": INPUT_EMAIL,
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "sf"}],
        "settings": settings or {},
    }


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    status = "running"
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        body = resp.json()
        if "data" not in body:
            time.sleep(0.05)
            continue
        status = body["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return body["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time: {status}")


def _user_id() -> int:
    db = get_session()
    try:
        return db.scalar(select(User.id).where(User.email == "a@b.com"))
    finally:
        db.close()


# ----------------------------------------------------------------------
# The API must not execute workflows synchronously
# ----------------------------------------------------------------------


def test_run_returns_202_without_synchronous_execution(client):
    headers, _user = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_async"
    client.post("/api/workflows", json=_sf_workflow(meta["id"], wf_id), headers=headers)

    # Stop the embedded consumer and prevent it from being restarted by
    # start_execution, so the job stays QUEUED for manual claim.
    stop_embedded_consumer()
    patcher, _fake = _patch_client(_search_responses(), client_cls=HangingFakeSFHTTPClient, hang_s=2.5)
    from unittest.mock import patch as _mpatch
    with _mpatch("app.api.executions.ensure_embedded_consumer"):
        t0 = time.monotonic()
        resp = client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers)
    elapsed = time.monotonic() - t0
    assert resp.status_code == 202, resp.text
    assert elapsed < 1.5, f"run endpoint blocked for {elapsed:.2f}s"

    execution_id = resp.json()["data"]["execution_id"]

    from app.execution_runtime import run_job
    from app.queue.worker import QueueWorker

    worker = QueueWorker()
    job = worker.queue.claim()
    assert job is not None, "job should be queued"
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_job(job, lambda ev: None))
    finally:
        loop.close()

    data = _poll(client, execution_id, headers)
    patcher.stop()

    assert data["status"] == "success"
    assert data["results"]["outputs"]["sf"]["main"][0]["found"] is True


# ----------------------------------------------------------------------
# API restart: pending jobs survive and are drained by a fresh consumer
# ----------------------------------------------------------------------


def test_api_restart_recovers_pending_jobs(client):
    stop_embedded_consumer()  # simulate the API process going down
    headers, user_id = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_restart"
    client.post("/api/workflows", json=_sf_workflow(meta["id"], wf_id), headers=headers)

    # A job was queued (e.g. by a webhook/scheduler) right before the
    # API process restarted. Execution row + job row are already persisted.
    execution_id = "exec_restart_1"
    db = get_session()
    try:
        db.add(Execution(
            id=execution_id,
            workflow_id=wf_id,
            user_id=user_id,
            workflow_version=1,
            workflow_data=_sf_workflow(meta["id"], wf_id),
            trigger="webhook",
            trigger_data=[{}],
            status=QUEUED,
        ))
        db.commit()
    finally:
        db.close()
    queue = get_queue()
    assert queue.enqueue(f"job_{execution_id}", execution_id, {
        "workflow_data": _sf_workflow(meta["id"], wf_id),
        "trigger_items": [{}],
        "trigger": "webhook",
        "user_id": user_id,
        "workflow_id": wf_id,
        "version": 1,
    })

    # No consumer is running: the job sits in the queue untouched.
    time.sleep(0.3)
    db = get_session()
    try:
        assert db.get(Execution, execution_id).status == QUEUED
        assert db.get(Job, f"job_{execution_id}").status == QUEUED
    finally:
        db.close()

    # The API "restarts": a fresh embedded consumer drains the queue.
    patcher, _fake = _patch_client(_search_responses())
    try:
        ensure_embedded_consumer()
        data = _poll(client, execution_id, headers)
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["trigger"] == "webhook"
    assert data["results"]["outputs"]["sf"]["main"][0]["found"] is True

    # Exactly one execution and one job; no duplicate delivery.
    db = get_session()
    try:
        assert db.scalar(
            select(func.count()).select_from(Execution).where(Execution.id == execution_id)
        ) == 1
        row = db.get(Job, f"job_{execution_id}")
        assert row.status == DONE
        assert row.attempts == 1
    finally:
        db.close()


# ----------------------------------------------------------------------
# History consistency across failures, retries and job rows
# ----------------------------------------------------------------------


def test_history_consistent_after_failure_and_retry(client):
    headers, _user = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_hist"
    client.post("/api/workflows", json=_sf_workflow(meta["id"], wf_id), headers=headers)

    # Scripted org: the first run gets a 400 (non-retryable), the retried
    # run succeeds.
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(400, json=[{"message": "INVALID_FIELD"}],
                       request=httpx.Request("GET", "http://fake")),
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]}),
        _json_response(200, LEAD_RECORD),
    ])
    try:
        first = client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers).json()["data"]
        failed = _poll(client, first["execution_id"], headers)
        retry = client.post(f"/api/executions/{first['execution_id']}/retry", json={}, headers=headers)
        assert retry.status_code == 202
        second = retry.json()["data"]
        succeeded = _poll(client, second["execution_id"], headers)
    finally:
        patcher.stop()

    assert failed["status"] == "failed"
    assert succeeded["status"] == "success"
    assert succeeded["trigger"] == "retry"
    assert succeeded["workflow_version"] == failed["workflow_version"] == 1

    # History: newest first, statuses consistent with the executions.
    history = client.get(f"/api/executions?workflow_id={wf_id}", headers=headers).json()
    assert history["meta"]["total"] == 2
    assert [e["id"] for e in history["data"]] == [second["execution_id"], first["execution_id"]]
    assert [e["status"] for e in history["data"]] == ["success", "failed"]
    assert history["data"][0]["workflow_name"] == "SF Pipeline"

    # Job rows mirror the execution outcomes (executions stay authoritative).
    db = get_session()
    try:
        rows = {
            r.execution_id: r
            for r in db.scalars(select(Job).where(
                Job.execution_id.in_([first["execution_id"], second["execution_id"]])
            )).all()
        }
    finally:
        db.close()
    assert rows[first["execution_id"]].status == FAILED
    assert rows[second["execution_id"]].status == DONE
