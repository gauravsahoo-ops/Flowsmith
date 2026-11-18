"""Database-backed job queue (Phase 15, spec 13/34/58).

Jobs live in the ``jobs`` table. Claiming is a single atomic
``UPDATE ... WHERE id = (SELECT ...)``: SQLite serializes writers and
PostgreSQL executes the statement atomically, so two workers can never
claim the same row (spec 58). Crashed workers are detected by a stale
``heartbeat_at`` and their jobs re-queued (spec 34.1).

Works on the same database as the rest of the app — zero extra
infrastructure. The Redis backend is the alternative when the queue
must live outside the database.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, text, update

from app.db import get_session
from app.models import Job
from app.models.job import CLAIMED, DONE, FAILED, QUEUED
from app.queue import QueueBackend, QueueJob, register_queue
from app.security.jwt import get_worker_id

logger = logging.getLogger("queue.db")

CLAIM_SQL = text(
    """
    WITH next AS (
        SELECT id FROM jobs
        WHERE status = :queued
          AND (next_retry_at IS NULL OR next_retry_at <= :now)
        ORDER BY created_at, id
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE jobs
    SET status = :claimed, claimed_by = :worker, claimed_at = :now,
        attempts = attempts + 1
    FROM next
    WHERE jobs.id = next.id
    RETURNING jobs.id
    """
)

# Poison-job guard: once a job exhausts its attempts (claims without a
# completing run — i.e. repeated worker crashes / stalled nodes), stop
# recycling it: fail the job AND its authoritative execution row.
SELECT_STALE_SQL = text(
    """
    SELECT id, execution_id, attempts FROM jobs
    WHERE status = :claimed AND (heartbeat_at IS NULL OR heartbeat_at < :cutoff)
    ORDER BY created_at, id
    LIMIT 500
    """
)


@register_queue
class DbJobQueue(QueueBackend):
    name = "db"

    def enqueue(self, job_id: str, execution_id: str, payload: dict[str, Any]) -> bool:
        from app.telemetry.tracer import inject_trace_context
        payload_to_store = dict(payload)
        inject_trace_context(payload_to_store)
        db = get_session()
        try:
            db.add(Job(id=job_id, execution_id=execution_id, status=QUEUED, payload=payload_to_store))
            db.commit()
            return True
        except Exception as exc:
            logger.warning("DbJobQueue.enqueue failed: %s", exc)
            db.rollback()
            return False  # duplicate execution_id (idempotency guard)
        finally:
            db.close()

    def requeue(self, execution_id: str, payload: dict[str, Any]) -> bool:
        """Reset the existing job row for this execution back to queued
        (durable resume). Keeps job ids stable across resumes."""
        db = get_session()
        try:
            row = db.query(Job).filter(Job.execution_id == execution_id).first()
            if row is None:
                return False
            # Never reset a job a live worker is actively heartbeating —
            # that would double-execute. Fresh claims refuse the resume;
            # stale claims are recover_stale's territory.
            if (
                row.status == CLAIMED
                and row.heartbeat_at is not None
                and row.heartbeat_at > datetime.now(UTC) - timedelta(seconds=60)
            ):
                return False
            row.status = QUEUED
            row.payload = payload
            row.claimed_by = None
            row.claimed_at = None
            row.heartbeat_at = None
            row.error = None
            row.finished_at = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def _to_queue_job(row: Job) -> QueueJob:
        return QueueJob(
            id=row.id,
            execution_id=row.execution_id,
            payload=row.payload,
            status=row.status,
            attempts=row.attempts,
            claimed_by=row.claimed_by,
            claimed_at=row.claimed_at.isoformat() if row.claimed_at else None,
        )

    def _claim_sqlite(self, db, now: datetime) -> QueueJob | None:
        """Portable claim path for SQLite.

        SQLite does not support ``FOR UPDATE SKIP LOCKED`` or
        ``UPDATE ... FROM ... RETURNING``. Select the oldest eligible row,
        then perform a conditional update on its status. If another writer
        wins the race, the update affects zero rows and this caller simply
        retries on the next poll.
        """
        row = (
            db.query(Job)
            .filter(
                Job.status == QUEUED,
                or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
            )
            .order_by(Job.created_at, Job.id)
            .first()
        )
        if row is None:
            db.rollback()
            return None
        updated = (
            db.query(Job)
            .filter(Job.id == row.id, Job.status == QUEUED)
            .update(
                {
                    Job.status: CLAIMED,
                    Job.claimed_by: get_worker_id(),
                    Job.claimed_at: now,
                    Job.attempts: Job.attempts + 1,
                },
                synchronize_session=False,
            )
        )
        if not updated:
            db.rollback()
            return None
        db.commit()
        db.refresh(row)
        return self._to_queue_job(row)

    def claim(self) -> QueueJob | None:
        db = get_session()
        try:
            now = datetime.now(UTC)
            if db.get_bind().dialect.name == "sqlite":
                return self._claim_sqlite(db, now)
            claimed_id = db.execute(
                CLAIM_SQL,
                {"claimed": CLAIMED, "worker": get_worker_id(),
                 "now": now, "queued": QUEUED},
            ).scalar_one_or_none()
            if claimed_id is None:
                db.rollback()
                return None
            row = db.get(Job, claimed_id)
            db.commit()
            if row is None:
                return None
            return self._to_queue_job(row)
        except Exception as exc:
            logger.exception("DbJobQueue.claim failed: %s", exc)
            db.rollback()
            return None
        finally:
            db.close()

    def complete(self, job_id: str, status: str = DONE, error: dict | None = None) -> None:
        db = get_session()
        try:
            row = db.get(Job, job_id)
            if row is not None and row.status not in (DONE, FAILED):
                # Fence: if a stale claim was requeued and re-claimed by
                # another worker, the old worker must not close the job out
                # from under the new run.
                if row.status == CLAIMED and row.claimed_by is not None and row.claimed_by != get_worker_id():
                    logger.warning(
                        "queue.db: refusing stale complete of %s (owned by %s)",
                        job_id, row.claimed_by,
                    )
                    return
                row.status = status
                row.finished_at = datetime.now(UTC)
                row.error = error
                db.commit()
        finally:
            db.close()

    def heartbeat(self, job_id: str) -> None:
        db = get_session()
        try:
            row = db.get(Job, job_id)
            # Only the current owner refreshes: a pre-stale worker must not
            # heartbeat a claim that was requeued and re-claimed elsewhere.
            if (
                row is not None
                and row.status == CLAIMED
                and (row.claimed_by is None or row.claimed_by == get_worker_id())
            ):
                row.heartbeat_at = datetime.now(UTC)
                db.commit()
        finally:
            db.close()

    def recover_stale(self, stale_after_s: float) -> int:
        from app.config import get_settings
        from app.queue import retry_delay_s

        settings = get_settings()
        db = get_session()
        try:
            now = datetime.now(UTC)
            cutoff = now - timedelta(seconds=stale_after_s)
            stale_rows = db.execute(
                SELECT_STALE_SQL,
                {"claimed": CLAIMED, "cutoff": cutoff},
            ).all()
            if not stale_rows:
                return 0
            exhausted_ids: list[str] = []
            requeue_updates: dict[str, datetime | None] = {}
            for job_id, execution_id, attempts in stale_rows:
                if int(attempts) >= settings.queue_max_attempts:
                    exhausted_ids.append(str(job_id))
                    continue
                delay_s = retry_delay_s(int(attempts))
                requeue_updates[str(job_id)] = (
                    now + timedelta(seconds=delay_s) if delay_s > 0 else None
                )
            if exhausted_ids:
                exec_map = {
                    str(job_id): str(exec_id)
                    for job_id, exec_id, _ in stale_rows
                    if str(job_id) in set(exhausted_ids)
                }
                error = {
                    "code": "MAX_ATTEMPTS_EXCEEDED",
                    "message": (
                        f"Job exceeded {settings.queue_max_attempts} claim attempts "
                        "without completing (worker crashes or stalled execution)."
                    ),
                }
                with db.begin_nested():
                    db.query(Job).filter(Job.id.in_(exhausted_ids)).update(
                        {Job.status: FAILED, Job.finished_at: now, Job.error: error},
                        synchronize_session=False,
                    )
                    from app.models import Execution

                    for exec_id in exec_map.values():
                        db.execute(
                            update(Execution)
                            .where(
                                Execution.id == exec_id,
                                Execution.status.in_(("queued", "running", "cancelling")),
                            )
                            .values(status="failed", finished_at=now, error=error)
                        )
                db.commit()
                logger.warning(
                    "queue.db: %d job(s) terminally failed after %d attempts: %s",
                    len(exhausted_ids), settings.queue_max_attempts, exhausted_ids,
                )
            requeued_count = 0
            if requeue_updates:
                for job_id, next_retry_at in requeue_updates.items():
                    db.query(Job).filter(Job.id == job_id, Job.status == CLAIMED).update(
                        {
                            Job.status: QUEUED,
                            Job.claimed_by: None,
                            Job.claimed_at: None,
                            Job.heartbeat_at: None,
                            Job.next_retry_at: next_retry_at,
                        },
                        synchronize_session=False,
                    )
                db.commit()
                requeued_count = len(requeue_updates)
            return requeued_count
        finally:
            db.close()
