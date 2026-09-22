"""Data retention (M9 pruning) and delivery bookkeeping.

`prune(..)` deletes finished executions and their webhook delivery
records once they are older than the retention window. A daemon runs
the same routine on a fixed interval; admins can trigger it manually
via POST /api/admin/maintenance/prune.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Execution, WebhookDelivery

logger = logging.getLogger("maintenance")


def mark_execution_failed(execution_id: str, error: dict[str, Any]) -> None:
    """Terminal-fail an authoritative execution row from infrastructure
    code paths (queue exhaustion sweeps) that never ran the engine.

    Never overwrites a row that already reached a terminal state."""
    db = get_session()
    try:
        rec = db.get(Execution, execution_id)
        if rec is None or rec.status in ("success", "failed", "cancelled", "timeout"):
            return
        rec.status = "failed"
        rec.finished_at = datetime.now(UTC)
        rec.error = error
        db.commit()
    finally:
        db.close()


def recover_orphaned_executions(grace_seconds: float) -> int:
    """Re-enqueue executions stuck in ``queued`` beyond the grace period.

    Repairs Redis-loss scenarios: the execution row (authoritative) says
    queued but its transport job vanished (flush / volume loss). The
    enqueue idempotency guard makes concurrent sweeps across API/worker
    replicas safe: when the job still exists in the store, enqueue is a
    no-op; only genuinely lost jobs are recreated from the execution's
    own workflow snapshot. Returns the number re-enqueued."""
    from uuid import uuid4

    from sqlalchemy import select

    from app.api.executions import workflow_workspace
    from app.queue import get_queue

    cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
    db = get_session()
    requeued = 0
    try:
        stuck = db.scalars(
            select(Execution).where(Execution.status == "queued", Execution.started_at < cutoff)
        ).all()
        for rec in stuck:
            payload = {
                "workflow_data": rec.workflow_data,
                "trigger_items": rec.trigger_data or [],
                "trigger": rec.trigger,
                "user_id": rec.user_id,
                "workflow_id": rec.workflow_id,
                "version": rec.workflow_version,
                "workspace_id": workflow_workspace(db, rec.workflow_id),
            }
            job_id = f"job_{uuid4().hex[:12]}"
            enqueued = False
            try:
                enqueued = get_queue().enqueue(job_id, rec.id, payload)
            except Exception:
                logger.exception("orphan sweep: enqueue failed for %s", rec.id)
            if enqueued:
                requeued += 1
                logger.warning(
                    "orphan sweep: execution %s was queued since %s with no live "
                    "queue job — re-enqueued as %s",
                    rec.id, rec.started_at.isoformat(), job_id,
                )
        return requeued
    finally:
        db.close()


def prune(db: Session, before: datetime, *, dry_run: bool = False) -> dict[str, int]:
    """Delete finished executions (and their deliveries) older than `before`.

    Running/cancelling executions are never pruned. Returns
    {"executions": n, "deliveries": n, "running_kept": n}.
    """
    running_ids = set(
        db.scalars(
            select(Execution.id).where(Execution.status.in_(("running", "cancelling")))
        ).all()
    )
    base = select(Execution.id, Execution.trigger).where(Execution.started_at < before)
    if running_ids:
        base = base.where(~Execution.id.in_(running_ids))
    rows = db.execute(base).all()
    exec_ids = [rid for rid, _ in rows]
    webhook_exec_ids = {rid for rid, trigger in rows if trigger == "webhook"}
    delivery_ids: set[str] = set()
    if webhook_exec_ids:
        delivery_ids = set(
            db.scalars(
                select(WebhookDelivery.id).where(
                    WebhookDelivery.execution_id.in_(webhook_exec_ids)
                )
            ).all()
        )

    if dry_run:
        pending_deliveries = db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(WebhookDelivery.received_at < before)
        ) or 0
        return {
            "executions": len(exec_ids),
            "deliveries": pending_deliveries,
            "running_kept": len(running_ids),
        }

    n_deliveries = 0
    if exec_ids:
        db.execute(delete(Execution).where(Execution.id.in_(exec_ids)))
    if delivery_ids:
        # Mature deliveries whose execution was pruned disappear with it.
        db.execute(delete(WebhookDelivery).where(WebhookDelivery.id.in_(delivery_ids)))
        n_deliveries += len(delivery_ids)
    db.commit()
    return {
        "executions": len(exec_ids),
        "deliveries": n_deliveries,
        "running_kept": len(running_ids),
    }


def fail_expired_approvals(db: Session, now: datetime) -> int:
    """Auto-reject approvals whose timeout window elapsed (Phase 36).

    A waiting execution with ``pause_state.timeout_hours > 0`` whose
    paused_at + timeout is in the past fails with APPROVAL_TIMEOUT.
    ``timeout_hours=0`` means "no timeout". Terminal writes are direct:
    no worker owns a waiting execution. Returns the count expired.
    """
    rows = db.scalars(
        select(Execution).where(Execution.status == "waiting_approval")
    ).all()
    expired = 0
    for rec in rows:
        pause = rec.pause_state or {}
        try:
            hours = float(pause.get("timeout_hours") or 0)
        except (TypeError, ValueError):
            continue
        if hours <= 0:
            continue
        paused_at = pause.get("paused_at")
        if not paused_at:
            continue
        try:
            paused = datetime.fromisoformat(str(paused_at))
            if paused.tzinfo is None:
                paused = paused.replace(tzinfo=UTC)
        except ValueError:
            continue
        deadline = paused + timedelta(hours=hours)
        if now >= deadline:
            rec.status = "failed"
            rec.finished_at = now
            rec.error = {
                "code": "APPROVAL_TIMEOUT",
                "message": f"No decision within {hours:g}h — auto-rejected.",
            }
            rec.pause_state = None
            expired += 1
    if expired:
        db.commit()
        logger.info("auto-rejected %d approval(s) past their timeout", expired)
    return expired


class MaintenanceDaemon:
    """Periodically prunes old data, expires stale approvals, and auto-renews credentials."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._cred_task: asyncio.Task | None = None
        self._interval: timedelta | None = None

    def configure(self, interval: timedelta) -> None:
        self._interval = interval

    async def ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        if self._cred_task is None or self._cred_task.done():
            self._cred_task = asyncio.create_task(self._cred_renewal_loop())

    async def stop(self) -> None:
        """Cancel both daemon loops.

        Loop- and thread-safe: tasks owned by this loop are cancelled and
        awaited; tasks owned by another loop (production: the worker loop
        via ``runner.submit``) are cancelled via ``call_soon_threadsafe``
        and cleared without cross-loop awaiting — ``runner.shutdown()``
        finishes their teardown. Safe to call from the lifespan shutdown
        path before ``runner.shutdown()``.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        for task_attr in ("_task", "_cred_task"):
            task = getattr(self, task_attr)
            if task is None:
                continue
            if task.done():
                setattr(self, task_attr, None)
                continue
            task_loop = None
            try:
                task_loop = task.get_loop()
            except Exception:
                task_loop = None
            same_loop = running is not None and task_loop is running
            try:
                if same_loop:
                    task.cancel()
                elif task_loop is not None:
                    task_loop.call_soon_threadsafe(task.cancel)
                else:
                    task.cancel()
            except Exception:
                pass
            # Only await tasks owned by this loop; cross-loop tasks are
            # finished by runner.shutdown(). Clear the ref if already done.
            if same_loop:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("maintenance stop failed")
                setattr(self, task_attr, None)
            elif task.done():
                setattr(self, task_attr, None)

    async def _loop(self) -> None:
        interval = self._interval or timedelta(hours=24)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("maintenance tick failed")
            await asyncio.sleep(interval.total_seconds())

    async def _cred_renewal_loop(self) -> None:
        while True:
            try:
                await self.renew_credentials()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("credential renewal loop error")
            await asyncio.sleep(600)  # Sweep every 10 minutes

    async def renew_credentials(self) -> dict[str, int]:
        """Sweep and renew all credentials expiring within the next 30 minutes."""
        from app.credentials.auto_reconnect import auto_refresh_all_expiring_credentials

        db = get_session()
        try:
            return await auto_refresh_all_expiring_credentials(db, window_minutes=30)
        finally:
            db.close()

    async def tick(self, now: datetime | None = None, *, include_credential_renewal: bool = True) -> dict[str, Any] | None:
        """One prune pass + approval sweep + optional credential renewal sweep.

        Prune/approval results are never lost to renewal failures: renewal
        runs in isolation and reports ``{"error": ...}`` on failure.
        """
        from app.config import get_settings

        retention_days = get_settings().execution_retention_days
        now = now or datetime.now(UTC)
        before = now - timedelta(days=retention_days)
        db = get_session()
        try:
            pruned = prune(db, before)
            approvals_expired = fail_expired_approvals(db, now)
            cred_stats: dict[str, Any] = {"checked": 0, "refreshed": 0, "skipped": 0, "failed": 0}
            if include_credential_renewal:
                try:
                    cred_stats = await self.renew_credentials()
                except Exception as exc:
                    logger.exception("credential renewal during tick failed")
                    cred_stats = {"checked": 0, "refreshed": 0, "skipped": 0, "failed": 0, "error": str(exc)[:200]}
            return {**pruned, "approvals_expired": approvals_expired, "credentials_renewed": cred_stats}
        finally:
            db.close()


maintenance = MaintenanceDaemon()
