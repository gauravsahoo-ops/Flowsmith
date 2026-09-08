"""Job queue abstraction (Phase 15, spec 13/34/58).

A queue delivers one job (execution) to exactly one worker. The worker
is stateless: it claims a job, loads everything it needs (workflow
snapshot, credentials) from the database, executes, and persists the
outcome — any worker can run any job, so workers scale horizontally
(spec 58). Jobs left claimed by a crashed worker are recovered via the
heartbeat/stale mechanism (spec 34.1).

Backends behind the same interface:

- ``db_queue.DbJobQueue``  — default. Jobs live in the ``jobs`` table;
  zero extra infrastructure, works with SQLite and PostgreSQL.
- ``redis_queue.RedisJobQueue`` — Redis list + hashes. Requires
  ``REDIS_URL``. Use when a shared queue is needed across many
  processes or instances.

Select the backend with ``QUEUE_BACKEND=db|redis`` (default ``db``).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.config import get_settings


@dataclass
class QueueJob:
    """One queued execution as seen by a worker."""

    id: str
    execution_id: str
    payload: dict[str, Any]
    status: str = "queued"
    attempts: int = 0
    claimed_by: str | None = None
    claimed_at: str | None = None

    @property
    def workflow_data(self) -> dict:
        return self.payload["workflow_data"]

    @property
    def trigger_items(self) -> list[dict[str, Any]]:
        return self.payload["trigger_items"]

    @property
    def trigger(self) -> str:
        return self.payload["trigger"]

    @property
    def user_id(self) -> int:
        return self.payload["user_id"]

    @property
    def workflow_id(self) -> str:
        return self.payload["workflow_id"]

    @property
    def version(self) -> int:
        return self.payload["version"]

    @property
    def workspace_id(self) -> str | None:
        """Workspace the workflow belongs to (absent in pre-P31 jobs)."""
        value = self.payload.get("workspace_id")
        return str(value) if value else None


class QueueBackend(ABC):
    """Minimal contract both backends implement.

    Claim must be atomic: two concurrent workers must never receive the
    same job. ``complete``/``fail`` are idempotent-ish (the first writer
    wins; a lost race is harmless because the execution row is the
    source of truth).
    """

    name: str = ""

    @abstractmethod
    def enqueue(self, job_id: str, execution_id: str, payload: dict[str, Any]) -> bool:
        """Queue a job. Returns False when an execution is already queued
        (idempotency guard for retried webhook/scheduler deliveries)."""

    def requeue(self, execution_id: str, payload: dict[str, Any]) -> bool:
        """Reset a finished job for the same execution back to queued with
        new payload (durable pause/resume, Phase 32). Returns False when
        no job row exists for the execution (callers fall back to
        enqueue). Backends may override; default delegates to enqueue."""
        return False

    @abstractmethod
    def claim(self) -> QueueJob | None:
        """Atomically take the oldest queued job, or None when empty."""

    @abstractmethod
    def complete(self, job_id: str, status: str = "done", error: dict | None = None) -> None:
        """Mark the job done/failed (terminal)."""

    @abstractmethod
    def heartbeat(self, job_id: str) -> None:
        """Refresh the claim so the stale-sweep does not re-queue it."""

    @abstractmethod
    def recover_stale(self, stale_after_s: float) -> int:
        """Re-queue claimed jobs whose heartbeat is older than
        ``stale_after_s`` (crashed workers). Jobs already claimed
        ``queue_max_attempts`` times are NOT re-queued again — they are
        terminally failed (job + execution row) so a poison payload cannot
        loop forever. Returns the number of jobs recovered."""


def retry_delay_s(attempts: int) -> float:
    """Exponential retry backoff for a job being requeued after its Nth
    claim failed to complete: attempt 2 waits ``base`` seconds, each
    later attempt doubles, capped. Attempt 1 (the first run) is immediate
    when triggered outside recovery.

    Shared formula for BOTH backends so behaviour/tests stay aligned."""
    settings = get_settings()
    if attempts <= 1:
        return 0.0
    return min(
        settings.queue_retry_backoff_base_s * (2 ** max(attempts - 2, 0)),
        settings.queue_retry_backoff_max_s,
    )


_QUEUES: dict[str, type[QueueBackend]] = {}
_lock = threading.Lock()
_instance: QueueBackend | None = None


_QueueT = TypeVar("_QueueT", bound=type[QueueBackend])


def register_queue(cls: _QueueT) -> _QueueT:
    if not cls.name:
        raise ValueError(f"Queue backend {cls.__name__} has no name.")
    _QUEUES[cls.name] = cls
    return cls


def queue_names() -> list[str]:
    return sorted(_QUEUES)


def get_queue() -> QueueBackend:
    """Return the configured backend singleton (spec 34: workers must not
    assume another worker's in-memory state — the queue is shared)."""
    global _instance
    with _lock:
        if _instance is None:
            settings = get_settings()
            cls = _QUEUES.get(settings.queue_backend)
            if cls is None:
                raise ValueError(
                    f"Unknown queue backend '{settings.queue_backend}' "
                    f"(available: {', '.join(queue_names())})"
                )
            _instance = cls()
        return _instance


def reset_queue() -> None:
    """Test helper: forget the singleton so a different backend can load."""
    global _instance
    with _lock:
        _instance = None


# Importing the modules registers the backends (no heavy imports: the
# redis backend imports redis lazily inside its constructor).
from app.queue import db_queue, redis_queue  # noqa: E402,F401
