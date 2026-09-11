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

from sqlalchemy import text, update

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

REQUEUE_SQL = text(
    """
    UPDATE jobs
    SET status = :queued, claimed_by = NULL, claimed_at = NULL,
        heartbeat_at = NULL, next_retry_at = :next_retry_at
    WHERE id = ANY(:job_ids)
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

FAIL_JOB_SQL = text(
    "UPDATE jobs SET status = :failed, finished_at = :now, error = :error "
    "WHERE id = ANY(:job_ids)"
)


@register_queue
class DbJobQueue(QueueBackend):
    name = "db"

    def enqueue(self, job_id: str, execution_id: str, payload: dict[str, Any]) -> bool:
        db = get_session()
        try:
            db.add(Job(id=job_id, execution_id=execution_id, status=QUEUED, payload=payload))
            db.commit()
            return True
        except Exception:
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

    def claim(self) -> QueueJob | None:
        db = get_session()
        try:
            claimed_id = db.execute(
                CLAIM_SQL,
                {"claimed": CLAIMED, "worker": get_worker_id(),
                 "now": datetime.now(UTC), "queued": QUEUED},
            ).scalar_one_or_none()
            if claimed_id is None:
                db.rollback()
                return None
            row = db.get(Job, claimed_id)
            db.commit()
            if row is None:
                return None
            return QueueJob(
                id=row.id, execution_id=row.execution_id, payload=row.payload,
                status=row.status, attempts=row.attempts,
                claimed_by=row.claimed_by,
                claimed_at=row.claimed_at.isoformat() if row.claimed_at else None,
            )
        except Exception:
            db.rollback()
            return None
        finally:
            db.close()

    def complete(self, job_id: str, status: str = DONE, error: dict | None = None) -> None:
        db = get_session()
        try:
            row = db.get(Job, job_id)
            if row is not None and row.status not in (DONE, FAILED):
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
            if row is not None and row.status == CLAIMED:
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
                import psycopg2.extras as _pgjson  # noqa: F401
                with db.begin_nested():
                    db.execute(
                        FAIL_JOB_SQL,
                        {"failed": FAILED, "now": now, "error": _pgjson.Json(error),
                         "job_ids": exhausted_ids},
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
                ids = list(requeue_updates)
                next_at = [requeue_updates[i] for i in ids]
                # Row-wise next_retry_at via executemany-style binding.
                db.execute(
                    REQUEUE_SQL,
                    [{"queued": QUEUED, "job_ids": [jid], "next_retry_at": at} for jid, at in zip(ids, next_at)],
                )
                db.commit()
                requeued_count = len(ids)
            return requeued_count
        finally:
            db.close()
