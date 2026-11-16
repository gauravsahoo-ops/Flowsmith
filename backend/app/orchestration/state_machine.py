"""Run state machine.

Pure functions so the same rules can be used by the coordinator, tests, and
future recovery tooling without importing SQLAlchemy or FastAPI.

The status values intentionally match the existing ``executions.status``
contract so the state machine can be introduced behind a feature flag without a
data migration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.platform.contracts import RunSnapshot, RunStatus


class InvalidTransition(ValueError):
    """Raised when a caller attempts an illegal run-state transition."""

    def __init__(self, current: RunStatus, target: RunStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid run transition: {current.value} -> {target.value}")


# A running run can pause for approval/auth, retry, finish, or start cancelling.
# A paused run can resume, fail, expire, or be cancelled. Terminal states are
# immutable.
ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.WAITING_AUTH,
            RunStatus.RETRYING,
            RunStatus.SUCCESS,
            RunStatus.FAILED,
            RunStatus.TIMEOUT,
            RunStatus.CANCELLING,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
        }
    ),
    RunStatus.WAITING_AUTH: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
        }
    ),
    RunStatus.RETRYING: frozenset(
        {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLING, RunStatus.CANCELLED}
    ),
    RunStatus.CANCELLING: frozenset({RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.SUCCESS: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.TIMEOUT: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: RunStatus, target: RunStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)


def transition(
    snapshot: RunSnapshot,
    target: RunStatus,
    *,
    expected_version: int | None = None,
) -> RunSnapshot:
    """Return the next snapshot or raise.

    ``expected_version`` gives callers optimistic-concurrency protection: a
    stale caller cannot overwrite a newer state.
    """
    if expected_version is not None and snapshot.version != expected_version:
        raise ValueError(
            f"Stale run snapshot: expected version {expected_version}, "
            f"current version {snapshot.version}"
        )
    assert_transition(snapshot.status, target)
    return replace(snapshot, status=target, version=snapshot.version + 1)


@dataclass(frozen=True)
class RunEvent:
    """Minimal event used by the state machine at the orchestration boundary."""

    event_type: str
    target: RunStatus


# Mapping for the events that may drive a run transition. Not every event maps
# to a status; unmapped events are ignored by the coordinator.
EVENT_TARGETS: dict[str, RunStatus] = {
    "run.claim": RunStatus.RUNNING,
    "run.pause.approval": RunStatus.WAITING_APPROVAL,
    "run.pause.auth": RunStatus.WAITING_AUTH,
    "run.retry": RunStatus.RETRYING,
    "run.resume": RunStatus.RUNNING,
    "run.cancel": RunStatus.CANCELLING,
    "run.cancel.confirmed": RunStatus.CANCELLED,
    "run.succeed": RunStatus.SUCCESS,
    "run.fail": RunStatus.FAILED,
    "run.timeout": RunStatus.TIMEOUT,
}
