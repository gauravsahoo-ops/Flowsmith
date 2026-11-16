"""ApprovalRepository read-core tests (no FastAPI, no TestClient)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ApprovalRequest, Execution, User, WorkflowRecord
from app.repositories.approvals import ApprovalRepository


def _user(db: Session, email: str = "approver@example.com") -> User:
    user = User(email=email, password_hash="x", role="member", active=True)
    db.add(user)
    db.flush()
    return user


def _workflow(
    db: Session, user: User, workflow_id: str, *, name: str = "Approval Workflow"
) -> WorkflowRecord:
    rec = WorkflowRecord(
        id=workflow_id,
        user_id=user.id,
        name=name,
        data={"id": workflow_id, "nodes": [], "connections": []},
        version=1,
    )
    db.add(rec)
    db.flush()
    return rec


def _execution(
    db: Session,
    *,
    user: User,
    workflow_id: str,
    execution_id: str,
    status: str = "waiting_approval",
) -> Execution:
    rec = Execution(
        id=execution_id,
        workflow_id=workflow_id,
        user_id=user.id,
        workflow_version=1,
        workflow_data={"id": workflow_id, "nodes": [], "connections": []},
        trigger="manual",
        status=status,
        started_at=datetime.now(UTC),
    )
    db.add(rec)
    db.flush()
    return rec


def _approval(
    db: Session,
    *,
    run_id: str,
    request_id: str,
    status: str = "pending",
    created_at: datetime | None = None,
    node_id: str = "gate",
    approvers: list[int] | None = None,
) -> ApprovalRequest:
    request = ApprovalRequest(
        id=request_id,
        run_id=run_id,
        node_id=node_id,
        reason="Sensitive side effect",
        status=status,
        approvers=approvers or [],
        created_at=created_at or datetime.now(UTC),
    )
    db.add(request)
    db.flush()
    return request


def _capture_statements(db: Session, action: Callable[[], object]) -> list[str]:
    statements: list[str] = []

    def _listener(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _listener)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", _listener)
    return statements


def test_get_returns_existing_and_missing(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_get_appr")
    _execution(db, user=user, workflow_id="wf_get_appr", execution_id="exec_get_appr")
    _approval(db, run_id="exec_get_appr", request_id="appr_get")
    db.commit()

    repo = ApprovalRepository(db)
    request = repo.get("appr_get")
    assert request is not None
    assert request.id == "appr_get"
    assert repo.get("appr_missing") is None


def test_get_for_update_returns_existing_and_missing(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_lock_appr")
    _execution(db, user=user, workflow_id="wf_lock_appr", execution_id="exec_lock_appr")
    _approval(db, run_id="exec_lock_appr", request_id="appr_lock")
    db.commit()

    repo = ApprovalRepository(db)
    statements = _capture_statements(db, lambda: repo.get_for_update("appr_lock"))
    request = repo.get_for_update("appr_lock")
    assert request is not None
    assert request.id == "appr_lock"
    assert any("FOR UPDATE" in statement.upper() for statement in statements)
    assert repo.get_for_update("appr_missing") is None


def test_list_for_workflows_scopes_filters_orders_and_limits(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_appr_a")
    _workflow(db, user, "wf_appr_b")
    _execution(db, user=user, workflow_id="wf_appr_a", execution_id="exec_a_old")
    _execution(db, user=user, workflow_id="wf_appr_a", execution_id="exec_a_new")
    _execution(db, user=user, workflow_id="wf_appr_b", execution_id="exec_b")
    now = datetime.now(UTC)
    _approval(
        db,
        run_id="exec_a_old",
        request_id="appr_a_old",
        created_at=now - timedelta(minutes=3),
    )
    _approval(
        db,
        run_id="exec_b",
        request_id="appr_b",
        created_at=now - timedelta(minutes=2),
    )
    _approval(
        db,
        run_id="exec_a_new",
        request_id="appr_a_new",
        status="approved",
        created_at=now - timedelta(minutes=1),
    )
    db.commit()

    repo = ApprovalRepository(db)
    assert [r.id for r in repo.list_for_workflows(["wf_appr_a"])] == [
        "appr_a_new",
        "appr_a_old",
    ]
    assert [
        r.id for r in repo.list_for_workflows(["wf_appr_a"], status="pending")
    ] == ["appr_a_old"]
    assert [
        r.id for r in repo.list_for_workflows(["wf_appr_a"], limit=1)
    ] == ["appr_a_new"]
    assert [
        r.id for r in repo.list_for_workflows(["wf_appr_a", "wf_appr_b"])
    ] == ["appr_a_new", "appr_b", "appr_a_old"]
    assert repo.list_for_workflows([]) == []


def test_list_recent_filters_orders_and_limits(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_recent_a")
    _workflow(db, user, "wf_recent_b")
    _execution(db, user=user, workflow_id="wf_recent_a", execution_id="exec_recent_a")
    _execution(db, user=user, workflow_id="wf_recent_b", execution_id="exec_recent_b")
    now = datetime.now(UTC)
    _approval(
        db,
        run_id="exec_recent_a",
        request_id="appr_recent_old",
        created_at=now - timedelta(minutes=3),
    )
    _approval(
        db,
        run_id="exec_recent_b",
        request_id="appr_recent_mid",
        created_at=now - timedelta(minutes=2),
    )
    _approval(
        db,
        run_id="exec_recent_a",
        request_id="appr_recent_new",
        status="approved",
        created_at=now - timedelta(minutes=1),
    )
    db.commit()

    repo = ApprovalRepository(db)
    assert [r.id for r in repo.list_recent()] == [
        "appr_recent_new",
        "appr_recent_mid",
        "appr_recent_old",
    ]
    assert [r.id for r in repo.list_recent(status="pending")] == [
        "appr_recent_mid",
        "appr_recent_old",
    ]
    assert [r.id for r in repo.list_recent(limit=1)] == ["appr_recent_new"]
    assert [r.id for r in repo.list_recent(status="pending", limit=1)] == [
        "appr_recent_mid"
    ]


def test_list_pending_for_run_is_scoped_to_run_and_status(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_pending")
    _execution(db, user=user, workflow_id="wf_pending", execution_id="exec_pending")
    _execution(
        db, user=user, workflow_id="wf_pending", execution_id="exec_pending_other"
    )
    now = datetime.now(UTC)
    _approval(
        db,
        run_id="exec_pending",
        request_id="appr_pending_old",
        created_at=now - timedelta(minutes=2),
    )
    _approval(
        db,
        run_id="exec_pending",
        request_id="appr_pending_new",
        created_at=now - timedelta(minutes=1),
    )
    _approval(
        db,
        run_id="exec_pending",
        request_id="appr_pending_done",
        status="approved",
        created_at=now,
    )
    _approval(
        db,
        run_id="exec_pending_other",
        request_id="appr_pending_other",
        created_at=now,
    )
    db.commit()

    rows = ApprovalRepository(db).list_pending_for_run("exec_pending")
    assert [row.id for row in rows] == ["appr_pending_new", "appr_pending_old"]
    assert ApprovalRepository(db).list_pending_for_run("exec_missing") == []


def test_latest_for_run_node_returns_newest_regardless_of_status(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_latest_appr")
    _execution(db, user=user, workflow_id="wf_latest_appr", execution_id="exec_latest_appr")
    now = datetime.now(UTC)
    _approval(
        db,
        run_id="exec_latest_appr",
        request_id="appr_latest_old",
        node_id="gate",
        status="rejected",
        created_at=now - timedelta(minutes=2),
    )
    _approval(
        db,
        run_id="exec_latest_appr",
        request_id="appr_latest_new",
        node_id="gate",
        created_at=now - timedelta(minutes=1),
    )
    _approval(
        db,
        run_id="exec_latest_appr",
        request_id="appr_latest_other_node",
        node_id="other_gate",
        created_at=now,
    )
    db.commit()

    repo = ApprovalRepository(db)
    latest = repo.latest_for_run_node("exec_latest_appr", "gate")
    assert latest is not None
    assert latest.id == "appr_latest_new"
    assert repo.latest_for_run_node("exec_latest_appr", "missing") is None
    assert repo.latest_for_run_node("exec_missing", "gate") is None


def test_add_stages_without_flushing(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_add_appr")
    _execution(db, user=user, workflow_id="wf_add_appr", execution_id="exec_add_appr")
    db.commit()

    request = ApprovalRequest(
        run_id="exec_add_appr",
        node_id="gate",
        reason="Staged request",
        status="pending",
    )
    statements = _capture_statements(
        db, lambda: ApprovalRepository(db).add(request)
    )
    assert statements == []
    assert sa_inspect(request).pending is True

    db.flush()
    assert request.id is not None
    assert sa_inspect(request).persistent is True
    assert db.get(ApprovalRequest, request.id) is request


def test_fresh_session_sees_only_committed_rows(db: Session) -> None:
    """The repository never commits; the caller owns the transaction."""
    user = _user(db)
    _workflow(db, user, "wf_txn_appr")
    _execution(db, user=user, workflow_id="wf_txn_appr", execution_id="exec_txn_appr")
    _approval(db, run_id="exec_txn_appr", request_id="appr_txn")
    db.commit()

    request = ApprovalRequest(
        run_id="exec_txn_appr",
        node_id="gate",
        reason="Uncommitted",
        status="pending",
    )
    ApprovalRepository(db).add(request)
    db.flush()

    with get_session() as fresh:
        assert ApprovalRepository(fresh).get("appr_txn") is not None
        assert ApprovalRepository(fresh).get(request.id) is None
