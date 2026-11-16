"""Application-service tests for execution writes (real DB, fake eventing).

These pin the behaviour extracted from ``api/executions``: cancellation
branches (CAS transitions, approval cleanup, child cascade, bus/audit) and
the resume transaction (durable approval authority, expiry/quorum, payloads,
queue compensation and audit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.audit import EXECUTION_CANCEL, EXECUTION_RESUME, EXECUTION_RETRY
from app.credentials.type_registry import get_credential_type_registry
from app.db import get_session
from app.engine.errors import WorkflowValidationError
from app.models import (
    ApprovalRequest,
    Execution,
    ExecutionRetryHistory,
    User,
    WorkflowRecord,
)
from app.services.execution_service import ExecutionService, ExecutionServiceError


@pytest.fixture
def db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def owner(db):
    user = User(email="cancel_service@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workflow = WorkflowRecord(
        id="wf_cancel_service",
        user_id=user.id,
        name="Cancel Service",
        data={},
    )
    db.add(workflow)
    db.commit()
    return user, workflow


@dataclass
class Recording:
    bus: list[tuple[str, dict]] = field(default_factory=list)
    audit: list[tuple[tuple, dict]] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)


@dataclass
class FakeQueue:
    """Queue double that records payloads and can force both failure paths."""

    requeue_ok: bool = True
    enqueue_ok: bool = True
    requeues: list[tuple[str, dict]] = field(default_factory=list)
    enqueues: list[tuple[str, str, dict]] = field(default_factory=list)

    def requeue(self, execution_id: str, payload: dict[str, Any]) -> bool:
        self.requeues.append((execution_id, payload))
        return self.requeue_ok

    def enqueue(
        self, job_id: str, execution_id: str, payload: dict[str, Any]
    ) -> bool:
        self.enqueues.append((job_id, execution_id, payload))
        return self.enqueue_ok


def _service(db, *, queue: Any = None) -> tuple[ExecutionService, Recording]:
    recorded = Recording()
    service = ExecutionService(
        db,
        signal_cancel=lambda execution_id: recorded.signals.append(execution_id) or True,
        bus_publish=lambda execution_id, event: recorded.bus.append((execution_id, event)),
        audit=lambda *args, **kwargs: recorded.audit.append((args, kwargs)),
        queue=queue,
        ensure_consumer=lambda: recorded.consumers.append("started"),
    )
    return service, recorded


_UNSET = object()


def _execution(
    db,
    owner,
    execution_id: str,
    status: str,
    *,
    trigger: str = "manual",
    parent_execution_id: str | None = None,
    pause_state=_UNSET,
    error=_UNSET,
) -> Execution:
    user, workflow = owner
    rec = Execution(
        id=execution_id,
        workflow_id=workflow.id,
        user_id=user.id,
        workflow_version=1,
        workflow_data={},
        trigger=trigger,
        status=status,
        parent_execution_id=parent_execution_id,
    )
    if pause_state is not _UNSET:
        rec.pause_state = pause_state
    if error is not _UNSET:
        rec.error = error
    db.add(rec)
    db.commit()
    return rec


def _refresh(db, model, row_id):
    db.expire_all()
    return db.get(model, row_id)


def _approval(
    db,
    rec: Execution,
    *,
    request_id: str = "appr_service",
    status: str = "pending",
    node_id: str | None = None,
    quorum: int = 1,
    approvers: list[int] | None = None,
    separation_of_duties: bool = False,
) -> ApprovalRequest:
    request = ApprovalRequest(
        id=request_id,
        run_id=rec.id,
        workflow_id=rec.workflow_id,
        node_id=node_id or (rec.pause_state or {}).get("node_id") or "",
        status=status,
        quorum=quorum,
        approvers=approvers or [],
        separation_of_duties=separation_of_duties,
    )
    db.add(request)
    db.commit()
    return request


# ---------------------------------------------------------------------------
# Queued / double cancel / CAS
# ---------------------------------------------------------------------------


def test_cancel_queued_execution_is_terminal(db, owner):
    service, recorded = _service(db)
    user, _workflow = owner
    rec = _execution(db, owner, "exec_service_queued", "queued")

    assert service.cancel(rec, user_id=user.id) == "cancelled"

    fresh = _refresh(db, Execution, rec.id)
    assert fresh.status == "cancelled"
    assert fresh.finished_at is not None
    assert fresh.error == {
        "code": "CANCELLED_IN_QUEUE",
        "message": "Execution cancelled before starting.",
    }
    assert recorded.bus == [(
        rec.id,
        {
            "event": "execution.cancelled",
            "execution_id": rec.id,
            "workflow_id": fresh.workflow_id,
            "status": "cancelled",
        },
    )]
    assert "execution.cancel" == recorded.audit[0][0][1]


def test_double_cancel_raises_typed_conflict(db, owner):
    service, _recorded = _service(db)
    user, _workflow = owner
    rec = _execution(db, owner, "exec_service_double", "queued")

    service.cancel(rec, user_id=user.id)
    db.refresh(rec)

    with pytest.raises(ExecutionServiceError) as raised:
        service.cancel(rec, user_id=user.id)

    assert raised.value.code == "EXECUTION_NOT_RUNNING"
    assert raised.value.http_status == 409
    assert raised.value.message == "Execution is not running."
    assert _refresh(db, Execution, rec.id).status == "cancelled"


def test_cas_loses_race_against_another_canceller(db, owner):
    """A stale row observed as queued must not overwrite a concurrent transition."""
    service, _recorded = _service(db)
    user, _workflow = owner
    rec = _execution(db, owner, "exec_service_race", "queued")

    with get_session() as other:
        other.query(Execution).filter(Execution.id == rec.id).update(
            {"status": "cancelled"}
        )
        other.commit()

    # This session still holds the pre-race row, so the precheck passes but the
    # compare-and-set must detect the lost race.
    assert rec.status == "queued"
    with pytest.raises(ExecutionServiceError) as raised:
        service.cancel(rec, user_id=user.id)

    assert raised.value.code == "EXECUTION_NOT_QUEUED"
    assert raised.value.http_status == 409


def test_cancel_terminal_execution_raises_not_running(db, owner):
    service, _recorded = _service(db)
    user, _workflow = owner
    rec = _execution(db, owner, "exec_service_done", "success")

    with pytest.raises(ExecutionServiceError) as raised:
        service.cancel(rec, user_id=user.id)

    assert raised.value.code == "EXECUTION_NOT_RUNNING"
    assert raised.value.http_status == 409


# ---------------------------------------------------------------------------
# Force cancel / running
# ---------------------------------------------------------------------------


def test_force_cancel_cancelling_execution(db, owner):
    service, recorded = _service(db)
    user, _workflow = owner
    rec = _execution(db, owner, "exec_service_force", "cancelling")

    assert service.cancel(rec, user_id=user.id) == "cancelled"

    fresh = _refresh(db, Execution, rec.id)
    assert fresh.status == "cancelled"
    assert fresh.finished_at is not None
    assert fresh.error == {
        "code": "FORCE_CANCELLED",
        "message": "Execution force-cancelled by user.",
    }
    assert recorded.signals == [rec.id]
    assert recorded.bus == [(
        rec.id,
        {
            "event": "execution.cancelled",
            "execution_id": rec.id,
            "workflow_id": fresh.workflow_id,
            "status": "cancelled",
        },
    )]


def test_cancel_running_branch_sets_cancelling_and_signals(db, owner):
    service, recorded = _service(db)
    user, _workflow = owner
    rec = _execution(db, owner, "exec_service_running", "running")

    assert service.cancel(rec, user_id=user.id) == "cancelling"

    fresh = _refresh(db, Execution, rec.id)
    assert fresh.status == "cancelling"
    assert fresh.finished_at is None
    assert recorded.signals == [rec.id]
    assert recorded.bus == [(
        rec.id,
        {
            "event": "execution.cancelling",
            "execution_id": rec.id,
            "workflow_id": fresh.workflow_id,
            "status": "cancelling",
        },
    )]


# ---------------------------------------------------------------------------
# Waiting approval cleanup / child cascade
# ---------------------------------------------------------------------------


def test_cancel_waiting_execution_closes_only_pending_approvals(db, owner):
    service, _recorded = _service(db)
    user, workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_service_waiting",
        "waiting_approval",
        pause_state={"node_id": "approve", "message": "Need approval"},
    )
    pending = ApprovalRequest(
        id="appr_pending",
        run_id=rec.id,
        workflow_id=workflow.id,
        node_id="approve",
        status="pending",
        decision={"decisions": [{"user_id": user.id, "approved": False}]},
    )
    approved = ApprovalRequest(
        id="appr_approved",
        run_id=rec.id,
        workflow_id=workflow.id,
        node_id="previous",
        status="approved",
        decision={"reason": "already decided"},
    )
    db.add_all([pending, approved])
    db.commit()

    assert service.cancel(rec, user_id=user.id) == "cancelled"

    fresh = _refresh(db, Execution, rec.id)
    assert fresh.status == "cancelled"
    assert fresh.pause_state is None
    assert fresh.error == {
        "code": "CANCELLED_WHILE_WAITING",
        "message": "Cancelled while waiting for action.",
    }

    fresh_pending = _refresh(db, ApprovalRequest, "appr_pending")
    assert fresh_pending.status == "cancelled"
    assert fresh_pending.decision == {
        "decisions": [{"user_id": user.id, "approved": False}],
        "reason": "execution_cancelled",
    }
    fresh_approved = _refresh(db, ApprovalRequest, "appr_approved")
    assert fresh_approved.status == "approved"
    assert fresh_approved.decision == {"reason": "already decided"}


def test_cancel_waiting_parent_cascades_child_checkpoints(db, owner):
    service, _recorded = _service(db)
    user, _workflow = owner
    parent = _execution(
        db,
        owner,
        "exec_service_parent",
        "waiting_approval",
        pause_state={"node_id": "approve"},
    )
    active_children = {
        "child_queued": _execution(
            db, owner, "child_queued", "queued",
            trigger="sub_workflow", parent_execution_id=parent.id,
        ),
        "child_running": _execution(
            db, owner, "child_running", "running",
            trigger="sub_workflow", parent_execution_id=parent.id,
        ),
        "child_waiting": _execution(
            db, owner, "child_waiting", "waiting_approval",
            trigger="sub_workflow", parent_execution_id=parent.id,
            pause_state={"node_id": "child_approve"},
        ),
        "child_cancelling": _execution(
            db, owner, "child_cancelling", "cancelling",
            trigger="sub_workflow", parent_execution_id=parent.id,
        ),
    }
    finished_child = _execution(
        db, owner, "child_finished", "success",
        trigger="sub_workflow", parent_execution_id=parent.id,
    )
    unrelated_child = _execution(
        db, owner, "child_manual", "running",
        trigger="manual", parent_execution_id=parent.id,
    )

    assert service.cancel(parent, user_id=user.id) == "cancelled"

    for child_id in active_children:
        child = _refresh(db, Execution, child_id)
        assert child.status == "cancelled", child_id
        assert child.pause_state is None, child_id
        assert child.finished_at is not None, child_id
        assert child.error == {
            "code": "PARENT_CANCELLED",
            "message": "Parent execution was cancelled.",
        }, child_id

    assert _refresh(db, Execution, finished_child.id).status == "success"
    assert _refresh(db, Execution, unrelated_child.id).status == "running"


# ---------------------------------------------------------------------------
# Bus + audit contract
# ---------------------------------------------------------------------------


def test_cancel_records_bus_event_and_audit_with_user(db, owner):
    service, recorded = _service(db)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_service_events",
        "running",
        pause_state=None,
    )

    service.cancel(rec, user_id=user.id)

    assert recorded.bus[0][0] == rec.id
    assert recorded.bus[0][1]["event"] == "execution.cancelling"
    assert recorded.bus[0][1]["status"] == "cancelling"
    assert len(recorded.audit) == 1
    args, kwargs = recorded.audit[0]
    assert args[0] is db
    assert args[1] == EXECUTION_CANCEL
    assert kwargs == {
        "target_type": "execution",
        "target_id": rec.id,
        "user_id": user.id,
    }


def test_existing_error_payload_is_preserved(db, owner):
    """Cancellation must not overwrite a richer error already on the row."""
    service, _recorded = _service(db)
    user, _workflow = owner
    existing = {"code": "TIMEOUT", "message": "Node timed out", "node_id": "http"}
    rec = _execution(
        db, owner, "exec_service_error", "queued", error=existing
    )

    service.cancel(rec, user_id=user.id)

    assert _refresh(db, Execution, rec.id).error == existing


# ---------------------------------------------------------------------------
# Resume: durable approvals, payloads, queue compensation and audit
# ---------------------------------------------------------------------------


def test_resume_pending_approval_decides_and_queues(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_pending",
        "waiting_approval",
        pause_state={
            "node_id": "gate",
            "message": "Need approval",
            "approvers": [user.id],
            "type": "approval",
        },
    )
    request = _approval(db, rec, approvers=[user.id])

    assert service.resume(
        rec, user_id=user.id, approved=True, workspace_id="ws_resume"
    ) == "queued"

    assert _refresh(db, Execution, rec.id).status == "queued"
    fresh_request = _refresh(db, ApprovalRequest, request.id)
    assert fresh_request.status == "approved"
    assert fresh_request.decided_by == user.id

    assert len(queue.requeues) == 1
    execution_id, payload = queue.requeues[0]
    assert execution_id == rec.id
    assert payload["workflow_id"] == rec.workflow_id
    assert payload["workspace_id"] == "ws_resume"
    assert payload["trigger_items"] == [{}]
    approval_data = payload["_approval_data"]
    assert approval_data["approved"] is True
    assert approval_data["approved_by"] == user.id
    assert approval_data["node_id"] == "gate"
    assert approval_data["pause_type"] == "approval"
    # The payload carries the pause's bound request id; this test exercises
    # the fallback lookup by (run_id, node_id) because the pause predates the
    # durable broker and has no approval_id.
    assert approval_data["approval_id"] is None
    assert approval_data["state"] is None
    assert datetime.fromisoformat(approval_data["approved_at"]).tzinfo is not None

    args, kwargs = recorded.audit[0]
    assert args == (db, EXECUTION_RESUME)
    assert kwargs["target_type"] == "execution"
    assert kwargs["target_id"] == rec.id
    assert kwargs["user_id"] == user.id
    assert kwargs["detail"] == {"resumed_from": "waiting_approval", "approved": True}


@pytest.mark.parametrize(
    ("durable_status", "requested", "effective"),
    [("approved", False, True), ("rejected", True, False)],
)
def test_resume_durable_decision_is_authoritative(
    db, owner, durable_status, requested, effective
):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_durable",
        "waiting_approval",
        pause_state={
            "node_id": "gate",
            "approval_id": "appr_durable",
            "approvers": [user.id],
        },
    )
    request = _approval(
        db, rec, request_id="appr_durable", status=durable_status, approvers=[user.id]
    )

    assert service.resume(
        rec, user_id=user.id, approved=requested, workspace_id=None
    ) == "queued"

    assert _refresh(db, Execution, rec.id).status == "queued"
    fresh_request = _refresh(db, ApprovalRequest, request.id)
    assert fresh_request.status == durable_status
    payload = queue.requeues[0][1]
    assert payload["_approval_data"]["approved"] is effective
    assert recorded.audit[0][1]["detail"] == {
        "resumed_from": "waiting_approval",
        "approved": effective,
    }


def test_resume_expired_approval_conflicts_without_queueing(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_expired",
        "waiting_approval",
        pause_state={
            "node_id": "gate",
            "approval_id": "appr_expired",
            "approvers": [user.id],
        },
    )
    request = _approval(
        db, rec, request_id="appr_expired", status="expired", approvers=[user.id]
    )

    with pytest.raises(ExecutionServiceError) as raised:
        service.resume(rec, user_id=user.id, approved=True, workspace_id=None)

    assert raised.value.code == "APPROVAL_EXPIRED"
    assert raised.value.http_status == 409
    assert raised.value.message == (
        "The approval request has expired; the run cannot be resumed."
    )
    assert _refresh(db, Execution, rec.id).status == "waiting_approval"
    assert _refresh(db, ApprovalRequest, request.id).status == "expired"
    assert queue.requeues == []
    assert queue.enqueues == []
    assert recorded.audit == []


def test_resume_quorum_not_met_keeps_execution_waiting(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_quorum",
        "waiting_approval",
        pause_state={"node_id": "gate", "approvers": [user.id]},
    )
    request = _approval(db, rec, quorum=2, approvers=[user.id])

    with pytest.raises(ExecutionServiceError) as raised:
        service.resume(rec, user_id=user.id, approved=True, workspace_id=None)

    assert raised.value.code == "APPROVAL_QUORUM_NOT_MET"
    assert raised.value.http_status == 409
    assert raised.value.message == (
        "Approval quorum not met (1/2); the run remains paused."
    )
    assert _refresh(db, Execution, rec.id).status == "waiting_approval"
    assert _refresh(db, ApprovalRequest, request.id).status == "pending"
    assert queue.requeues == []
    assert recorded.audit == []


def test_resume_requires_listed_approver(db, owner):
    queue = FakeQueue()
    service, _recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_approver",
        "waiting_approval",
        pause_state={"node_id": "gate", "approvers": [user.id + 1]},
    )

    with pytest.raises(ExecutionServiceError) as raised:
        service.resume(rec, user_id=user.id, approved=True, workspace_id=None)

    assert raised.value.code == "NOT_AN_APPROVER"
    assert raised.value.http_status == 403
    assert raised.value.message == "You are not a listed approver for this step."
    assert _refresh(db, Execution, rec.id).status == "waiting_approval"
    assert queue.requeues == []


def test_double_resume_conflicts(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_double",
        "waiting_approval",
        pause_state={"node_id": "gate"},
    )

    assert service.resume(
        rec, user_id=user.id, approved=True, workspace_id=None
    ) == "queued"
    with pytest.raises(ExecutionServiceError) as raised:
        service.resume(rec, user_id=user.id, approved=True, workspace_id=None)

    assert raised.value.code == "EXECUTION_NOT_WAITING"
    assert raised.value.http_status == 409
    assert raised.value.message == (
        "Execution is not waiting for approval or authentication."
    )
    assert len(queue.requeues) == 1
    assert len(recorded.audit) == 1


def test_resume_auth_pause_payload_reruns_from_node(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_auth",
        "waiting_auth",
        pause_state={
            "node_id": "authenticate",
            "type": "authentication",
            "state": {"checkpoint": "encrypted"},
            "approvers": [user.id + 1],
        },
    )

    assert service.resume(
        rec, user_id=user.id, approved=False, workspace_id="ws_auth"
    ) == "queued"

    assert _refresh(db, Execution, rec.id).status == "queued"
    execution_id, payload = queue.requeues[0]
    assert execution_id == rec.id
    assert payload["_retry_from_node"] == "authenticate"
    assert payload["_retry_source"] == rec.id
    assert payload["workspace_id"] == "ws_auth"
    assert "_approval_data" not in payload
    # Authentication pauses are not approval-gated, so the approvers list is
    # irrelevant and no durable request is consulted.
    assert recorded.audit[0][1]["detail"] == {
        "resumed_from": "waiting_auth",
        "approved": False,
    }


def test_resume_requeue_failure_falls_back_to_enqueue(db, owner):
    queue = FakeQueue(requeue_ok=False, enqueue_ok=True)
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_fallback",
        "waiting_approval",
        pause_state={"node_id": "gate"},
    )

    assert service.resume(
        rec, user_id=user.id, approved=True, workspace_id=None
    ) == "queued"

    assert len(queue.requeues) == 1
    assert len(queue.enqueues) == 1
    job_id, execution_id, payload = queue.enqueues[0]
    assert job_id.startswith("job_")
    assert execution_id == rec.id
    assert payload == queue.requeues[0][1]
    assert _refresh(db, Execution, rec.id).status == "queued"
    assert len(recorded.audit) == 1


def test_resume_enqueue_failure_compensates_to_waiting(db, owner):
    queue = FakeQueue(requeue_ok=False, enqueue_ok=False)
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_compensate",
        "waiting_approval",
        pause_state={"node_id": "gate"},
    )

    with pytest.raises(ExecutionServiceError) as raised:
        service.resume(rec, user_id=user.id, approved=True, workspace_id=None)

    assert raised.value.code == "EXECUTION_ALREADY_QUEUED"
    assert raised.value.http_status == 409
    assert raised.value.message == "Execution is already queued."
    assert _refresh(db, Execution, rec.id).status == "waiting_approval"
    assert len(queue.requeues) == 1
    assert len(queue.enqueues) == 1
    assert recorded.audit == []


def test_resume_records_audit_detail(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _execution(
        db,
        owner,
        "exec_resume_audit",
        "waiting_approval",
        pause_state={"node_id": "gate"},
    )

    service.resume(rec, user_id=user.id, approved=False, workspace_id=None)

    args, kwargs = recorded.audit[0]
    assert args == (db, EXECUTION_RESUME)
    assert kwargs == {
        "target_type": "execution",
        "target_id": rec.id,
        "user_id": user.id,
        "detail": {"resumed_from": "waiting_approval", "approved": False},
    }


# ---------------------------------------------------------------------------
# Start: row creation, credential pre-validation, enqueue/compensation
# ---------------------------------------------------------------------------


def _start_workflow_data(workflow_id: str) -> dict[str, Any]:
    return {
        "id": workflow_id,
        "nodes": [{"id": "trigger", "type": "manual_trigger"}],
        "connections": [],
    }


def test_start_execution_creates_queued_row_and_enqueues(db, owner, monkeypatch):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, workflow = owner
    started: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.services.execution_service.execution_started",
        lambda execution_id, trigger: started.append((execution_id, trigger)),
    )
    workflow_data = _start_workflow_data(workflow.id)

    execution_id = service.start_execution(
        workflow_id=workflow.id,
        user_id=user.id,
        version=4,
        workflow_data=workflow_data,
        trigger="manual",
        trigger_items=[{"name": "Ada"}],
        workspace_id="ws_start",
        extra_payload={"_run_node": "trigger", "extra": True},
        parent_execution_id="exec_parent",
        retry_count=2,
        correlation_id="corr_start",
        organization_id="org_start",
    )

    fresh = _refresh(db, Execution, execution_id)
    assert execution_id.startswith("exec_")
    assert fresh.status == "queued"
    assert fresh.workflow_id == workflow.id
    assert fresh.workflow_version == 4
    assert fresh.workflow_data == workflow_data
    assert fresh.trigger == "manual"
    assert fresh.trigger_data == [{"name": "Ada"}]
    assert fresh.workspace_id == "ws_start"
    assert fresh.parent_execution_id == "exec_parent"
    assert fresh.retry_count == 2
    assert fresh.correlation_id == "corr_start"
    assert fresh.organization_id == "org_start"
    assert fresh.started_at is not None
    assert fresh.finished_at is None

    assert len(queue.enqueues) == 1
    job_id, queued_execution_id, payload = queue.enqueues[0]
    assert job_id.startswith("job_")
    assert queued_execution_id == execution_id
    assert payload["workflow_data"] == workflow_data
    assert payload["trigger_items"] == [{"name": "Ada"}]
    assert payload["trigger"] == "manual"
    assert payload["user_id"] == user.id
    assert payload["workflow_id"] == workflow.id
    assert payload["version"] == 4
    assert payload["workspace_id"] == "ws_start"
    assert payload["_run_node"] == "trigger"
    assert payload["extra"] is True
    assert recorded.consumers == ["started"]
    assert started == [(execution_id, "manual")]


def test_start_execution_credential_provider_failure_records_failed_row(
    db, owner, monkeypatch
):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, workflow = owner
    monkeypatch.setitem(
        get_credential_type_registry()._by_id,
        "mock_unimplemented",
        {
            "id": "mock_unimplemented",
            "provider": "mock",
            "implemented": False,
        },
    )
    workflow_data = {
        "id": workflow.id,
        "nodes": [{
            "id": "needs_auth",
            "type": "code",
            "credentials": {"mock_unimplemented": "cred_missing"},
        }],
        "connections": [],
    }

    with pytest.raises(WorkflowValidationError) as raised:
        service.start_execution(
            workflow_id=workflow.id,
            user_id=user.id,
            version=1,
            workflow_data=workflow_data,
            trigger="manual",
            trigger_items=[{}],
        )

    assert any(
        issue["code"] == "CREDENTIAL_PROVIDER_NOT_IMPLEMENTED"
        for issue in raised.value.issues
    )
    row = db.scalar(
        select(Execution).where(Execution.workflow_id == workflow.id)
    )
    assert row is not None
    assert row.status == "failed"
    assert row.http_status_code == 400
    assert row.finished_at is not None
    assert row.error is not None
    assert row.error["code"] == "INVALID_WORKFLOW"
    assert queue.enqueues == []
    assert recorded.consumers == []


def test_start_execution_duplicate_queue_compensates_row(db, owner):
    queue = FakeQueue(enqueue_ok=False)
    service, recorded = _service(db, queue=queue)
    user, workflow = owner

    execution_id = service.start_execution(
        workflow_id=workflow.id,
        user_id=user.id,
        version=1,
        workflow_data=_start_workflow_data(workflow.id),
        trigger="webhook",
        trigger_items=[{}],
    )

    fresh = _refresh(db, Execution, execution_id)
    assert fresh.status == "failed"
    assert fresh.error == {
        "code": "DUPLICATE_QUEUE",
        "message": "Execution was already queued.",
    }
    assert fresh.finished_at is None
    assert len(queue.enqueues) == 1
    # The historical flow still starts the consumer and records metrics
    # after compensating the row.
    assert recorded.consumers == ["started"]


# ---------------------------------------------------------------------------
# Retry: idempotency, node validation, history and audit
# ---------------------------------------------------------------------------


def _failed_execution(
    db,
    owner,
    execution_id: str = "exec_retry_parent",
    *,
    status: str = "failed",
    node_statuses: dict[str, str] | None = None,
) -> Execution:
    rec = _execution(db, owner, execution_id, status, trigger="webhook")
    rec.workflow_data = {
        "id": rec.workflow_id,
        "nodes": [{"id": "boom", "type": "boom"}],
        "connections": [],
    }
    rec.trigger_data = [{"id": 1}]
    rec.retry_count = 1
    rec.correlation_id = "corr_parent"
    rec.organization_id = "org_parent"
    rec.node_statuses = node_statuses
    db.commit()
    return rec


def test_retry_creates_execution_history_and_audit(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _failed_execution(db, owner)

    outcome = service.retry_execution(
        rec,
        user_id=user.id,
        workspace_id="ws_retry",
        reason="upstream recovered",
        idempotency_key="idem_retry",
    )

    assert outcome.idempotent_replay is False
    assert outcome.attempt_number == 2
    new = _refresh(db, Execution, outcome.execution_id)
    assert new.trigger == "retry"
    assert new.retry_count == 2
    assert new.parent_execution_id == rec.id
    assert new.workspace_id == "ws_retry"
    assert new.correlation_id == "corr_parent"
    assert new.organization_id == "org_parent"
    assert new.trigger_data == [{"id": 1}]

    history = db.scalars(select(ExecutionRetryHistory)).all()
    assert len(history) == 1
    row = history[0]
    assert row.original_execution_id == rec.id
    assert row.retry_execution_id == outcome.execution_id
    assert row.attempt_number == 2
    assert row.retry_reason == "upstream recovered"
    assert row.retry_policy == "idem_retry"
    assert row.failed_step_id is None
    assert row.retry_trigger == "manual"
    assert row.initiated_by_user_id == user.id
    assert row.status == "pending"

    args, kwargs = recorded.audit[0]
    assert args == (db, EXECUTION_RETRY)
    assert kwargs == {
        "target_type": "execution",
        "target_id": rec.id,
        "user_id": user.id,
        "detail": {
            "new_execution_id": outcome.execution_id,
            "attempt_number": 2,
        },
    }
    assert len(queue.enqueues) == 1


def test_retry_idempotency_key_replays_without_side_effects(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _failed_execution(db, owner)

    first = service.retry_execution(
        rec, user_id=user.id, idempotency_key="same_key"
    )
    second = service.retry_execution(
        rec, user_id=user.id, idempotency_key="same_key"
    )

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.execution_id == first.execution_id
    assert second.attempt_number == first.attempt_number
    assert len(queue.enqueues) == 1
    assert len(db.scalars(select(ExecutionRetryHistory)).all()) == 1
    assert len(recorded.audit) == 1


def test_retry_node_records_failed_step_and_seeded_payload(db, owner):
    queue = FakeQueue()
    service, recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _failed_execution(
        db, owner, "exec_retry_node", node_statuses={"boom": "error"}
    )

    outcome = service.retry_execution(
        rec, user_id=user.id, node_id="boom"
    )

    new = _refresh(db, Execution, outcome.execution_id)
    assert new.trigger == "node_retry"
    job_payload = queue.enqueues[0][2]
    assert job_payload["_retry_from_node"] == "boom"
    assert job_payload["_retry_source"] == rec.id

    row = db.scalars(select(ExecutionRetryHistory)).one()
    assert row.failed_step_id == "boom"
    assert row.retry_reason == "node_retry"
    assert recorded.audit[0][1]["detail"] == {
        "new_execution_id": outcome.execution_id,
        "attempt_number": 2,
        "node_id": "boom",
    }


def test_retry_node_rejects_running_and_non_failed_nodes(db, owner):
    queue = FakeQueue()
    service, _recorded = _service(db, queue=queue)
    user, _workflow = owner
    rec = _failed_execution(
        db,
        owner,
        "exec_retry_conflict",
        status="running",
        node_statuses={"boom": "error"},
    )

    with pytest.raises(ExecutionServiceError) as raised:
        service.retry_execution(rec, user_id=user.id, node_id="boom")
    assert raised.value.code == "EXECUTION_IN_PROGRESS"
    assert raised.value.http_status == 409
    assert raised.value.message == (
        "Cannot retry a node while the execution is still running."
    )

    rec.status = "failed"
    rec.node_statuses = {"boom": "success"}
    db.commit()
    with pytest.raises(ExecutionServiceError) as raised:
        service.retry_execution(rec, user_id=user.id, node_id="boom")
    assert raised.value.code == "NODE_NOT_RETRYABLE"
    assert raised.value.http_status == 409
    assert raised.value.message == (
        "Node 'boom' did not fail (status: success); only failed nodes can be "
        "retried safely."
    )

    with pytest.raises(ExecutionServiceError) as raised:
        service.retry_execution(rec, user_id=user.id, node_id="missing")
    assert raised.value.code == "UNKNOWN_NODE"
    assert raised.value.http_status == 404
    assert raised.value.message == "Unknown node 'missing'."

    assert queue.enqueues == []
    assert db.scalars(select(ExecutionRetryHistory)).all() == []
