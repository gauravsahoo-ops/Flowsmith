"""Run coordinator: the single authority for run lifecycle transitions.

This module is intentionally free of SQLAlchemy and FastAPI. A Postgres-backed
``RunStore`` and the existing queue adapters will be wired in later; the
in-memory adapters here make the contract executable today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.platform.contracts import (
    Checkpoint,
    EventBus,
    JobQueue,
    RunSnapshot,
    RunStatus,
    RunStore,
    TERMINAL_STATUSES,
)
from app.platform.events import (
    RUN_COMPLETED,
    RUN_PAUSED,
    RUN_QUEUED,
    RUN_RESUMED,
    RUN_STARTED,
    new_event,
)
from app.orchestration.state_machine import transition


class RunNotFound(KeyError):
    pass


@dataclass(frozen=True)
class StartRun:
    run_id: str
    workflow_id: str
    tenant_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None
    priority: str = "interactive"
    correlation_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.workflow_id.strip() or not self.tenant_id.strip():
            raise ValueError("run_id, workflow_id, and tenant_id are required")


class InMemoryRunStore:
    """Reference RunStore implementation for tests and local development."""

    def __init__(self) -> None:
        self._runs: dict[str, RunSnapshot] = {}
        self._checkpoints: dict[str, list[Checkpoint]] = {}

    def create(self, snapshot: RunSnapshot) -> RunSnapshot:
        if snapshot.run_id in self._runs:
            return self._runs[snapshot.run_id]
        self._runs[snapshot.run_id] = snapshot
        self._checkpoints.setdefault(snapshot.run_id, [])
        return snapshot

    def load(self, run_id: str) -> RunSnapshot:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFound(run_id) from exc

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._runs[checkpoint.run_id]  # raises RunNotFound
        self._checkpoints.setdefault(checkpoint.run_id, []).append(checkpoint)

    def transition(
        self,
        run_id: str,
        target: RunStatus,
        expected_version: int,
    ) -> RunSnapshot:
        current = self.load(run_id)
        updated = transition(current, target, expected_version=expected_version)
        self._runs[run_id] = updated
        return updated

    def checkpoints(self, run_id: str) -> tuple[Checkpoint, ...]:
        return tuple(self._checkpoints.get(run_id, ()))


class InMemoryJobQueue:
    """Small JobQueue adapter used by coordinator tests."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._claimed: set[str] = set()
        self._done: dict[str, str] = {}

    async def enqueue(self, job: Mapping[str, Any]) -> str:
        job_id = str(job["job_id"])
        if job_id not in self._jobs:
            self._jobs[job_id] = dict(job)
        return job_id

    async def claim(self, worker_id: str) -> Mapping[str, Any] | None:
        for job_id, job in self._jobs.items():
            if job_id in self._claimed or job_id in self._done:
                continue
            self._claimed.add(job_id)
            claimed = dict(job)
            claimed["worker_id"] = worker_id
            return claimed
        return None

    async def heartbeat(self, job_id: str, worker_id: str) -> None:
        if job_id not in self._claimed:
            raise KeyError(f"Job not claimed: {job_id}")
        self._jobs[job_id]["worker_id"] = worker_id

    async def complete(self, job_id: str, status: str) -> None:
        if job_id not in self._jobs:
            raise KeyError(f"Unknown job: {job_id}")
        self._done[job_id] = status

    def status(self, job_id: str) -> str | None:
        return self._done.get(job_id)

    def is_claimed(self, job_id: str) -> bool:
        return job_id in self._claimed


class RunCoordinator:
    """Coordinates run state, queue admission, checkpoints, and events."""

    def __init__(
        self,
        store: RunStore,
        queue: JobQueue,
        events: EventBus | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.events = events

    async def _publish(self, event: Any) -> None:
        if self.events is not None:
            await self.events.publish(event)

    @staticmethod
    def _tenant(snapshot: RunSnapshot) -> str:
        return snapshot.tenant_id or "unknown"

    async def start(self, command: StartRun) -> RunSnapshot:
        try:
            existing = self.store.load(command.run_id)
        except RunNotFound:
            existing = None
        if existing is not None:
            # Idempotent start: the same command/run id must not enqueue twice.
            return existing

        snapshot = self.store.create(
            RunSnapshot(
                run_id=command.run_id,
                status=RunStatus.QUEUED,
                tenant_id=command.tenant_id,
                workspace_id=command.workspace_id,
            )
        )
        await self.queue.enqueue(
            {
                "job_id": command.run_id,
                "run_id": command.run_id,
                "workflow_id": command.workflow_id,
                "tenant_id": command.tenant_id,
                "workspace_id": command.workspace_id,
                "priority": command.priority,
                "payload": dict(command.payload),
                "idempotency_key": command.idempotency_key,
            }
        )
        await self._publish(
            new_event(
                RUN_QUEUED,
                tenant_id=command.tenant_id,
                correlation_id=command.correlation_id,
                workspace_id=command.workspace_id,
                run_id=command.run_id,
                idempotency_key=command.idempotency_key,
                payload={"workflow_id": command.workflow_id},
            )
        )
        return snapshot

    def _transition(self, run_id: str, target: RunStatus) -> RunSnapshot:
        current = self.store.load(run_id)
        return self.store.transition(run_id, target, expected_version=current.version)

    async def claim(self, run_id: str, worker_id: str) -> RunSnapshot:
        snapshot = self._transition(run_id, RunStatus.RUNNING)
        await self._publish(
            new_event(
                RUN_STARTED,
                tenant_id=self._tenant(snapshot),
                workspace_id=snapshot.workspace_id,
                run_id=run_id,
                payload={"worker_id": worker_id},
            )
        )
        return snapshot

    async def pause(self, run_id: str, reason: str) -> RunSnapshot:
        snapshot = self._transition(run_id, RunStatus.WAITING_APPROVAL)
        await self._publish(
            new_event(
                RUN_PAUSED,
                tenant_id=self._tenant(snapshot),
                workspace_id=snapshot.workspace_id,
                run_id=run_id,
                payload={"reason": reason},
            )
        )
        return snapshot

    async def resume(self, run_id: str) -> RunSnapshot:
        snapshot = self._transition(run_id, RunStatus.RUNNING)
        await self._publish(
            new_event(RUN_RESUMED, tenant_id=self._tenant(snapshot), workspace_id=snapshot.workspace_id, run_id=run_id)
        )
        return snapshot

    async def request_cancel(self, run_id: str) -> RunSnapshot:
        return self._transition(run_id, RunStatus.CANCELLING)

    async def confirm_cancel(self, run_id: str) -> RunSnapshot:
        snapshot = self._transition(run_id, RunStatus.CANCELLED)
        await self._publish(
            new_event(
                RUN_COMPLETED,
                tenant_id=self._tenant(snapshot),
                workspace_id=snapshot.workspace_id,
                run_id=run_id,
                payload={"status": RunStatus.CANCELLED.value},
            )
        )
        return snapshot

    async def finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: Mapping[str, Any] | None = None,
    ) -> RunSnapshot:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"finish() requires a terminal status, got {status.value}")
        snapshot = self._transition(run_id, status)
        await self._publish(
            new_event(
                RUN_COMPLETED,
                tenant_id=self._tenant(snapshot),
                workspace_id=snapshot.workspace_id,
                run_id=run_id,
                payload={
                    "status": status.value,
                    "error": dict(error) if error else None,
                },
            )
        )
        return snapshot

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        self.store.save_checkpoint(checkpoint)
