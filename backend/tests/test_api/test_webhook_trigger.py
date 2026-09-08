"""Public webhook trigger tests (spec 9, 32): 202, delivery records,
404/405/413, skip-if-running, activation semantics."""

from __future__ import annotations

import time

import pytest

from app.db import get_session
from app.models import WebhookDelivery, WebhookTrigger
from tests.test_api.conftest import SLOW_TYPE, auth_headers, register

pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_node")]


def _setup(client):
    return auth_headers(register(client)["token"])


def _webhook_workflow(workflow_id="wf_hook", path="hook-test-secure-path-abcdefgh", method="POST", slow=False):
    nodes = [
        {"id": "trigger", "type": "webhook", "parameters": {"path": path, "method": method}},
        {"id": "echo", "type": "set_data", "parameters": {"fields": {"msg": "{{ $json.body.msg }}"}}},
    ]
    if slow:
        nodes.append({"id": "slow", "type": SLOW_TYPE, "parameters": {}, "settings": {}})
    connections = [{"source": "trigger", "target": "echo"}]
    if slow:
        connections.append({"source": "echo", "target": "slow"})
    return {
        "id": workflow_id,
        "name": "Hook",
        "nodes": nodes,
        "connections": connections,
        "settings": {},
    }


def _create_and_activate(client, headers, workflow):
    client.post("/api/workflows", json=workflow, headers=headers)
    resp = client.patch(f"/api/workflows/{workflow['id']}/active", json={"active": True}, headers=headers)
    assert resp.status_code == 200, resp.text


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        status = resp.json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return resp.json()["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def test_webhook_fires_workflow_publicly(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow())

    resp = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={"msg": "hello"})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["skipped"] is False
    assert data["execution_id"]

    exec_data = _poll(client, data["execution_id"], headers)
    assert exec_data["status"] == "success"
    assert exec_data["trigger"] == "webhook"
    output = exec_data["results"]["outputs"]["echo"]["main"][0]
    assert output["msg"] == "hello"

    db = get_session()
    try:
        delivery = db.get(WebhookDelivery, data["delivery_id"])
        assert delivery is not None
        assert delivery.status == "success"  # linked to the execution outcome
        assert delivery.response_code == 202
        assert delivery.execution_id == data["execution_id"]
    finally:
        db.close()


def test_webhook_body_passthrough_shaped_like_node_contract(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow())
    resp = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={"a": [1, 2]}, headers={"X-Custom": "v"})
    data = resp.json()["data"]
    exec_data = _poll(client, data["execution_id"], headers)
    assert exec_data["status"] == "success"
    wh_out = exec_data["results"]["outputs"]["trigger"]["main"]
    assert wh_out[0]["body"] == {"a": [1, 2]}
    assert wh_out[0]["headers"]["x-custom"] == "v"
    assert wh_out[0]["query"] == {}


def test_webhook_unknown_path_404(client):
    assert client.post("/api/webhooks/never-registered", json={}).status_code == 404


def test_webhook_inactive_workflow_404(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_webhook_workflow(), headers=headers)
    assert client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={}).status_code == 404


def test_webhook_wrong_method_405(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow(method="POST"))
    assert client.get("/api/webhooks/hook-test-secure-path-abcdefgh").status_code == 405


def test_webhook_oversize_body_413(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow())
    resp = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", content=b"x" * (5 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def test_webhook_skips_when_workflow_already_running(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow(slow=True))

    first = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={"n": 1}).json()["data"]
    assert first["skipped"] is False
    # The job goes through the queue (Phase 15): wait until the embedded
    # consumer picks it up and the execution is actually running.
    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/executions/{first['execution_id']}", headers=headers).json()["data"]["status"]
        if status == "running":
            break
        time.sleep(0.05)
    assert status == "running"

    second = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={"n": 2}).json()["data"]
    assert second["skipped"] is True
    assert second["execution_id"] is None

    db = get_session()
    try:
        deliveries = db.query(WebhookDelivery).order_by(WebhookDelivery.received_at).all()
        # the first run is still in flight, so its delivery stays queued
        assert [d.status for d in deliveries] == ["queued", "skipped"]
    finally:
        db.close()

    client.post(f"/api/executions/{first['execution_id']}/cancel", headers=headers)
    _poll(client, first["execution_id"], headers)


def test_deactivate_removes_webhook(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow())
    assert client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={}).status_code == 202

    client.patch("/api/workflows/wf_hook/active", json={"active": False}, headers=headers)
    assert client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={}).status_code == 404

    db = get_session()
    try:
        assert db.query(WebhookTrigger).count() == 0
    finally:
        db.close()


def test_webhook_path_collision_rejected(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow(workflow_id="wf_a", path="same-path-abcdefgh12345678"))
    second = _webhook_workflow(workflow_id="wf_b", path="same-path-abcdefgh12345678")
    resp = client.post("/api/workflows", json=second, headers=headers)
    assert resp.status_code == 422


def test_webhook_idempotency_key_replays_first_delivery(client):
    """Spec 32: the same Idempotency-Key returns the original delivery
    instead of creating a second execution."""
    import uuid

    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow())
    key = f"key-{uuid.uuid4().hex[:8]}"

    first = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={"msg": "a"}, headers={"Idempotency-Key": key})
    assert first.status_code == 202
    first_data = first.json()["data"]
    _poll(client, first_data["execution_id"], headers)

    replay = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={"msg": "b"}, headers={"Idempotency-Key": key})
    assert replay.status_code == 202
    replay_data = replay.json()["data"]
    assert replay_data["replayed"] is True
    assert replay_data["delivery_id"] == first_data["delivery_id"]
    assert replay_data["execution_id"] == first_data["execution_id"]

    db = get_session()
    try:
        assert db.query(WebhookDelivery).count() == 1
    finally:
        db.close()


def test_webhook_distinct_idempotency_keys_get_separate_runs(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _webhook_workflow())

    a = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={}, headers={"Idempotency-Key": "key-a"}).json()["data"]
    _poll(client, a["execution_id"], headers)
    b = client.post("/api/webhooks/hook-test-secure-path-abcdefgh", json={}, headers={"Idempotency-Key": "key-b"}).json()["data"]
    _poll(client, b["execution_id"], headers)

    assert a["execution_id"] != b["execution_id"]
    assert a["delivery_id"] != b["delivery_id"]
    db = get_session()
    try:
        assert db.query(WebhookDelivery).count() == 2
    finally:
        db.close()
