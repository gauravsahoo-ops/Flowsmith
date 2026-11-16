"""RunCoordinator composition tests.

The coordinator is driven directly (not through the worker) with fake
control-plane callables, while the execution row stays in the real test
database. That pins the lifecycle contract: CAS, seed plans, pause/auth/
terminal routing, deliveries, error handlers, and cancellation cleanup.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.db import get_session
from app.engine.errors import NodeExecutionError, WorkflowValidationError
from app.engine.executor import ExecutionResult
from app.models import Execution, User, WebhookDelivery, WorkflowRecord
from app.orchestration import cancellation
from app.orchestration.run_coordinator import RunCoordinator
from app.queue import QueueJob

USER_ID = 901
WF_ID = "wf_coord"
DELIVERY_ID = "del_coord"


def _workflow(nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": WF_ID,
        "name": "Coordinator flow",
        "nodes": nodes
        or [{"id": "trigger", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
        "settings": {},
    }


def _seed_execution(
    execution_id: str,
    *,
    status: str = "queued",
    results: dict[str, Any] | None = None,
    workflow_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_data = workflow_data or _workflow()
    db = get_session()
    try:
        db.add(User(id=USER_ID, email=f"{execution_id}@example.com", password_hash="x"))
        db.add(
            WorkflowRecord(
                id=WF_ID,
                user_id=USER_ID,
                name="Coordinator flow",
                version=1,
                active=True,
                data=workflow_data,
            )
        )
        db.flush()
        db.add(
            Execution(
                id=execution_id,
                workflow_id=WF_ID,
                user_id=USER_ID,
                workflow_version=1,
                workflow_data=workflow_data,
                trigger="manual",
                trigger_data=[{}],
                status=status,
                results=results,
            )
        )
        db.add(
            WebhookDelivery(
                id=DELIVERY_ID,
                workflow_id=WF_ID,
                user_id=USER_ID,
                path="/hook",
                status="queued",
                execution_id=execution_id,
            )
        )
        db.commit()
    finally:
        db.close()
    return workflow_data


def _job(
    execution_id: str,
    *,
    workflow_data: dict[str, Any] | None = None,
    payload_extra: dict[str, Any] | None = None,
) -> QueueJob:
    workflow_data = workflow_data or _workflow()
    return QueueJob(
        id=f"job_{execution_id}",
        execution_id=execution_id,
        payload={
            "workflow_data": workflow_data,
            "trigger_items": [{"value": "in"}],
            "trigger": "manual",
            "user_id": USER_ID,
            "workflow_id": WF_ID,
            "version": 1,
            "workspace_id": None,
            **(payload_extra or {}),
        },
    )


def _row(execution_id: str) -> dict[str, Any]:
    db = get_session()
    try:
        rec = db.get(Execution, execution_id)
        assert rec is not None
        return {
            "status": rec.status,
            "error": rec.error,
            "finished_at": rec.finished_at,
            "pause_state": rec.pause_state,
            "node_statuses": rec.node_statuses,
            "results": rec.results,
            "trace": rec.trace,
        }
    finally:
        db.close()


def _delivery_status() -> str:
    db = get_session()
    try:
        row = db.get(WebhookDelivery, DELIVERY_ID)
        assert row is not None
        return row.status
    finally:
        db.close()


class _Fakes:
    """Injected control-plane callables with call capture."""

    def __init__(
        self,
        *,
        result: ExecutionResult | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self.result = result if result is not None else ExecutionResult()
        self.exc = exc
        self.calls: list[dict[str, Any]] = []
        self.env_calls: list[QueueJob] = []
        self.error_workflow_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.http_mocked: list[bool] = []

    async def execute(self, workflow: Any, trigger_items: Any, **kwargs: Any) -> ExecutionResult:
        self.calls.append(
            {
                "workflow": workflow,
                "trigger_items": trigger_items,
                **kwargs,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.result

    def resolve_env(self, db: Any, job: QueueJob) -> dict[str, str]:
        self.env_calls.append(job)
        return {"COORD_ENV": "on"}

    def start_error_workflow(
        self,
        db: Any,
        job: QueueJob,
        execution_id: str,
        error: dict[str, Any] | None,
    ) -> None:
        self.error_workflow_calls.append((execution_id, error))

    def http_client(self, *, mocked: bool = False) -> str:
        self.http_mocked.append(mocked)
        return "fake-http-client"


def _run(
    execution_id: str,
    fakes: _Fakes,
    *,
    payload_extra: dict[str, Any] | None = None,
    workflow_data: dict[str, Any] | None = None,
    evaluator: Any = None,
) -> tuple[str, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    db = get_session()
    try:
        coordinator = RunCoordinator(
            db,
            _job(
                execution_id,
                workflow_data=workflow_data,
                payload_extra=payload_extra,
            ),
            events.append,
            execute_workflow=fakes.execute,
            resolve_env_vars=fakes.resolve_env,
            start_error_workflow=fakes.start_error_workflow,
            http_client=fakes.http_client,
            test_run_evaluator=evaluator,
        )
        status = asyncio.run(coordinator.run())
    finally:
        db.close()
    return status, events


def _assert_no_registry_entry(execution_id: str) -> None:
    assert execution_id not in cancellation._ACTIVE_CANCEL_EVENTS


def test_fresh_run_persists_terminal_state_and_deliveries() -> None:
    execution_id = "exec_coord_fresh"
    _seed_execution(execution_id)
    fakes = _Fakes(
        result=ExecutionResult(
            status="success",
            results={"trigger": {"main": [{"value": "in"}]}},
            inputs={"trigger": [{"value": "in"}]},
            trace=[
                {
                    "node_id": "trigger",
                    "status": "success",
                    "started_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            events=[
                {
                    "node_id": "trigger",
                    "status": "success",
                    "execution_id": execution_id,
                }
            ],
        )
    )

    status, _events = _run(execution_id, fakes)

    assert status == "success"
    assert len(fakes.calls) == 1
    call = fakes.calls[0]
    assert call["execution_id"] == execution_id
    assert call["env_vars"] == {"COORD_ENV": "on"}
    assert call["http_client"] == "fake-http-client"
    assert fakes.http_mocked == [False]
    assert call["initial_results"] is None
    assert call["storage_seed"] is None
    assert isinstance(call["cancel_event"], asyncio.Event)
    assert call["cancel_event"].is_set() is False

    row = _row(execution_id)
    assert row["status"] == "success"
    assert row["finished_at"] is not None
    assert row["node_statuses"] == {"trigger": "success"}
    assert row["results"]["outputs"] == {"trigger": {"main": [{"value": "in"}]}}
    assert row["trace"] == [
        {
            "node_id": "trigger",
            "status": "success",
            "started_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    assert row["error"] is None
    assert row["pause_state"] is None
    assert _delivery_status() == "success"
    _assert_no_registry_entry(execution_id)


def test_approval_seed_replays_upstream_and_records_decision() -> None:
    execution_id = "exec_coord_approval"
    _seed_execution(
        execution_id,
        results={
            "outputs": {
                "trigger": {"main": [{"value": "in"}]},
                "gate": {"main": [{}]},
            }
        },
    )
    decision = {
        "node_id": "gate",
        "approved": True,
        "approved_by": USER_ID,
        "approved_at": "2026-01-01T00:00:00+00:00",
    }
    fakes = _Fakes(
        result=ExecutionResult(
            status="success",
            results={"gate": {"main": [{"approved": True}]}},
            events=[
                {
                    "node_id": "gate",
                    "status": "success",
                    "execution_id": execution_id,
                }
            ],
        )
    )

    status, _events = _run(
        execution_id,
        fakes,
        payload_extra={"_approval_data": decision},
    )

    assert status == "success"
    call = fakes.calls[0]
    assert call["initial_results"] == {"trigger": {"main": [{"value": "in"}]}}
    assert call["storage_seed"] == {"_approval_data": decision}

    row = _row(execution_id)
    assert row["status"] == "success"
    assert row["results"]["approval"] == decision
    assert row["results"]["outputs"] == {"gate": {"main": [{"approved": True}]}}
    _assert_no_registry_entry(execution_id)


def test_worker_cancellation_records_terminal_row_and_reraises() -> None:
    execution_id = "exec_coord_worker_cancel"
    _seed_execution(execution_id)
    fakes = _Fakes(exc=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        _run(execution_id, fakes)

    row = _row(execution_id)
    assert row["status"] == "cancelled"
    assert row["finished_at"] is not None
    assert row["error"] == {
        "code": "WORKER_STOPPED",
        "message": "Worker stopped mid-execution.",
    }
    assert _delivery_status() == "cancelled"
    _assert_no_registry_entry(execution_id)


def test_validation_error_is_not_a_crash() -> None:
    execution_id = "exec_coord_validation"
    _seed_execution(execution_id)
    validation = WorkflowValidationError(
        [
            {
                "code": "INVALID_NODE",
                "node_id": "trigger",
                "field": "type",
                "message": "Unknown node type.",
            }
        ]
    )
    fakes = _Fakes(exc=validation)

    status, _events = _run(execution_id, fakes)

    assert status == "failed"
    row = _row(execution_id)
    assert row["status"] == "failed"
    assert row["finished_at"] is not None
    assert row["error"] == validation.to_dict()
    assert _delivery_status() == "failed"
    assert fakes.error_workflow_calls == []
    _assert_no_registry_entry(execution_id)


def test_crash_records_failure_and_starts_error_workflow() -> None:
    execution_id = "exec_coord_crash"
    _seed_execution(execution_id)
    fakes = _Fakes(exc=RuntimeError("kaboom"))

    status, _events = _run(execution_id, fakes)

    assert status == "failed"
    row = _row(execution_id)
    assert row["status"] == "failed"
    assert row["error"] == {"code": "EXECUTION_CRASHED", "message": "kaboom"}
    assert _delivery_status() == "failed"
    assert fakes.error_workflow_calls == [
        (execution_id, {"code": "EXECUTION_CRASHED", "message": "kaboom"})
    ]
    _assert_no_registry_entry(execution_id)


def test_pause_routes_to_waiting_approval() -> None:
    execution_id = "exec_coord_pause"
    _seed_execution(execution_id)
    pause_state = {"type": "human_approval", "message": "Ship it?"}
    fakes = _Fakes(
        result=ExecutionResult(
            status="success",
            paused=True,
            paused_node_id="gate",
            pause_info={"pause_state": pause_state},
            events=[
                {
                    "node_id": "gate",
                    "status": "waiting_approval",
                    "execution_id": execution_id,
                }
            ],
        )
    )

    status, _events = _run(execution_id, fakes)

    assert status == "waiting_approval"
    row = _row(execution_id)
    assert row["status"] == "waiting_approval"
    assert row["finished_at"] is None
    assert row["pause_state"] == pause_state
    assert row["node_statuses"] == {"gate": "waiting_approval"}
    assert row["error"] is None
    assert _delivery_status() == "waiting_approval"
    _assert_no_registry_entry(execution_id)


def test_auth_failure_routes_to_waiting_auth() -> None:
    execution_id = "exec_coord_auth"
    workflow_data = _workflow(
        nodes=[
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "gate",
                "type": "http_request",
                "name": "Billing API",
                "parameters": {},
                "credentials": {"api_key": "cred_auth"},
            },
        ]
    )
    _seed_execution(execution_id, workflow_data=workflow_data)
    fakes = _Fakes(
        result=ExecutionResult(
            status="failed",
            error=NodeExecutionError(
                "Token expired", code="AUTH_FAILED", node_id="gate"
            ),
            events=[
                {
                    "node_id": "gate",
                    "status": "error",
                    "execution_id": execution_id,
                }
            ],
        )
    )

    status, events = _run(execution_id, fakes, workflow_data=workflow_data)

    assert status == "waiting_auth"
    row = _row(execution_id)
    assert row["status"] == "waiting_auth"
    assert row["pause_state"]["type"] == "auth_required"
    assert row["pause_state"]["credential_id"] == "cred_auth"
    assert row["pause_state"]["node_id"] == "gate"
    assert row["node_statuses"] == {"gate": "waiting_auth"}
    assert any(
        event.get("event") == "execution.waiting_auth"
        and event.get("credential_id") == "cred_auth"
        for event in events
    )
    assert _delivery_status() == "waiting_auth"
    _assert_no_registry_entry(execution_id)


def test_terminal_failure_uses_terminal_plan() -> None:
    execution_id = "exec_coord_terminal"
    _seed_execution(execution_id)
    failure = NodeExecutionError("boom", code="NODE_EXECUTION_ERROR", node_id="work")
    fakes = _Fakes(
        result=ExecutionResult(
            status="failed",
            error=failure,
            trace=[
                {
                    "node_id": "work",
                    "status": "error",
                    "started_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            events=[
                {
                    "node_id": "work",
                    "status": "error",
                    "execution_id": execution_id,
                }
            ],
        )
    )

    status, _events = _run(execution_id, fakes)

    assert status == "failed"
    row = _row(execution_id)
    assert row["status"] == "failed"
    assert row["finished_at"] is not None
    assert row["error"] == failure.to_dict()
    assert row["node_statuses"] == {"work": "error"}
    assert row["trace"] == [
        {
            "node_id": "work",
            "status": "error",
            "started_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    assert row["pause_state"] is None
    assert _delivery_status() == "failed"
    assert fakes.error_workflow_calls == [(execution_id, failure.to_dict())]
    _assert_no_registry_entry(execution_id)


def test_test_run_uses_injected_evaluator() -> None:
    execution_id = "exec_coord_test_run"
    _seed_execution(execution_id)
    seen: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def evaluator(spec: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        seen.append((spec, payload))
        return {"verdict": "PASS", "checks": []}

    fakes = _Fakes(
        result=ExecutionResult(
            status="success",
            results={"trigger": {"main": [{"value": "in"}]}},
            events=[
                {
                    "node_id": "trigger",
                    "status": "success",
                    "execution_id": execution_id,
                }
            ],
        )
    )

    status, _events = _run(
        execution_id,
        fakes,
        payload_extra={"_test_run": {"mocks": [], "assertions": []}},
        evaluator=evaluator,
    )

    assert status == "success"
    assert len(seen) == 1
    spec, payload = seen[0]
    assert spec == {"mocks": [], "assertions": []}
    assert payload["status"] == "success"
    assert payload["results"] == {"outputs": {"trigger": {"main": [{"value": "in"}]}}}
    row = _row(execution_id)
    assert row["results"]["tests"] == {
        "verdict": "PASS",
        "checks": [],
        "workflow_id": WF_ID,
        "test_mode": True,
    }
    _assert_no_registry_entry(execution_id)


def test_cancelled_before_start_publishes_event_and_is_not_registered() -> None:
    execution_id = "exec_coord_pre_cancelled"
    _seed_execution(execution_id, status="cancelling")
    fakes = _Fakes()

    status, events = _run(execution_id, fakes)

    assert status == "cancelled"
    assert fakes.calls == []
    row = _row(execution_id)
    assert row["status"] == "cancelled"
    assert row["finished_at"] is not None
    assert events == [
        {
            "event": "execution.cancelled",
            "execution_id": execution_id,
            "workflow_id": WF_ID,
            "node_id": None,
            "status": "cancelled",
        }
    ]
    _assert_no_registry_entry(execution_id)
