"""Generic HTTP polling-trigger registration and deduplication tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db import get_session
from app.models import PollingTrigger
from tests.test_api.conftest import auth_headers, register


def _make_workflow(client, headers, path: str = "poll-test"):
    workflow = {
        "id": f"wf_{path}",
        "name": "Polling Workflow",
        "nodes": [{
            "id": "poll",
            "type": "http_poll_trigger",
            "parameters": {
                "url": "https://example.com/items",
                "items_path": "items",
                "dedupe_field": "id",
                "interval_seconds": 60,
            },
        }],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=workflow, headers=headers).status_code == 201
    assert client.patch(
        f"/api/workflows/wf_{path}/active", json={"active": True}, headers=headers
    ).status_code == 200
    return workflow


def _due_trigger(workflow_id: str) -> str:
    db = get_session()
    try:
        trigger = db.query(PollingTrigger).filter(
            PollingTrigger.workflow_id == workflow_id
        ).one()
        trigger.next_poll_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        return trigger.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_polling_trigger_deduplicates_items(client, monkeypatch):
    user = register(client, "polling@example.com", "Password123!")
    headers = auth_headers(user["token"])
    _make_workflow(client, headers)

    db = get_session()
    try:
        trigger = db.query(PollingTrigger).filter(
            PollingTrigger.workflow_id == "wf_poll-test"
        ).one()
        assert trigger.status == "active"
        assert trigger.interval_seconds == 60
    finally:
        db.close()

    from app.services import polling_triggers

    calls: list[dict] = []

    async def fake_fetch(trigger):
        return {"items": [{"id": 1}, {"id": 2}]}, {}

    def fake_start(db, **kwargs):
        calls.append(kwargs)
        return "exec_test"

    monkeypatch.setattr(polling_triggers, "_fetch", fake_fetch)
    monkeypatch.setattr(
        "app.api.executions.has_running_execution", lambda db, workflow_id: False
    )
    monkeypatch.setattr("app.api.executions.start_execution", fake_start)

    _due_trigger("wf_poll-test")
    started = await polling_triggers.poll_due()
    assert started == 1
    assert len(calls) == 1
    assert [item["body"]["id"] for item in calls[0]["trigger_items"]] == [1, 2]
    assert calls[0]["trigger"] == "poll"

    _due_trigger("wf_poll-test")
    assert await polling_triggers.poll_due() == 0
    assert len(calls) == 1

    async def fake_new_fetch(trigger):
        return {"items": [{"id": 2}, {"id": 3}]}, {}

    monkeypatch.setattr(polling_triggers, "_fetch", fake_new_fetch)
    _due_trigger("wf_poll-test")
    assert await polling_triggers.poll_due() == 1
    assert [item["body"]["id"] for item in calls[1]["trigger_items"]] == [3]


@pytest.mark.asyncio
async def test_polling_failure_is_recorded(client, monkeypatch):
    user = register(client, "polling-fail@example.com", "Password123!")
    headers = auth_headers(user["token"])
    _make_workflow(client, headers, "poll-fail")
    _due_trigger("wf_poll-fail")

    from app.services import polling_triggers

    async def failing_fetch(trigger):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(polling_triggers, "_fetch", failing_fetch)
    assert await polling_triggers.poll_due() == 0

    db = get_session()
    try:
        trigger = db.query(PollingTrigger).filter(
            PollingTrigger.workflow_id == "wf_poll-fail"
        ).one()
        assert "upstream unavailable" in (trigger.last_error or "")
    finally:
        db.close()


def test_polling_trigger_removed_when_workflow_deactivates(client):
    user = register(client, "polling-off@example.com", "Password123!")
    headers = auth_headers(user["token"])
    _make_workflow(client, headers, "poll-off")
    assert client.patch(
        "/api/workflows/wf_poll-off/active", json={"active": False}, headers=headers
    ).status_code == 200
    db = get_session()
    try:
        assert db.query(PollingTrigger).filter(
            PollingTrigger.workflow_id == "wf_poll-off"
        ).count() == 0
    finally:
        db.close()
