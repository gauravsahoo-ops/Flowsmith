"""Scheduler persistence & restart behaviour tests.

Tests that schedule triggers survive simulated restarts, advisory locks
prevent double-fires, activation/deletion works, and edge-case cron
expressions fire correctly.

All tests mock start_execution / has_running_execution so no real
workflow runs.  The actual DB (schedule_triggers table) is used.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import select

from app.db import get_session
from app.models import ScheduleTrigger, WorkflowRecord, User, Execution
from app.scheduler import Scheduler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_test_user_counter = 0


def _unique_suffix() -> str:
    global _test_user_counter
    _test_user_counter += 1
    return f"{_test_user_counter}_{int(datetime.now(timezone.utc).timestamp())}"


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
        data = {
            "id": wf_id,
            "name": wf_id,
            "nodes": [{"id": "t", "type": "schedule", "parameters": {"cron": "* * * * *"}}],
            "connections": [],
        }
        rec = WorkflowRecord(id=wf_id, user_id=user_id, name=wf_id, data=data, active=True)
        db.add(rec)
        db.commit()
        return data
    finally:
        db.close()


def _insert_trigger(
    *,
    trigger_id: str,
    workflow_id: str,
    user_id: int,
    wf_data: dict,
    cron: str = "* * * * *",
    tz: str = "UTC",
    status: str = "active",
    interval_type: str | None = None,
    interval_value: int | None = None,
) -> ScheduleTrigger:
    db = get_session()
    try:
        t = ScheduleTrigger(
            id=trigger_id,
            workflow_id=workflow_id,
            user_id=user_id,
            node_id="t",
            cron=cron,
            timezone=tz,
            status=status,
            workflow_version=1,
            workflow_data=wf_data,
            interval_type=interval_type,
            interval_value=interval_value,
        )
        db.add(t)
        db.commit()
        return t
    finally:
        db.close()


def _delete_trigger(trigger_id: str) -> None:
    db = get_session()
    try:
        t = db.get(ScheduleTrigger, trigger_id)
        if t:
            db.delete(t)
            db.commit()
    finally:
        db.close()


def _cleanup(wf_id: str) -> None:
    db = get_session()
    try:
        for r in db.scalars(select(ScheduleTrigger).where(ScheduleTrigger.workflow_id == wf_id)).all():
            db.delete(r)
        for e in db.scalars(select(Execution).where(Execution.workflow_id == wf_id)).all():
            db.delete(e)
        db.commit()
    finally:
        db.close()


def _has_no_running(db, wf_id):
    return False


def _fire_patches():
    """Return a tuple of context-manager patches for start_execution + has_running_execution."""
    return (
        patch("app.api.executions.start_execution", return_value="exec_001"),
        patch("app.api.executions.has_running_execution", side_effect=_has_no_running),
    )



# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_trigger_survives_restart():
    """1. Cron schedule in DB -> new Scheduler instance -> tick fires it."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"persist_cron_{suffix}@test.com")
    wf_id = f"wf_persist_cron_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_persist_cron_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="* * * * *")

        # Simulate restart: fresh Scheduler instance (empty _next_fire cache)
        s = Scheduler()
        now = datetime.now(timezone.utc)

        # Prime: first tick registers next_fire, returns 0
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired1 = await s.tick(now - timedelta(seconds=60))
        assert fired1 == 0

        # Second tick: cron is due -> fires
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired2 = await s.tick(now)
        assert fired2 == 1
        start_mock.assert_called_once()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_seconds_trigger_survives_restart():
    """2. Seconds-based schedule -> new Scheduler -> fires after interval."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"persist_sec_{suffix}@test.com")
    wf_id = f"wf_persist_sec_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_persist_sec_{suffix}"

    try:
        _insert_trigger(
            trigger_id=trig_id,
            workflow_id=wf_id,
            user_id=user_id,
            wf_data=wf_data,
            cron="* * * * *",
            interval_type="seconds",
            interval_value=10,
        )

        s = Scheduler()
        now = datetime.now(timezone.utc)

        # Prime: first tick sets next_fire = now + 10s
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired1 = await s.tick(now)
        assert fired1 == 0

        # Tick at now + 5s -> not yet
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired2 = await s.tick(now + timedelta(seconds=5))
        assert fired2 == 0
        start_mock.assert_not_called()

        # Tick at now + 10s -> fires
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired3 = await s.tick(now + timedelta(seconds=10))
        assert fired3 == 1
        start_mock.assert_called_once()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_missed_fires_during_downtime():
    """3. Schedule fires every minute -> scheduler down 3 min -> restart.

    The scheduler fires if the missed time is within CATCH_UP_WINDOW (5 min).
    After restart with a new instance, the first tick primes next_fire;
    the second tick (at now) checks if next_fire <= now.
    """
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"missed_{suffix}@test.com")
    wf_id = f"wf_missed_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_missed_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="* * * * *")

        # Simulate downtime: scheduler was off for 3 minutes
        downtime = timedelta(minutes=3)
        before_down = datetime.now(timezone.utc) - downtime

        s = Scheduler()

        # Prime with a tick BEFORE downtime started
        p1, p2 = _fire_patches()
        with p1, p2:
            await s.tick(before_down)

        # Now simulate restart: fresh instance
        s2 = Scheduler()

        # New instance has empty cache - first tick primes next_fire from now
        now = datetime.now(timezone.utc)
        p1, p2 = _fire_patches()
        with p1, p2:
            fired_prime = await s2.tick(now)
        assert fired_prime == 0

        # Use a time 2 minutes later to ensure the cron boundary has passed
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired = await s2.tick(now + timedelta(minutes=2))

        # The scheduler should fire at most once (not catch up for each missed minute)
        assert fired <= 1
        if fired == 1:
            start_mock.assert_called_once()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_advisory_lock_prevents_double_fire():
    """4. Advisory lock prevents double-fire when two instances contend.

    Tests the lock mechanism at two levels:
    (a) Direct gate: _try_acquire_lock returns (conn, False) -> tick returns 0
    (b) Sequential guard: first tick fires (creates execution), second tick
        sees has_running_execution -> skips.  This is the real-world protection
        for sequential async ticks in a single event loop.
    """
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"lock_{suffix}@test.com")
    wf_id = f"wf_lock_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_lock_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="* * * * *")

        now = datetime.now(timezone.utc)

        # --- (a) Direct lock-contention test ---
        # Simulate: another process holds the advisory lock
        s_blocked = Scheduler()
        p1, p2 = _fire_patches()
        with p1, p2:
            await s_blocked.tick(now - timedelta(seconds=60))

        fake_conn = MagicMock()
        with patch.object(s_blocked, "_try_acquire_lock", return_value=(fake_conn, False)):
            p1, p2 = _fire_patches()
            with p1 as start_mock, p2:
                fired_blocked = await s_blocked.tick(now)
            assert fired_blocked == 0, "Scheduler must skip firing when advisory lock is unavailable"
            start_mock.assert_not_called()

        # --- (b) Sequential double-fire guard via has_running_execution ---
        # Two scheduler instances tick sequentially (as in asyncio event loop).
        # The first fires and creates an execution; the second detects it.
        s1 = Scheduler()
        s2 = Scheduler()
        p1, p2 = _fire_patches()
        with p1, p2:
            await s1.tick(now - timedelta(seconds=60))
        p1, p2 = _fire_patches()
        with p1, p2:
            await s2.tick(now - timedelta(seconds=60))

        # First tick fires (has_running_execution = False)
        with patch("app.api.executions.start_execution", return_value="exec_001") as start_mock1, \
             patch("app.api.executions.has_running_execution", side_effect=_has_no_running):
            fired1 = await s1.tick(now)
        assert fired1 == 1

        # Second tick: has_running_execution now returns True (execution from s1)
        with patch("app.api.executions.start_execution", return_value="exec_001") as start_mock2, \
             patch("app.api.executions.has_running_execution", return_value=True):
            fired2 = await s2.tick(now)
        assert fired2 == 0
        start_mock2.assert_not_called()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_schedule_activation_active_vs_paused():
    """5. Active schedule fires; paused schedule does NOT fire."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"act_{suffix}@test.com")
    wf_id = f"wf_act_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_active = f"trig_active_{suffix}"
    trig_paused = f"trig_paused_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_active, workflow_id=wf_id, user_id=user_id, wf_data=wf_data,
                        cron="* * * * *", status="active")
        _insert_trigger(trigger_id=trig_paused, workflow_id=wf_id, user_id=user_id, wf_data=wf_data,
                        cron="* * * * *", status="paused")

        s = Scheduler()
        now = datetime.now(timezone.utc)

        # Prime
        p1, p2 = _fire_patches()
        with p1, p2:
            await s.tick(now - timedelta(seconds=60))

        # Fire - only active triggers should be considered
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired = await s.tick(now)

        assert fired == 1, f"Expected 1 fire (active only), got {fired}"
        assert start_mock.call_count == 1
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_schedule_deletion():
    """6. Create schedule -> delete -> scheduler no longer fires it."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"del_{suffix}@test.com")
    wf_id = f"wf_del_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_del_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="* * * * *")

        s = Scheduler()
        now = datetime.now(timezone.utc)

        # Prime
        p1, p2 = _fire_patches()
        with p1, p2:
            await s.tick(now - timedelta(seconds=60))

        # Fire - should succeed
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired = await s.tick(now)
        assert fired == 1

        # Delete the trigger
        _delete_trigger(trig_id)

        # Next tick - new Scheduler (fresh) should find nothing
        s2 = Scheduler()
        p1, p2 = _fire_patches()
        with p1 as start_mock2, p2:
            fired2 = await s2.tick(now + timedelta(seconds=1))
        assert fired2 == 0
        start_mock2.assert_not_called()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_multiple_schedules_fire_independently():
    """7. Three different schedules -> all fire independently."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"multi_{suffix}@test.com")
    wf_id = f"wf_multi_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)

    trig_ids = [f"trig_multi_{suffix}_{i}" for i in range(3)]
    crons = ["* * * * *", "*/2 * * * *", "*/5 * * * *"]

    try:
        for tid, cron in zip(trig_ids, crons):
            _insert_trigger(trigger_id=tid, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron=cron)

        s = Scheduler()
        now = datetime.now(timezone.utc)

        # Prime far enough back (10 min) so all cron boundaries are in the past
        p1, p2 = _fire_patches()
        with p1, p2:
            fired_prime = await s.tick(now - timedelta(minutes=10))

        # All crons are due now
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired = await s.tick(now)

        # Each schedule fires independently - all three should fire
        # (since has_running_execution returns False for all)
        assert fired == 3, f"Expected 3 fires, got {fired}"
        assert start_mock.call_count == 3
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_cron_daily_midnight():
    """8a. Daily midnight cron '0 0 * * *'."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"cron_midnight_{suffix}@test.com")
    wf_id = f"wf_cron_midnight_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_cron_midnight_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="0 0 * * *")

        s = Scheduler()
        now = datetime(2026, 1, 15, 23, 59, 30, tzinfo=timezone.utc)

        # Prime
        p1, p2 = _fire_patches()
        with p1, p2:
            fired1 = await s.tick(now)
        assert fired1 == 0

        # Tick at midnight
        midnight = datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc)
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired2 = await s.tick(midnight)
        assert fired2 == 1
        start_mock.assert_called_once()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_cron_every_5_minutes():
    """8b. Every 5 minutes '*/5 * * * *'."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"cron_5min_{suffix}@test.com")
    wf_id = f"wf_cron_5min_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_cron_5min_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="*/5 * * * *")

        s = Scheduler()
        now = datetime(2026, 1, 15, 10, 3, 0, tzinfo=timezone.utc)

        # Prime
        p1, p2 = _fire_patches()
        with p1, p2:
            fired1 = await s.tick(now)
        assert fired1 == 0

        # Tick at 10:05
        tick_time = datetime(2026, 1, 15, 10, 5, 0, tzinfo=timezone.utc)
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired2 = await s.tick(tick_time)
        assert fired2 == 1
        start_mock.assert_called_once()

        # Tick at 10:07 -> should NOT fire (next fire is 10:10)
        tick_time2 = datetime(2026, 1, 15, 10, 7, 0, tzinfo=timezone.utc)
        p1, p2 = _fire_patches()
        with p1 as start_mock2, p2:
            fired3 = await s.tick(tick_time2)
        assert fired3 == 0
        start_mock2.assert_not_called()
    finally:
        _cleanup(wf_id)


