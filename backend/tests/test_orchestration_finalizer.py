"""Golden tests for the pure pause/auth/terminal finalizer decisions.

These tests pin the exact persisted shapes the execution runtime writes.
The module under test is pure: no database, FastAPI, or ``app.api`` imports.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.engine.errors import NodeExecutionError
from app.engine.executor import ExecutionResult
from app.orchestration.finalizer import (
    AUTH_ERROR_CODES,
    CANCELLED_ERROR,
    AuthFailure,
    PausePlan,
    build_auth_pause_plan,
    build_pause_plan,
    build_terminal_plan,
    classify_auth_failure,
    is_pause,
    mark_deliveries,
    node_statuses,
    terminal_status,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _result(**kwargs: Any) -> ExecutionResult:
    return ExecutionResult(**kwargs)


def _event(node_id: str | None, status: str = "success") -> dict[str, Any]:
    return {"node_id": node_id, "status": status}


def _step(
    node_id: str,
    started_at: str,
    status: str = "success",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "started_at": started_at,
        "status": status,
        **extra,
    }


# ---------------------------------------------------------------------------
# Status decision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result_status", "rec_status", "cancel_requested", "expected"),
    [
        ("timeout", "running", False, "timeout"),
        # Timeout wins even a durable cancel or an in-process request.
        ("timeout", "cancelled", True, "timeout"),
        ("cancelled", "running", False, "cancelled"),
        ("success", "cancelling", False, "cancelled"),
        ("failed", "cancelled", False, "cancelled"),
        ("failed", "running", True, "cancelled"),
        ("failed", "running", False, "failed"),
        ("success", "running", False, "success"),
    ],
)
def test_terminal_status_matrix(
    result_status: str,
    rec_status: str,
    cancel_requested: bool,
    expected: str,
) -> None:
    result = _result(status=result_status)

    assert terminal_status(
        result,
        rec_status=rec_status,
        cancel_requested=cancel_requested,
    ) == expected


def test_terminal_plan_uses_same_status_decision() -> None:
    result = _result(status="success")
    plan = build_terminal_plan(
        result,
        decision=None,
        mode="fresh",
        rec_status="cancelling",
        cancel_requested=False,
        existing_node_statuses=None,
        source_results=None,
        prior_inputs=None,
        upstream=None,
        doomed=None,
    )

    assert plan.status == "cancelled"


# ---------------------------------------------------------------------------
# Pause snapshot
# ---------------------------------------------------------------------------


def test_pause_plan_snapshot_is_exact() -> None:
    result = _result(
        status="success",
        paused=True,
        paused_node_id="gate",
        pause_info={"pause_state": {"type": "human_approval", "message": "Ship it?"}},
        trace=[_step("a", "2026-01-01T00:00:00Z"), _step("gate", "2026-01-01T00:01:00Z")],
        results={"a": {"main": [{"value": 1}]}},
        inputs={"trigger": [{"value": 0}]},
        events=[
            _event("a", "success"),
            # The paused node's event must not win over the forced status.
            _event("gate", "success"),
        ],
    )

    plan = build_pause_plan(
        result,
        {"a": "waiting_approval", "old": "failed"},
    )

    assert isinstance(plan, PausePlan)
    assert plan.status == "waiting_approval"
    assert plan.node_statuses == {
        "a": "waiting_approval",  # existing pause status preserved
        "old": "failed",  # untouched existing status preserved
        "gate": "waiting_approval",  # forced by paused_node_id
    }
    assert plan.trace is result.trace
    assert plan.results == {
        "outputs": result.results,
        "inputs": result.inputs,
    }
    assert plan.results["outputs"] is not result.results
    assert plan.results["inputs"] is not result.inputs
    assert plan.pause_state == {"type": "human_approval", "message": "Ship it?"}
    # A pause is never terminal: no finished_at field exists on the plan.
    assert "finished_at" not in {field.name for field in fields(PausePlan)}


def test_pause_plan_pause_state_falls_back_to_pause_info() -> None:
    result = _result(
        paused=True,
        paused_node_id="gate",
        pause_info={"type": "agent_tool_approval", "tool": "refund"},
        events=[_event("gate")],
    )

    plan = build_pause_plan(result, None)

    assert plan.pause_state is result.pause_info
    assert plan.node_statuses == {"gate": "waiting_approval"}


def test_pause_plan_without_pause_info_has_no_pause_state() -> None:
    result = _result(paused=True, paused_node_id="gate", events=[_event("gate")])

    plan = build_pause_plan(result, None)

    assert plan.pause_state is None
    assert plan.node_statuses == {"gate": "waiting_approval"}


@pytest.mark.parametrize(
    ("rec_status", "paused", "expected"),
    [
        ("waiting_approval", False, True),
        ("running", True, True),
        ("running", False, False),
        ("failed", False, False),
    ],
)
def test_is_pause(rec_status: str, paused: bool, expected: bool) -> None:
    assert is_pause(rec_status, _result(paused=paused)) is expected


# ---------------------------------------------------------------------------
# Auth classification
# ---------------------------------------------------------------------------


def _auth_workflow() -> dict[str, Any]:
    return {
        "id": "wf_auth",
        "nodes": [
            {
                "id": "conn",
                "name": "Stripe",
                "type": "http_request",
                "credentials": {"bearer": "cred_1"},
            }
        ],
        "connections": [],
    }


@pytest.mark.parametrize("code", sorted(AUTH_ERROR_CODES))
def test_classify_auth_failure_by_error_code(code: str) -> None:
    result = _result(
        status="failed",
        error=NodeExecutionError("provider rejected the call", code=code, node_id="conn"),
    )

    failure = classify_auth_failure(result, _auth_workflow())

    assert failure == AuthFailure(
        node_id="conn",
        credential_id="cred_1",
        credential_name="Stripe",
    )


@pytest.mark.parametrize(
    "message",
    [
        "Token expired for the provider",
        "authentication failed",
        "UNAUTHORIZED",
        "invalid_grant returned",
        "Credentials Required",
    ],
)
def test_classify_auth_failure_by_message_hint(message: str) -> None:
    result = _result(
        status="failed",
        error=NodeExecutionError(message, code="PROVIDER_ERROR", node_id="conn"),
    )

    failure = classify_auth_failure(result, _auth_workflow())

    assert failure is not None
    assert failure.credential_id == "cred_1"


def test_classify_auth_failure_falls_back_to_last_error_trace_step() -> None:
    result = _result(
        status="failed",
        error=NodeExecutionError("token expired", code="AUTH_FAILED"),
        trace=[
            _step("first", "2026-01-01T00:00:00Z"),
            _step("conn", "2026-01-01T00:01:00Z", status="error"),
        ],
    )

    failure = classify_auth_failure(result, _auth_workflow())

    assert failure is not None
    assert failure.node_id == "conn"
    assert failure.credential_id == "cred_1"


def test_classify_auth_failure_credential_name_fallback() -> None:
    # The failed node is unknown: no credential id, generic connection name.
    result = _result(
        status="failed",
        error=NodeExecutionError("unauthorized", code="AUTH_FAILED", node_id="unknown"),
    )

    failure = classify_auth_failure(result, _auth_workflow())

    assert failure == AuthFailure(
        node_id="unknown",
        credential_id=None,
        credential_name="Integration",
    )


def test_classify_auth_failure_node_name_falls_back_to_node_id() -> None:
    result = _result(
        status="failed",
        error=NodeExecutionError("unauthorized", code="AUTH_FAILED", node_id="conn"),
    )
    workflow = {
        "nodes": [{"id": "conn", "credentials": {"bearer": "cred_1"}}],
    }

    failure = classify_auth_failure(result, workflow)

    assert failure is not None
    assert failure.credential_name == "conn"


def test_classify_auth_failure_ignores_non_auth_and_non_failed_runs() -> None:
    auth_error = NodeExecutionError("boom", code="AUTH_FAILED", node_id="conn")
    assert classify_auth_failure(
        _result(status="failed", error=NodeExecutionError("boom", code="PROVIDER_ERROR", node_id="conn")),
        _auth_workflow(),
    ) is None
    assert classify_auth_failure(
        _result(status="success", error=auth_error),
        _auth_workflow(),
    ) is None
    assert classify_auth_failure(_result(status="failed"), _auth_workflow()) is None


# ---------------------------------------------------------------------------
# Auth pause snapshot
# ---------------------------------------------------------------------------


def test_auth_pause_plan_result_shape_and_exact_pause_state() -> None:
    result = _result(
        status="failed",
        trace=[_step("conn", "2026-01-01T00:00:00Z", status="error")],
        results={"conn": {"main": [{"error": "expired"}]}},
        inputs={"trigger": [{"value": 0}]},
        events=[_event("conn", "error"), _event("other", "success")],
        error=NodeExecutionError("token expired", code="AUTH_FAILED", node_id="conn"),
    )
    failure = AuthFailure(
        node_id="conn",
        credential_id="cred_1",
        credential_name="Stripe",
    )

    plan = build_auth_pause_plan(
        result,
        failure,
        {"conn": "running", "other": "success"},
        now=NOW,
    )

    assert plan.status == "waiting_auth"
    assert plan.node_statuses == {"conn": "waiting_auth", "other": "success"}
    assert plan.trace is result.trace
    # Auth pauses persist outputs only; inputs would leak the failed payload.
    assert plan.results == {"outputs": result.results}
    assert set(plan.results) == {"outputs"}
    assert plan.pause_state == {
        "type": "auth_required",
        "credential_id": "cred_1",
        "node_id": "conn",
        "node_name": "Stripe",
        "message": (
            "Execution paused: authentication required for connection "
            "'Stripe'. Reconnect integration to resume."
        ),
        "paused_at": NOW.isoformat(),
    }
    assert plan.credential_id == "cred_1"
    assert plan.node_id == "conn"
    assert plan.node_name == "Stripe"


# ---------------------------------------------------------------------------
# Terminal snapshot
# ---------------------------------------------------------------------------


def test_terminal_results_include_approval_block_and_test_report() -> None:
    report = {"passed": True, "diff": []}
    result = _result(
        status="failed",
        results={"after": {"main": [{"done": True}]}},
        inputs={"gate": [{"decision": "approved"}]},
        error=NodeExecutionError("after failed", code="NODE_ERROR", node_id="after"),
        test_report=report,
    )
    decision = {
        "node_id": "gate",
        "approved": True,
        "approved_by": "alice",
        "approved_at": "2026-01-01T00:00:00Z",
        "extra": "ignored",
    }

    plan = build_terminal_plan(
        result,
        decision=decision,
        mode="approval",
        rec_status="running",
        cancel_requested=False,
        existing_node_statuses={"gate": "success"},
        source_results=None,
        prior_inputs=None,
        upstream=None,
        doomed=None,
    )

    assert plan.status == "failed"
    assert plan.results["outputs"] == result.results
    assert plan.results["inputs"] == result.inputs
    assert plan.results["approval"] == {
        "node_id": "gate",
        "approved": True,
        "approved_by": "alice",
        "approved_at": "2026-01-01T00:00:00Z",
    }
    assert plan.results["tests"] is report
    assert plan.error == result.error.to_dict()


def test_terminal_run_node_merge() -> None:
    new_b = _step("b", "2026-01-01T12:00:00Z", new=True)
    new_c = _step("c", "2026-01-04T00:00:00Z", new=True)
    result = _result(
        status="success",
        results={
            "a": {"main": [999]},  # seeded upstream entry, no prior output
            "b": {"main": [20]},
            "c": {"main": [30]},
        },
        inputs={
            "a": [{"seed": 1}],
            "b": [{"value": 20}],
            "c": [{"value": 30}],
        },
        trace=[new_b, new_c],
        events=[_event("b"), _event("c")],
    )

    plan = build_terminal_plan(
        result,
        decision=None,
        mode="run_node",
        rec_status="running",
        cancel_requested=False,
        existing_node_statuses={
            "a": "success",
            "b": "failed",
            "downstream": "success",
        },
        source_results={
            "outputs": {
                "b": {"main": [2]},
                "downstream": {"main": [9]},
            },
            "inputs": {"b": [{"value": 2}]},
            "trace": [
                _step("a", "2026-01-01T00:00:00Z", old=True),
                _step("b", "2026-01-01T00:30:00Z", old=True),
                _step("downstream", "2026-01-02T00:00:00Z", old=True),
            ],
        },
        prior_inputs={"b": [{"value": 2}]},
        upstream={"a", "b"},
        doomed=set(),
    )

    # Prior outputs/inputs merged, target overwrites, seed-only upstream
    # entries without a prior value are deleted.
    assert plan.results["outputs"] == {
        "b": {"main": [20]},
        "downstream": {"main": [9]},
        "c": {"main": [30]},
    }
    assert plan.results["inputs"] == {
        "b": [{"value": 20}],
        "c": [{"value": 30}],
    }
    # Only upstream prior trace steps survive; downstream is dropped.
    assert plan.trace == [
        _step("a", "2026-01-01T00:00:00Z", old=True),
        new_b,
        new_c,
    ]
    # Duplicate node ids prefer the new step.
    assert [step for step in plan.trace if step["node_id"] == "b"] == [new_b]
    # Prior statuses only for upstream nodes, new events win.
    assert plan.node_statuses == {"a": "success", "b": "success", "c": "success"}
    assert plan.error is None


def test_terminal_retry_merge_keeps_prior_statuses_outside_doomed() -> None:
    new_trace = [_step("b", "2026-01-02T00:00:00Z", new=True)]
    result = _result(
        status="success",
        results={"b": {"main": [20]}, "c": {"main": [30]}},
        inputs={"b": [{"value": 20}], "c": [{"value": 30}]},
        trace=new_trace,
        events=[_event("b")],
    )

    plan = build_terminal_plan(
        result,
        decision=None,
        mode="node_retry",
        rec_status="running",
        cancel_requested=False,
        existing_node_statuses={"a": "success", "b": "failed", "c": "failed"},
        source_results={
            "outputs": {"a": {"main": [1]}, "b": {"main": [2]}, "c": {"main": [3]}},
            "inputs": {"a": [{"value": 1}], "b": [{"value": 2}]},
            "trace": [_step("a", "2026-01-01T00:00:00Z", old=True)],
        },
        prior_inputs={},
        upstream={"a", "b", "c"},
        doomed={"c"},
    )

    assert plan.results["outputs"] == {
        "a": {"main": [1]},
        "b": {"main": [20]},
        "c": {"main": [30]},
    }
    assert plan.results["inputs"] == {
        "a": [{"value": 1}],
        "b": [{"value": 20}],
        "c": [{"value": 30}],
    }
    # Retry traces only contain the steps that ran again.
    assert plan.trace is new_trace
    # Non-doomed prior statuses survive; doomed nodes are not inherited.
    assert plan.node_statuses == {"a": "success", "b": "success"}


def test_terminal_plan_without_source_uses_new_trace_and_statuses() -> None:
    result = _result(
        status="success",
        trace=[_step("a", "2026-01-01T00:00:00Z")],
        events=[_event("a")],
    )

    plan = build_terminal_plan(
        result,
        decision=None,
        mode="fresh",
        rec_status="running",
        cancel_requested=False,
        existing_node_statuses={"stale": "failed"},
        source_results=None,
        prior_inputs=None,
        upstream=None,
        doomed=None,
    )

    assert plan.trace is result.trace
    assert plan.node_statuses == {"a": "success"}
    assert plan.results == {"outputs": {}, "inputs": {}}
    assert plan.error is None


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def test_node_statuses_skips_empty_ids_and_defaults_to_success() -> None:
    events = [
        {"node_id": "a", "status": "failed"},
        {"node_id": None, "status": "success"},
        {"node_id": "", "status": "failed"},
        {"node_id": "b"},
        {"node_id": "a", "status": "success"},
    ]

    assert node_statuses(events) == {"a": "success", "b": "success"}


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.commits = 0

    def scalars(self, _statement: Any) -> _FakeScalars:
        return _FakeScalars(self._rows)

    def commit(self) -> None:
        self.commits += 1


def test_mark_deliveries_updates_rows_and_commits() -> None:
    rows = [SimpleNamespace(status="queued"), SimpleNamespace(status="queued")]
    db = _FakeSession(rows)

    mark_deliveries(db, "exec_1", "success")  # type: ignore[arg-type]

    assert [row.status for row in rows] == ["success", "success"]
    assert db.commits == 1


def test_mark_deliveries_without_rows_does_not_commit() -> None:
    db = _FakeSession([])

    mark_deliveries(db, "exec_1", "failed")  # type: ignore[arg-type]

    assert db.commits == 0


def test_cancelled_error_constant_shape() -> None:
    assert CANCELLED_ERROR == {
        "code": "CANCELLED",
        "message": "Execution cancelled by user.",
    }
