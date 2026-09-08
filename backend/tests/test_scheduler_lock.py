"""Scheduler advisory-lock test (Phase 18).

Verifies that when two Scheduler ticks contend for the same pg advisory
lock, only one fires executions (no duplicate scheduled runs).
"""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from app.db import get_session
from app.models import ScheduleTrigger, WorkflowRecord, User
from app.scheduler import Scheduler


def _get_or_create_user(email: str) -> int:
    db = get_session()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            return user.id
        u = User(email=email, password_hash="x")
        db.add(u)
        db.commit()
        return u.id
    finally:
        db.close()


def _get_or_create_workflow(user_id: int, wf_id: str) -> dict:
    db = get_session()
    try:
        rec = db.get(WorkflowRecord, wf_id)
        if rec:
            return rec.data
        data = {"id": wf_id, "name": wf_id, "nodes": [{"id": "t", "type": "schedule", "parameters": {"cron": "* * * * *"}}], "connections": []}
        rec = WorkflowRecord(id=wf_id, user_id=user_id, name=wf_id, data=data, active=True)
        db.add(rec)
        db.commit()
        return data
    finally:
        db.close()


@pytest.mark.asyncio
async def test_two_schedulers_do_not_double_fire(monkeypatch):
    user_id = _get_or_create_user("sched_lock@example.com")
    wf_id = "wf_sched_lock"
    wf_data = _get_or_create_workflow(user_id, wf_id)

    # Create an active schedule trigger that would fire now (every minute).
    db = get_session()
    try:
        # Clean previous triggers for this workflow
        for r in db.scalars(select(ScheduleTrigger).where(ScheduleTrigger.workflow_id == wf_id)).all():
            db.delete(r)
        db.commit()
        trig = ScheduleTrigger(
            id="sched_lock_trig",
            workflow_id=wf_id,
            node_id="t",
            user_id=user_id,
            cron="* * * * *",
            timezone="UTC",
            status="active",
            workflow_version=1,
            workflow_data=wf_data,
        )
        db.add(trig)
        db.commit()
    finally:
        db.close()

    s1 = Scheduler()
    s2 = Scheduler()
    now = datetime.now(timezone.utc)
    # Prime their next_fire caches (first call always returns 0 and sets next_fire).
    await s1.tick(now - timedelta(seconds=60))
    await s2.tick(now - timedelta(seconds=60))
    # Second tick: the cron is due now; only one should fire.
    fired1 = await s1.tick(now)
    fired2 = await s2.tick(now)
    assert fired1 + fired2 == 1, f"expected exactly one fire, got {fired1}+{fired2}"

    # Cleanup
    db = get_session()
    try:
        for r in db.scalars(select(ScheduleTrigger).where(ScheduleTrigger.workflow_id == wf_id)).all():
            db.delete(r)
        # Remove executions created by the scheduler to keep test DB clean
        from app.models import Execution
        for e in db.scalars(select(Execution).where(Execution.workflow_id == wf_id)).all():
            db.delete(e)
        db.commit()
    finally:
        db.close()