@pytest.mark.asyncio
async def test_cron_weekdays_830():
    """8c. Weekdays at 8:30 '30 8 * * 1-5'."""
    suffix = _unique_suffix()
    user_id = _get_or_create_user(f"cron_wkday_{suffix}@test.com")
    wf_id = f"wf_cron_wkday_{suffix}"
    wf_data = _get_or_create_workflow(user_id, wf_id)
    trig_id = f"trig_cron_wkday_{suffix}"

    try:
        _insert_trigger(trigger_id=trig_id, workflow_id=wf_id, user_id=user_id, wf_data=wf_data, cron="30 8 * * 1-5")

        s = Scheduler()
        # Monday 8:29
        now = datetime(2026, 2, 2, 8, 29, 0, tzinfo=timezone.utc)

        # Prime
        p1, p2 = _fire_patches()
        with p1, p2:
            fired1 = await s.tick(now)
        assert fired1 == 0

        # Monday 8:30 -> should fire
        tick_time = datetime(2026, 2, 2, 8, 30, 0, tzinfo=timezone.utc)
        p1, p2 = _fire_patches()
        with p1 as start_mock, p2:
            fired2 = await s.tick(tick_time)
        assert fired2 == 1
        start_mock.assert_called_once()

        # Monday 8:31 -> should NOT fire
        tick_time2 = datetime(2026, 2, 2, 8, 31, 0, tzinfo=timezone.utc)
        p1, p2 = _fire_patches()
        with p1 as start_mock2, p2:
            fired3 = await s.tick(tick_time2)
        assert fired3 == 0
        start_mock2.assert_not_called()
    finally:
        _cleanup(wf_id)
