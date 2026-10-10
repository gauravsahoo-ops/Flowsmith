"""Schedule daemon (spec 33, 13): fires due cron triggers.

A background task on the worker loop scans `schedule_triggers` every 30
seconds. Per (workflow, node) it tracks the next fire time and only
fires once per occurrence; if the app was down across an occurrence it
does not catch up (missed > 5 minutes are skipped). Spec 8.4: never run
two executions of the same workflow at once — skip if one is running.

Timing rules (audit H18): occurrences are resolved on the rule's wall
clock and converted to UTC instants; seconds schedules are pure UTC
arithmetic, so a DST transition can neither duplicate nor drop a fire.
The next occurrence is advanced from the occurrence that just fired (not
from "now"), and an in-memory watermark refuses to fire the same
occurrence twice.

Locking (audit H29): on PostgreSQL a tick only runs while it holds the
advisory lock. Non-PostgreSQL engines (tests) run unlocked.

Quota (audit H9): every start passes the workspace's execution quota; a
plan limit behaves like "workflow already running" — the occurrence is
consumed with a warning instead of failing the whole tick.
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
# Safety bound for occurrence-resolution loops (1440 minutes = one day of
# minute-granular candidates); unreachable for any valid 5-field cron.
_MAX_OCCURRENCE_STEPS = 1440


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._next_fire: dict[tuple[str, str], datetime] = {}
        # Watermark of the last occurrence consumed per rule (audit H18):
        # blocks a duplicate fire when wall time repeats across a DST
        # transition or the system clock steps backwards.
        self._last_fired_for: dict[tuple[str, str], datetime] = {}
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
                self._cached_tick_s = await asyncio.to_thread(self._compute_tick_interval)
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

        The whole scan (advisory lock, queries, firing) is synchronous DB
        work, so it runs on a worker thread instead of the event loop.
        """
        return await asyncio.to_thread(self._tick_sync, now)

    def _tick_sync(self, now: datetime | None) -> int:
        """One scan; returns the number of executions fired.

        Acquires a PostgreSQL advisory lock so that only ONE scheduler
        replica fires per interval when multiple API processes run (audit
        phase 18). A tick that cannot take the lock does NOT run: falling
        through unlocked is exactly the double-fire the lock exists to
        prevent (audit H29). Non-PostgreSQL engines (tests) run unlocked.
        """
        now = now or datetime.now(timezone.utc)
        lock_conn = None
        locked = False
        try:
            lock_conn, locked = self._try_acquire_lock()
            if not locked:
                logger.info("scheduler tick skipped: advisory lock not acquired")
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

        On PostgreSQL, any failure returns (None, False): a lock we could
        not take (busy or error) means another replica owns the tick, so
        this one must not run unlocked (audit H29).
        """
        pg = False
        try:
            pg = engine.dialect.name == "postgresql"
            if not pg:
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
        except Exception as exc:
            logger.warning(
                "scheduler advisory lock unavailable (%s); %s",
                exc,
                "skipping tick" if pg else "running unlocked",
            )
            try:
                if "conn" in locals() and conn:  # type: ignore[possibly-undefined]
                    conn.close()
            except Exception:
                pass
            return None, not pg

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

    @staticmethod
    def _next_occurrence(cron: str, after: datetime, tz: ZoneInfo, local_now: datetime) -> datetime:
        """Next cron occurrence (UTC instant) strictly after both inputs.

        The candidate is generated on the naive wall clock in the rule's
        timezone and then resolved to an instant, so the wall time and the
        instant can never disagree the way `croniter(..., local_now)` does
        across a DST fall-back (audit H18). Candidates at or before
        `local_now` are skipped: missed occurrences stay missed (no
        catch-up burst).
        """
        limit = max(after, local_now)
        limit_utc = limit.astimezone(timezone.utc)
        wall = limit.astimezone(tz).replace(tzinfo=None)
        it = croniter(cron, wall)
        for _ in range(_MAX_OCCURRENCE_STEPS):
            candidate = it.get_next(datetime).replace(tzinfo=tz).astimezone(timezone.utc)
            if candidate > limit_utc:
                return candidate
        # Unreachable for a valid cron; keep the daemon moving instead of
        # re-firing the same (pathological) occurrence forever.
        logger.warning(
            "scheduler: no future occurrence for cron %r in tz %s; retrying in 60s",
            cron, tz,
        )
        return limit_utc + timedelta(minutes=1)

    def _try_start(
        self,
        rule: ScheduleTrigger,
        trigger_item: dict[str, Any],
        db: Session,
        occurrence: datetime,
    ) -> bool:
        """Start one execution for a due occurrence; returns True if queued.

        Order: skip-if-running (spec 8.4), then plan quota (audit H9), then
        start. A quota 402 is consumed exactly like a running workflow: log
        and skip this occurrence instead of failing the whole tick.
        """
        from app.api.executions import has_running_execution, start_execution, workflow_workspace

        if has_running_execution(db, rule.workflow_id):
            return False
        workspace_id = workflow_workspace(db, rule.workflow_id)
        from app.billing.service import enforce_can_start_execution
        from fastapi import HTTPException

        try:
            enforce_can_start_execution(db, workspace_id)
        except HTTPException as exc:
            logger.warning(
                "scheduler: workflow %s occurrence %s skipped: %s",
                rule.workflow_id, occurrence.isoformat(), exc.detail,
            )
            return False
        try:
            start_execution(
                db,
                workflow_id=rule.workflow_id,
                user_id=rule.user_id,
                version=rule.workflow_version,
                workflow_data=rule.workflow_data,
                trigger="schedule",
                trigger_items=[trigger_item],
                workspace_id=workspace_id,
            )
        except Exception as exc:
            try:
                from app.services.error_monitoring import ErrorMonitoringService
                ErrorMonitoringService.capture_error(
                    db=db,
                    error_data=exc,
                    user_id=rule.user_id,
                    workflow_id=rule.workflow_id,
                )
            except Exception:
                pass
            from app.engine.errors import WorkflowValidationError
            if isinstance(exc, WorkflowValidationError):
                logger.warning("scheduler: workflow %s credential validation failed: %s", rule.workflow_id, exc.message)
                return False
            raise
        return True

    def _fire(self, rule: ScheduleTrigger, now_utc: datetime, db: Session) -> bool:
        # Per-rule key (multi-rule support)
        key = (rule.id, "")
        tz = ZoneInfo(rule.timezone or "UTC")
        local_now = now_utc.astimezone(tz)
        next_fire = self._next_fire.get(key)

        # Seconds-based rules: use simple interval math (croniter doesn't
        # reliably handle 6-field cron with seconds). Timing is pure UTC so
        # a DST wall-clock jump cannot stretch or compress the interval.
        if rule.interval_type == "seconds" and rule.interval_value:
            interval_s = rule.interval_value
            if next_fire is None:
                # First tick after restart: catch up if last_fired_at is set and we missed fires
                if rule.last_fired_at:
                    last_utc = rule.last_fired_at.astimezone(timezone.utc)
                    missed = now_utc - last_utc
                    if missed >= timedelta(seconds=interval_s):
                        # Fire immediately for missed interval(s), then schedule next
                        self._next_fire[key] = now_utc + timedelta(seconds=interval_s)
                        # persist and fire
                        rule.last_fired_at = now_utc
                        db.commit()
                        trigger_item: dict[str, Any] = {
                            "timestamp": local_now.isoformat(),
                            "cron": rule.cron,
                            "timezone": rule.timezone,
                            "workflow_id": rule.workflow_id,
                        }
                        return self._try_start(rule, trigger_item, db, now_utc)
                # No last_fired_at or within window: prime the timer
                self._next_fire[key] = now_utc + timedelta(seconds=interval_s)
                return False
            if now_utc < next_fire:
                return False
            # Fire and schedule next from NOW (not from expected time)
            self._next_fire[key] = now_utc + timedelta(seconds=interval_s)
            rule.last_fired_at = now_utc
            db.commit()
            trigger_item = {
                "timestamp": next_fire.astimezone(tz).isoformat(),
                "cron": rule.cron,
                "timezone": rule.timezone,
                "workflow_id": rule.workflow_id,
            }
            return self._try_start(rule, trigger_item, db, next_fire)

        # All other intervals: use croniter (5-field cron works correctly)
        if next_fire is None:
            # First tick after restart: catch up if last_fired_at is set
            if rule.last_fired_at:
                last_utc = rule.last_fired_at.astimezone(timezone.utc)
                limit_utc = local_now.astimezone(timezone.utc)
                # Check how many fires were missed (wall clock in rule tz)
                missed_iter = croniter(rule.cron, last_utc.astimezone(tz).replace(tzinfo=None))
                catch_up_fires: list[datetime] = []
                for _ in range(_MAX_OCCURRENCE_STEPS):
                    candidate = missed_iter.get_next(datetime).replace(tzinfo=tz).astimezone(timezone.utc)
                    if candidate > limit_utc:
                        break
                    if (limit_utc - candidate) <= CATCH_UP_WINDOW:
                        catch_up_fires.append(candidate)
                    else:
                        break
                if catch_up_fires:
                    # Fire for the most recent missed occurrence
                    fire_at = catch_up_fires[-1]
                    self._next_fire[key] = self._next_occurrence(rule.cron, fire_at, tz, local_now)
                    self._last_fired_for[key] = fire_at
                    rule.last_fired_at = now_utc
                    db.commit()
                    occ = fire_at.astimezone(tz)
                    trigger_item = {
                        "timestamp": occ.isoformat(),
                        "cron": rule.cron,
                        "timezone": rule.timezone,
                        "workflow_id": rule.workflow_id,
                        # Standard human-readable fields
                        "Readable date": occ.strftime("%B ") + (
                            f"{occ.day}{'th' if 11 <= occ.day <= 13 else {1:'st',2:'nd',3:'rd'}.get(occ.day % 10, 'th')}"
                        ) + occ.strftime(f" %Y, {occ.hour % 12 or 12}:{occ.minute:02d}:{occ.second:02d} {'am' if occ.hour < 12 else 'pm'}"),
                        "Readable time": f"{occ.hour % 12 or 12}:{occ.minute:02d}:{occ.second:02d} {'am' if occ.hour < 12 else 'pm'}",
                        "Day of week": occ.strftime("%A"),
                        "Year": str(occ.year),
                        "Month": occ.strftime("%B"),
                        "Day of month": f"{occ.day:02d}",
                        "Hour": str(occ.hour),
                        "Minute": f"{occ.minute:02d}",
                        "Second": f"{occ.second:02d}",
                        "Timezone": rule.timezone,
                    }
                    return self._try_start(rule, trigger_item, db, fire_at)
            # No catch-up needed: prime the timer
            self._next_fire[key] = self._next_occurrence(rule.cron, local_now, tz, local_now)
            return False  # first registration: fire from the next boundary

        if local_now < next_fire:
            return False

        prev_fire = self._last_fired_for.get(key)
        if prev_fire is not None and next_fire <= prev_fire:
            # Same occurrence already consumed (DST wall-time repeat or a
            # clock step backwards): skip it and move on (audit H18).
            logger.warning(
                "scheduler: workflow %s occurrence %s already fired; skipping",
                rule.workflow_id, next_fire.isoformat(),
            )
            self._next_fire[key] = self._next_occurrence(rule.cron, next_fire, tz, local_now)
            self._last_fired_for[key] = next_fire
            return False

        # Advance from the OCCURRENCE just fired (not from the current wall
        # time) so the schedule stays anchored to its own cadence; the
        # helper drops any occurrence that already fell behind `local_now`.
        self._next_fire[key] = self._next_occurrence(rule.cron, next_fire, tz, local_now)
        self._last_fired_for[key] = next_fire
        rule.last_fired_at = now_utc
        db.commit()

        occ = next_fire.astimezone(tz)
        trigger_item = {
            "timestamp": occ.isoformat(),
            "cron": rule.cron,
            "timezone": rule.timezone,
            "workflow_id": rule.workflow_id,
            # Standard human-readable fields
            "Readable date": occ.strftime("%B ") + (
                f"{occ.day}{'th' if 11 <= occ.day <= 13 else {1:'st',2:'nd',3:'rd'}.get(occ.day % 10, 'th')}"
            ) + occ.strftime(f" %Y, {occ.hour % 12 or 12}:{occ.minute:02d}:{occ.second:02d} {'am' if occ.hour < 12 else 'pm'}"),
            "Readable time": f"{occ.hour % 12 or 12}:{occ.minute:02d}:{occ.second:02d} {'am' if occ.hour < 12 else 'pm'}",
            "Day of week": occ.strftime("%A"),
            "Year": str(occ.year),
            "Month": occ.strftime("%B"),
            "Day of month": f"{occ.day:02d}",
            "Hour": str(occ.hour),
            "Minute": f"{occ.minute:02d}",
            "Second": f"{occ.second:02d}",
            "Timezone": rule.timezone,
        }
        return self._try_start(rule, trigger_item, db, next_fire)


scheduler = Scheduler()
