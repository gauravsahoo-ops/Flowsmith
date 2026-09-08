"""Scheduler trigger tests (spec 33, 13): registration, due firing,
skip-if-running, no catch-up, deactivation, rules-based format."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest

from app.db import get_session
from app.models import Execution, ScheduleTrigger
from app.scheduler import Scheduler
from tests.test_api.conftest import SLOW_TYPE, auth_headers, register

pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_node")]


def _setup(client):
    return auth_headers(register(client)["token"])


def _schedule_workflow(workflow_id="wf_cron", cron="* * * * *", timezone_="UTC", slow=False):
    nodes = [
        {"id": "trigger", "type": "schedule", "parameters": {"cron": cron, "timezone": timezone_}},
        {"id": "echo", "type": "set_data", "parameters": {"fields": {"ts": "{{ $json.timestamp }}"}}},
    ]
    if slow:
        nodes.append({"id": "slow", "type": SLOW_TYPE, "parameters": {}, "settings": {}})
    connections = [{"source": "trigger", "target": "echo"}]
    if slow:
        connections.append({"source": "echo", "target": "slow"})
    return {
        "id": workflow_id,
        "name": "Cron",
        "nodes": nodes,
        "connections": connections,
        "settings": {},
    }


def _schedule_workflow_rules(workflow_id="wf_rules", rules=None, slow=False):
    """Create a workflow with the new rules-based format."""
    if rules is None:
        rules = [{"id": "r1", "interval": "minutes", "value": 1, "timezone": "UTC"}]
    nodes = [
        {"id": "trigger", "type": "schedule", "parameters": {"rules": rules}},
        {"id": "echo", "type": "set_data", "parameters": {"fields": {"ts": "{{ $json.timestamp }}"}}},
    ]
    if slow:
        nodes.append({"id": "slow", "type": SLOW_TYPE, "parameters": {}, "settings": {}})
    connections = [{"source": "trigger", "target": "echo"}]
    if slow:
        connections.append({"source": "echo", "target": "slow"})
    return {
        "id": workflow_id,
        "name": "Rules Schedule",
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


# ── Legacy cron format tests ──

def test_activation_registers_schedule_trigger(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow())
    db = get_session()
    try:
        rows = db.query(ScheduleTrigger).all()
        assert len(rows) == 1
        assert rows[0].workflow_id == "wf_cron"
        assert rows[0].cron == "* * * * *"
        assert rows[0].timezone == "UTC"
        assert rows[0].status == "active"
    finally:
        db.close()


async def test_scheduler_fires_due_cron(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow())
    sched = Scheduler()

    t0 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    assert await sched.tick(t0) == 0  # registers next fire (12:01:00), no catch-up

    t1 = datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    assert await sched.tick(t1) == 1

    db = get_session()
    try:
        execs = db.query(Execution).filter_by(workflow_id="wf_cron").all()
        assert len(execs) == 1
        assert execs[0].trigger == "schedule"
        td = execs[0].trigger_data[0]
        assert td["timestamp"] == "2026-01-01T12:01:00+00:00"
        assert td["cron"] == "* * * * *"
        assert td["timezone"] == "UTC"
        assert td["workflow_id"] == "wf_cron"
    finally:
        db.close()
    _poll(client, execs[0].id, headers)

    assert await sched.tick(t1) == 0  # same minute again: not due
    assert await sched.tick(datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc)) == 1


async def test_scheduler_no_duplicate_fire_per_occurrence(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow())
    sched = Scheduler()
    t0 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    await sched.tick(t0)
    # many ticks after the due minute -> exactly one execution
    for _ in range(5):
        await sched.tick(datetime(2026, 1, 1, 12, 1, 30, tzinfo=timezone.utc))
    db = get_session()
    try:
        assert db.query(Execution).filter_by(workflow_id="wf_cron").count() == 1
    finally:
        db.close()


async def test_scheduler_skips_when_workflow_running(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow(slow=True))
    sched = Scheduler()
    t0 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    await sched.tick(t0)
    t1 = datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    assert await sched.tick(t1) == 1
    # Small delay to ensure the execution has been claimed and is running
    await asyncio.sleep(0.1)
    t2 = datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc)
    assert await sched.tick(t2) == 0  # still running -> skipped

    db = get_session()
    try:
        execs = db.query(Execution).filter_by(workflow_id="wf_cron").all()
        assert len(execs) == 1
        client.post(f"/api/executions/{execs[0].id}/cancel", headers=headers)
    finally:
        db.close()
    _poll(client, execs[0].id, headers)


async def test_scheduler_no_catchup_after_restart(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow())

    first = Scheduler()
    t0 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    await first.tick(t0)

    # Small delay to ensure the execution has started
    await asyncio.sleep(0.1)

    # "restart": a fresh scheduler has no memory; occurrences 12:01..12:09
    # were missed -> must not fire a burst, just resync to the next
    # occurrence (12:11) and fire it once due.
    restarted = Scheduler()
    assert await restarted.tick(datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)) == 0
    assert await restarted.tick(datetime(2026, 1, 1, 12, 11, 0, tzinfo=timezone.utc)) == 1

    db = get_session()
    try:
        execs = db.query(Execution).filter_by(workflow_id="wf_cron").all()
        assert len(execs) == 1
    finally:
        db.close()
    _poll(client, execs[0].id, headers)


async def test_deactivate_removes_schedule(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow())
    client.patch("/api/workflows/wf_cron/active", json={"active": False}, headers=headers)
    db = get_session()
    try:
        assert db.query(ScheduleTrigger).count() == 0
        sched = Scheduler()
        assert await sched.tick(datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)) == 0
    finally:
        db.close()


# ── Rules-based format tests ──

def test_activation_registers_rules_trigger(client):
    """New rules-based format creates correct DB row with 5-field cron."""
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow_rules(
        rules=[{"id": "r1", "interval": "minutes", "value": 5, "timezone": "UTC"}]
    ))
    db = get_session()
    try:
        rows = db.query(ScheduleTrigger).filter_by(workflow_id="wf_rules").all()
        assert len(rows) == 1
        assert rows[0].cron == "*/5 * * * *"
        assert rows[0].timezone == "UTC"
        assert rows[0].status == "active"
    finally:
        db.close()


def test_activation_registers_seconds_trigger(client):
    """Seconds-based rule creates DB row with interval_type metadata."""
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow_rules(
        workflow_id="wf_sec",
        rules=[{"id": "r1", "interval": "seconds", "value": 10, "timezone": "UTC"}]
    ))
    db = get_session()
    try:
        rows = db.query(ScheduleTrigger).filter_by(workflow_id="wf_sec").all()
        assert len(rows) == 1
        assert rows[0].timezone == "UTC"
        assert rows[0].interval_type == "seconds"
        assert rows[0].interval_value == 10
        assert rows[0].status == "active"
    finally:
        db.close()


def test_activation_registers_multiple_rules(client):
    """Multiple rules create multiple DB rows with interval metadata."""
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow_rules(
        workflow_id="wf_multi",
        rules=[
            {"id": "r1", "interval": "seconds", "value": 5, "timezone": "UTC"},
            {"id": "r2", "interval": "minutes", "value": 10, "timezone": "UTC"},
        ]
    ))
    db = get_session()
    try:
        rows = db.query(ScheduleTrigger).filter_by(workflow_id="wf_multi").all()
        assert len(rows) == 2
        by_type = {r.interval_type: r for r in rows}
        assert "seconds" in by_type
        assert "minutes" in by_type
        assert by_type["seconds"].interval_value == 5
        assert by_type["minutes"].interval_value == 10
    finally:
        db.close()


def test_activation_registers_cron_rule(client):
    """Custom cron rule creates correct DB row."""
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow_rules(
        workflow_id="wf_cron_rule",
        rules=[{"id": "r1", "interval": "cron", "cron": "30 4 * * *", "timezone": "US/Eastern"}]
    ))
    db = get_session()
    try:
        rows = db.query(ScheduleTrigger).filter_by(workflow_id="wf_cron_rule").all()
        assert len(rows) == 1
        assert rows[0].cron == "30 4 * * *"
        assert rows[0].timezone == "US/Eastern"
    finally:
        db.close()


async def test_scheduler_fires_rules_seconds(client):
    """Seconds-based rule fires correctly with adaptive tick."""
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow_rules(
        workflow_id="wf_sec_fire",
        rules=[{"id": "r1", "interval": "seconds", "value": 5, "timezone": "UTC"}]
    ))
    sched = Scheduler()
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert await sched.tick(t0) == 0  # register

    t1 = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
    assert await sched.tick(t1) == 1

    db = get_session()
    try:
        execs = db.query(Execution).filter_by(workflow_id="wf_sec_fire").all()
        assert len(execs) == 1
        assert execs[0].trigger == "schedule"
        # Seconds rules use placeholder cron
        assert execs[0].trigger_data[0]["cron"] == "*/5 * * * *"
    finally:
        db.close()


def test_deactivate_removes_rules_schedule(client):
    """Deactivation removes rules-based schedule rows."""
    headers = _setup(client)
    _create_and_activate(client, headers, _schedule_workflow_rules(
        workflow_id="wf_del",
        rules=[
            {"id": "r1", "interval": "seconds", "value": 5, "timezone": "UTC"},
            {"id": "r2", "interval": "minutes", "value": 10, "timezone": "UTC"},
        ]
    ))
    db = get_session()
    try:
        assert db.query(ScheduleTrigger).filter_by(workflow_id="wf_del").count() == 2
    finally:
        db.close()
    client.patch("/api/workflows/wf_del/active", json={"active": False}, headers=headers)
    db = get_session()
    try:
        assert db.query(ScheduleTrigger).filter_by(workflow_id="wf_del").count() == 0
    finally:
        db.close()




