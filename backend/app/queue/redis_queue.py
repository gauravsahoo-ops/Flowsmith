"""Redis-backed job queue (Phase 15, spec 13/34/58).

Design mirrors the DB backend so workers are interchangeable:

- ``queue:jobs``            — FIFO list of pending job ids
  (LPUSH enqueue, LMOVE claim)
- ``queue:jobs:scheduled``  — zset of jobs waiting out a retry backoff
  (score = ready epoch; claim() promotes due entries back onto the FIFO)
- ``queue:jobs:processing`` — ids currently being worked on
  (crash-safe: a worker that dies mid-run leaves its job here, and the
  stale sweep re-queues it or terminally fails it after the configured
  max attempts)
- ``queue:meta:{job_id}``   — hash: status, payload, attempts, claimed_by,
  claimed_at, heartbeat_at, error. Terminal jobs carry a TTL
  (QUEUE_REDIS_JOB_META_TTL_S): the executions table stays authoritative,
  so Redis bookkeeping is evictable.
- ``queue:execs``           — set of already-queued execution ids
  (idempotency guard for retried deliveries); entries are removed when
  their job reaches a terminal state

Claiming moves the oldest id out of ``queue:jobs`` atomically (LMOVE),
so two workers can never take the same job; the meta hash is then
updated by the exclusive owner. Crash windows (crash right after LMOVE
or mid-enqueue) are closed by the stale sweep, which re-queues ids with
no/missing/stale heartbeats.

Requires ``REDIS_URL`` and the optional ``redis`` package
(requirements.txt). The DB backend remains the zero-infra default.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, cast

from app.config import get_settings
from app.queue import QueueBackend, QueueJob, register_queue
from app.security.jwt import get_worker_id

logger = logging.getLogger("queue.redis")

QUEUE_KEY = "queue:jobs"
PROCESSING_KEY = "queue:jobs:processing"
META_PREFIX = "queue:meta:"
EXECS_KEY = "queue:execs"
SCHEDULED_KEY = "queue:jobs:scheduled"  # zset of job_id -> ready epoch (retry backoff)

_CLAIMED = "claimed"
_QUEUED = "queued"
_DONE = "done"
_FAILED = "failed"


def _now() -> str:
    return str(time.time())


def _meta_key(job_id: str) -> str:
    return f"{META_PREFIX}{job_id}"


@register_queue
class RedisJobQueue(QueueBackend):
    name = "redis"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.redis_url:
            raise ValueError("RedisJobQueue requires REDIS_URL (set queue_backend=redis + REDIS_URL).")
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - guarded by requirements
            raise RuntimeError(
                "The redis package is required for the redis queue backend: "
                "pip install redis"
            ) from exc
        self._conn = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def enqueue(self, job_id: str, execution_id: str, payload: dict[str, Any]) -> bool:
        added = self._conn.sadd(EXECS_KEY, execution_id)
        if not added:
            return False  # execution already queued (idempotency guard)
        meta = {
            "status": _QUEUED,
            "execution_id": execution_id,
            "payload": json.dumps(payload),
            "attempts": "0",
            "claimed_by": "",
            "claimed_at": "",
            "heartbeat_at": "",
            "error": "",
        }
        self._conn.hset(_meta_key(job_id), mapping=cast(Any, meta))
        self._conn.hset(f"{META_PREFIX}exec_to_job", execution_id, job_id)
        self._conn.lpush(QUEUE_KEY, job_id)
        return True

    def requeue(self, execution_id: str, payload: dict[str, Any]) -> bool:
        """Reset a finished job for this execution back to queued with new
        payload (durable resume). The execution id is already in the
        guard set, so this reuses its existing meta hash."""
        raw = self._conn.hget(f"{META_PREFIX}exec_to_job", execution_id)
        if not raw:
            return False
        job_id = str(raw)
        meta = {
            "status": _QUEUED,
            "payload": json.dumps(payload),
            "claimed_by": "",
            "claimed_at": "",
            "heartbeat_at": "",
            "error": "",
            "finished_at": "",
        }
        pipe = self._conn.pipeline()
        pipe.hset(_meta_key(str(job_id)), mapping=cast(Any, meta))
        pipe.lrem(PROCESSING_KEY, 0, str(job_id))
        pipe.zrem(SCHEDULED_KEY, str(job_id))
        pipe.lpush(QUEUE_KEY, str(job_id))
        pipe.execute()
        return True

    def _record_exec_job(self, execution_id: str, job_id: str) -> None:
        self._conn.hset(f"{META_PREFIX}exec_to_job", execution_id, job_id)

    def _promote_due_scheduled(self) -> None:
        """Move scheduled (backoff-delayed) jobs whose retry time has
        passed back onto the FIFO queue."""
        now = time.time()
        due = self._conn.zrangebyscore(SCHEDULED_KEY, "-inf", now)
        if not due:
            return
        pipe = self._conn.pipeline()
        pipe.zrem(SCHEDULED_KEY, *due)  # type: ignore[arg-type]
        # Re-push oldest-scheduled first to keep FIFO ordering stable.
        for job_id in sorted(due):
            pipe.lpush(QUEUE_KEY, str(job_id))
        pipe.execute()

    def claim(self) -> QueueJob | None:
        self._promote_due_scheduled()
        moved = self._conn.lmove(QUEUE_KEY, PROCESSING_KEY, "RIGHT", "LEFT")
        if moved is None:
            return None
        job_id: str = str(moved)
        meta = cast(dict[str, str], self._conn.hgetall(_meta_key(job_id)))
        if not meta:
            # Enqueue crashed between LPUSH and HSET: rebuild a queued
            # meta and hand the job to this worker anyway.
            self._conn.hset(_meta_key(job_id), mapping=cast(Any, {"status": _QUEUED}))
            meta = cast(dict[str, str], self._conn.hgetall(_meta_key(job_id)))
        worker = get_worker_id()
        now = _now()
        attempts = int(meta.get("attempts", "0") or 0)
        self._conn.hset(
            _meta_key(job_id),
            mapping=cast(Any, {
                "status": _CLAIMED,
                "claimed_by": worker,
                "claimed_at": now,
                "heartbeat_at": now,
                "attempts": str(attempts + 1),
            }),
        )
        try:
            payload = json.loads(meta["payload"])
        except (KeyError, json.JSONDecodeError):
            logger.exception("queue: job %s has an unreadable payload", job_id)
            payload = {}
        return QueueJob(
            id=job_id,
            execution_id=meta.get("execution_id", ""),
            payload=payload,
            status=_CLAIMED,
            attempts=attempts + 1,
            claimed_by=worker,
            claimed_at=now,
        )

    def complete(self, job_id: str, status: str = _DONE, error: dict | None = None) -> None:
        from app.config import get_settings

        execution_id = str(self._conn.hget(_meta_key(job_id), "execution_id") or "")
        terminal = status in (_DONE, _FAILED)
        pipe = self._conn.pipeline()
        pipe.lrem(PROCESSING_KEY, 0, job_id)
        pipe.zrem(SCHEDULED_KEY, job_id)
        pipe.hset(
            _meta_key(job_id),
            mapping=cast(Any, {
                "status": status,
                "finished_at": _now(),
                "error": json.dumps(error) if error else "",
            }),
        )
        if terminal:
            # Terminal bookkeeping may be evicted once the TTL passes: the
            # executions table is the authoritative record (spec 25.3).
            ttl = max(int(get_settings().redis_job_meta_ttl_s), 1)
            pipe.expire(_meta_key(job_id), ttl)
            if execution_id:
                pipe.srem(EXECS_KEY, execution_id)
                pipe.hdel(f"{META_PREFIX}exec_to_job", execution_id)
        pipe.execute()

    def heartbeat(self, job_id: str) -> None:
        self._conn.hset(_meta_key(job_id), "heartbeat_at", _now())

    def recover_stale(self, stale_after_s: float) -> int:
        from app.config import get_settings
        from app.maintenance import mark_execution_failed
        from app.queue import retry_delay_s

        settings = get_settings()
        now = time.time()
        recovered = 0
        for raw in self._conn.lrange(PROCESSING_KEY, 0, -1):
            job_id = str(raw)
            meta = cast(dict[str, str], self._conn.hgetall(_meta_key(job_id)))
            heartbeat = meta.get("heartbeat_at", "")
            elapsed = now - float(heartbeat) if heartbeat else None
            if elapsed is not None and 0 <= elapsed <= stale_after_s:
                # Fresh claim (heartbeat older than the threshold is stale;
                # a heartbeat dated in the future is clock skew -> stale).
                continue
            attempts = int(meta.get("attempts", "0") or 0)
            execution_id = meta.get("execution_id", "")
            if attempts >= settings.queue_max_attempts:
                # Poison-job guard: terminal failure instead of endless
                # recycling; the authoritative execution row is failed too.
                error = {
                    "code": "MAX_ATTEMPTS_EXCEEDED",
                    "message": (
                        f"Job exceeded {settings.queue_max_attempts} claim "
                        "attempts without completing (worker crashes or stalled execution)."
                    ),
                }
                pipe = self._conn.pipeline()
                pipe.lrem(PROCESSING_KEY, 0, job_id)
                pipe.zrem(SCHEDULED_KEY, job_id)
                pipe.hset(
                    _meta_key(job_id),
                    mapping=cast(Any, {
                        "status": _FAILED,
                        "finished_at": _now(),
                        "error": json.dumps(error),
                    }),
                )
                ttl = max(int(settings.redis_job_meta_ttl_s), 1)
                pipe.expire(_meta_key(job_id), ttl)
                if execution_id:
                    pipe.srem(EXECS_KEY, execution_id)
                    pipe.hdel(f"{META_PREFIX}exec_to_job", execution_id)
                pipe.execute()
                if execution_id:
                    mark_execution_failed(execution_id, error)
                logger.warning(
                    "queue.redis: job %s terminally failed after %d attempts",
                    job_id, attempts,
                )
                continue
            delay_s = retry_delay_s(attempts)
            meta_update: dict[str, str] = {
                "status": _QUEUED,
                "claimed_by": "",
                "claimed_at": "",
            }
            pipe = self._conn.pipeline()
            ready = now + delay_s if delay_s > 0 else None
            if ready is not None:
                pipe.zadd(SCHEDULED_KEY, {job_id: ready})
                meta_update["next_retry_at"] = str(ready)
            else:
                pipe.lpush(QUEUE_KEY, job_id)
            pipe.lrem(PROCESSING_KEY, 0, job_id)
            pipe.hset(_meta_key(job_id), mapping=cast(Any, meta_update))
            pipe.execute()
            recovered += 1
        return recovered
