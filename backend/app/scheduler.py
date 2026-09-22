"""Schedule daemon (spec 33, 13): fires due cron triggers.

A background task on the worker loop scans `schedule_triggers` every 30
seconds. Per (workflow, node) it tracks the next fire time and only
fires once per occurrence; if the app was down across an occurrence it
does not catch up (missed > 5 minutes are skipped). Spec 8.4: never run
two executions of the same workflow at once — skip if one is running.

Single-instance v1 (in-process); a distributed scheduler would add a DB
lock / unique execution key (spec 33).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from croniter import croniter
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.db import engine, get_session
from app.models import ScheduleTrigger

logger = logging.getLogger("scheduler")

TICK_INTERVAL_S = 30
CATCH_UP_WINDOW = timedelta(minutes=5)
# Advisory-lock key for distributed scheduler coordination (audit phase 18).
# Fits in signed 32-bit range expected by pg_try_advisory_lock(int).
SCHEDULER_LOCK_KEY = 0x7EED01  # 8293471


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._next_fire: dict[tuple[str, str], datetime] = {}
        self._cached_tick_s: float = float(TICK_INTERVAL_S)  # avoids DB call every sleep cycle

    async def ensure_started(self) -> None:
        """Start the daemon (runs on the worker loop)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                fired = await self.tick()
                # Refresh tick interval once per tick (not every sleep) to avoid
                # opening a DB session on every 250ms cancel-poll cycle.
                self._cached_tick_s = self._compute_tick_interval()
            except Exception:
                logger.exception("scheduler tick failed")
                fired = 0
            await asyncio.sleep(self._cached_tick_s)

    def _compute_tick_interval(self) -> float:
        """Return the optimal sleep duration before the next tick.

        When active rules include seconds-level schedules, poll every
        2 seconds so we don't miss fires.  Otherwise use the default
        30-second interval to avoid unnecessary DB scans.
        """
        try:
            db = get_session()
            try:
                rules = db.scalars(
                    select(ScheduleTrigger).where(ScheduleTrigger.status == "active")
                ).all()
                for r in rules:
                    if r.interval_type == "seconds":
                        return 2.0
            finally:
                db.close()
        except Exception:
            pass
        return float(TICK_INTERVAL_S)

    async def tick(self, now: datetime | None = None) -> int:
        """One scan; returns the number of executions fired.

        Acquires a PostgreSQL advisory lock so that only ONE scheduler
        replica fires per interval when multiple API processes run (audit
        phase 18). Falls back to unlocked execution on non-PostgreSQL
        engines (tests) or when the lock cannot be obtained.
        """
        now = now or datetime.now(timezone.utc)
        lock_conn = None
        locked = False
        try:
            lock_conn, locked = self._try_acquire_lock()
            if lock_conn is not None and not locked:
                return 0
            db = get_session()
            try:
                rules = db.scalars(
                    select(ScheduleTrigger).where(ScheduleTrigger.status == "active")
                ).all()
                fired = 0
                for rule in rules:
                    if self._fire(rule, now, db):
                        fired += 1
                        logger.info(
                            "scheduler fired workflow=%s node=%s cron=%s tz=%s",
                            rule.workflow_id, rule.node_id, rule.cron, rule.timezone,
                        )
                return fired
            finally:
                db.close()
        finally:
            if lock_conn is not None and locked:
                self._release_lock(lock_conn)

    def _try_acquire_lock(self):
        """Try pg advisory lock.

        Returns (conn, acquired). conn is the raw connection holding the
        lock when acquired, else None. On non-PostgreSQL engines returns
        (None, True) meaning "run unlocked" (tests).
        """
        try:
            if engine.dialect.name != "postgresql":
                return None, True
            conn = engine.connect()
            acquired = conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"),
                {"k": SCHEDULER_LOCK_KEY},
            ).scalar()
            if not acquired:
                conn.close()
                return None, False
            return conn, True
        except Exception as exc:  # pragma: no cover — fallback for test SQLite
            logger.debug("scheduler advisory lock unavailable (%s); running unlocked", exc)
            try:
                if "conn" in locals() and conn:  # type: ignore[possibly-undefined]
                    conn.close()
            except Exception:
                pass
            return None, True

    def _release_lock(self, conn) -> None:
        try:
            conn.execute(
                text("SELECT pg_advisory_unlock(:k)"),
                {"k": SCHEDULER_LOCK_KEY},
            )
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _fire(self, rule: ScheduleTrigger, now_utc: datetime, db: Session) -> bool:
        # Per-rule key (multi-rule support)
        key = (rule.id, "")
        tz = ZoneInfo(rule.timezone or "UTC")
        local_now = now_utc.astimezone(tz)
        next_fire = self._next_fire.get(key)

        # Seconds-based rules: use simple interval math (croniter doesn't
        # reliably handle 6-field cron with seconds).
        if rule.interval_type == "seconds" and rule.interval_value:
            interval_s = rule.interval_value
            if next_fire is None:
                # First tick after restart: catch up if last_fired_at is set and we missed fires
                if rule.last_fired_at:
                    last_local = rule.last_fired_at.astimezone(tz)
                    missed = local_now - last_local
                    if missed >= timedelta(seconds=interval_s):
                        # Fire immediately for missed interval(s), then schedule next
                        self._next_fire[key] = local_now + timedelta(seconds=interval_s)
                        # persist and fire
                        rule.last_fired_at = now_utc
                        db.commit()
                        from app.api.executions import has_running_execution, start_execution, workflow_workspace
                        if has_running_execution(db, rule.workflow_id):
                            return False
                        trigger_item: dict[str, Any] = {
                            "timestamp": local_now.isoformat(),
                            "cron": rule.cron,
                            "timezone": rule.timezone,
                            "workflow_id": rule.workflow_id,
                        }
                        try:
                            start_execution(
                                db,
                                workflow_id=rule.workflow_id,
                                user_id=rule.user_id,
                                version=rule.workflow_version,
                                workflow_data=rule.workflow_data,
                                trigger="schedule",
                                trigger_items=[trigger_item],
                                workspace_id=workflow_workspace(db, rule.workflow_id),
                            )
                        except Exception as exc:
                            from app.engine.errors import WorkflowValidationError
                            if isinstance(exc, WorkflowValidationError):
                                logger.warning("scheduler: workflow %s credential validation failed: %s", rule.workflow_id, exc.message)
                                return False
                            raise
                        return True
                # No last_fired_at or within window: prime the timer
                self._next_fire[key] = local_now + timedelta(seconds=interval_s)
                return False
            if local_now < next_fire:
                return False
            # Fire and schedule next from NOW (not from expected time)
            self._next_fire[key] = local_now + timedelta(seconds=interval_s)
            rule.last_fired_at = now_utc
            db.commit()
            from app.api.executions import has_running_execution, start_execution, workflow_workspace
            if has_running_execution(db, rule.workflow_id):
                return False
            trigger_item: dict[str, Any] = {
                "timestamp": next_fire.isoformat(),
                "cron": rule.cron,
                "timezone": rule.timezone,
                "workflow_id": rule.workflow_id,
            }
            try:
                start_execution(
                    db,
                    workflow_id=rule.workflow_id,
                    user_id=rule.user_id,
                    version=rule.workflow_version,
                    workflow_data=rule.workflow_data,
                    trigger="schedule",
                    trigger_items=[trigger_item],
                    workspace_id=workflow_workspace(db, rule.workflow_id),
                )
            except Exception as exc:
                from app.engine.errors import WorkflowValidationError
                if isinstance(exc, WorkflowValidationError):
                    logger.warning("scheduler: workflow %s credential validation failed: %s", rule.workflow_id, exc.message)
                    return False
                raise
            return True

        # All other intervals: use croniter (5-field cron works correctly)
        if next_fire is None:
            # First tick after restart: catch up if last_fired_at is set
            if rule.last_fired_at:
                last_local = rule.last_fired_at.astimezone(tz)
                # Check how many fires were missed
                missed_iter = croniter(rule.cron, last_local)
                catch_up_fires: list[datetime] = []
                while True:
                    candidate = missed_iter.get_next(datetime)
                    if candidate > local_now:
                        break
                    if candidate > last_local and (local_now - candidate) <= CATCH_UP_WINDOW:
                        catch_up_fires.append(candidate)
                    elif candidate > last_local:
                        break
                if catch_up_fires:
                    # Fire for the most recent missed occurrence
                    fire_at = catch_up_fires[-1]
                    next_fire_after = croniter(rule.cron, local_now).get_next(datetime)
                    self._next_fire[key] = next_fire_after
                    rule.last_fired_at = now_utc
                    db.commit()
                    from app.api.executions import has_running_execution, start_execution, workflow_workspace
                    if has_running_execution(db, rule.workflow_id):
                        return False
                    trigger_item: dict[str, Any] = {
                        "timestamp": fire_at.isoformat(),
                        "cron": rule.cron,
                        "timezone": rule.timezone,
                        "workflow_id": rule.workflow_id,
                        # Standard human-readable fields
                        "Readable date": fire_at.strftime("%B ") + (
                            f"{fire_at.day}{'th' if 11 <= fire_at.day <= 13 else {1:'st',2:'nd',3:'rd'}.get(fire_at.day % 10, 'th')}"
                        ) + fire_at.strftime(f" %Y, {fire_at.hour % 12 or 12}:{fire_at.minute:02d}:{fire_at.second:02d} {'am' if fire_at.hour < 12 else 'pm'}"),
                        "Readable time": f"{fire_at.hour % 12 or 12}:{fire_at.minute:02d}:{fire_at.second:02d} {'am' if fire_at.hour < 12 else 'pm'}",
                        "Day of week": fire_at.strftime("%A"),
                        "Year": str(fire_at.year),
                        "Month": fire_at.strftime("%B"),
                        "Day of month": f"{fire_at.day:02d}",
                        "Hour": str(fire_at.hour),
                        "Minute": f"{fire_at.minute:02d}",
                        "Second": f"{fire_at.second:02d}",
                        "Timezone": rule.timezone,
                    }
                    try:
                        start_execution(
                            db,
                            workflow_id=rule.workflow_id,
                            user_id=rule.user_id,
                            version=rule.workflow_version,
                            workflow_data=rule.workflow_data,
                            trigger="schedule",
                            trigger_items=[trigger_item],
                            workspace_id=workflow_workspace(db, rule.workflow_id),
                        )
                    except Exception as exc:
                        from app.engine.errors import WorkflowValidationError
                        if isinstance(exc, WorkflowValidationError):
                            logger.warning("scheduler: workflow %s credential validation failed: %s", rule.workflow_id, exc.message)
                            return False
                        raise
                    return True
            # No catch-up needed: prime the timer
            next_fire = croniter(rule.cron, local_now).get_next(datetime)
            self._next_fire[key] = next_fire
            return False  # first registration: fire from the next boundary

        if local_now < next_fire:
            return False

        from app.api.executions import has_running_execution, start_execution, workflow_workspace

        # Compute next fire from ACTUAL current time (not the expected
        # fire time) so sub-minute intervals don't compound drift.
        self._next_fire[key] = croniter(rule.cron, local_now).get_next(datetime)
        rule.last_fired_at = now_utc
        db.commit()
        if has_running_execution(db, rule.workflow_id):
            return False

        trigger_item: dict[str, Any] = {
            "timestamp": next_fire.isoformat(),
            "cron": rule.cron,
            "timezone": rule.timezone,
            "workflow_id": rule.workflow_id,
            # Standard human-readable fields
            "Readable date": next_fire.strftime("%B ") + (
                f"{next_fire.day}{'th' if 11 <= next_fire.day <= 13 else {1:'st',2:'nd',3:'rd'}.get(next_fire.day % 10, 'th')}"
            ) + next_fire.strftime(f" %Y, {next_fire.hour % 12 or 12}:{next_fire.minute:02d}:{next_fire.second:02d} {'am' if next_fire.hour < 12 else 'pm'}"),
            "Readable time": f"{next_fire.hour % 12 or 12}:{next_fire.minute:02d}:{next_fire.second:02d} {'am' if next_fire.hour < 12 else 'pm'}",
            "Day of week": next_fire.strftime("%A"),
            "Year": str(next_fire.year),
            "Month": next_fire.strftime("%B"),
            "Day of month": f"{next_fire.day:02d}",
            "Hour": str(next_fire.hour),
            "Minute": f"{next_fire.minute:02d}",
            "Second": f"{next_fire.second:02d}",
            "Timezone": rule.timezone,
        }
        try:
            start_execution(
                db,
                workflow_id=rule.workflow_id,
                user_id=rule.user_id,
                version=rule.workflow_version,
                workflow_data=rule.workflow_data,
                trigger="schedule",
                trigger_items=[trigger_item],
                workspace_id=workflow_workspace(db, rule.workflow_id),
            )
        except Exception as exc:
            from app.engine.errors import WorkflowValidationError
            if isinstance(exc, WorkflowValidationError):
                logger.warning("scheduler: workflow %s credential validation failed: %s", rule.workflow_id, exc.message)
                return False
            raise
        return True


scheduler = Scheduler()
