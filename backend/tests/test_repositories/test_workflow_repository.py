"""WorkflowRepository read-core tests (no FastAPI, no TestClient)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    User,
    WorkflowRecord,
    WorkflowShare,
    WorkflowVersionRecord,
)
from app.repositories.workflows import WorkflowRepository


def _user(db: Session, email: str = "workflow-owner@example.com") -> User:
    user = User(email=email, password_hash="x", role="member", active=True)
    db.add(user)
    db.flush()
    return user


def _workflow(
    db: Session,
    user: User,
    workflow_id: str,
    *,
    name: str | None = None,
    updated_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> WorkflowRecord:
    rec = WorkflowRecord(
        id=workflow_id,
        user_id=user.id,
        name=name or workflow_id,
        description="",
        data={"id": workflow_id, "nodes": [], "connections": []},
        version=1,
        deleted_at=deleted_at,
    )
    if updated_at is not None:
        rec.updated_at = updated_at
    db.add(rec)
    db.flush()
    return rec


def _version(
    db: Session,
    user: User,
    workflow_id: str,
    version: int,
    *,
    version_id: str | None = None,
    name: str | None = None,
    created_at: datetime | None = None,
) -> WorkflowVersionRecord:
    rec = WorkflowVersionRecord(
        id=version_id or f"ver_{workflow_id}_{version}",
        workflow_id=workflow_id,
        version=version,
        data={
            "id": workflow_id,
            "name": name or f"{workflow_id} v{version}",
            "nodes": [{"id": "n1"}],
            "connections": [],
        },
        user_id=user.id,
        is_active=False,
    )
    if created_at is not None:
        rec.created_at = created_at
    db.add(rec)
    db.flush()
    return rec


def _share(
    db: Session, workflow_id: str, user: User, permission: str = "view"
) -> WorkflowShare:
    share = WorkflowShare(
        workflow_id=workflow_id, user_id=user.id, permission=permission
    )
    db.add(share)
    db.flush()
    return share


def _audit(
    db: Session,
    *,
    action: str,
    target_id: str,
    created_at: datetime,
    user: User | None = None,
    target_type: str = "workflow",
) -> AuditEvent:
    event_row = AuditEvent(
        user_id=user.id if user else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        created_at=created_at,
    )
    db.add(event_row)
    db.flush()
    return event_row


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


def test_get_returns_existing_missing_and_soft_deleted(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_get", name="Visible")
    _workflow(
        db,
        user,
        "wf_get_deleted",
        name="Deleted",
        deleted_at=datetime.now(UTC),
    )
    db.commit()

    repo = WorkflowRepository(db)
    rec = repo.get("wf_get")
    assert rec is not None
    assert rec.name == "Visible"
    assert repo.get("wf_missing") is None
    assert repo.get("wf_get_deleted") is None


def test_get_for_update_locks_the_row(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_lock")
    db.commit()

    repo = WorkflowRepository(db)
    statements = _capture_statements(db, lambda: repo.get("wf_lock", for_update=True))
    rec = repo.get("wf_lock", for_update=True)
    assert rec is not None
    assert rec.id == "wf_lock"
    assert any("FOR UPDATE" in statement.upper() for statement in statements)
    assert repo.get("wf_missing", for_update=True) is None


def test_get_populate_existing_refreshes_cached_columns(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_refresh", name="Before")
    db.commit()

    repo = WorkflowRepository(db)
    rec = repo.get("wf_refresh")
    assert rec is not None
    assert rec.name == "Before"

    # A concurrent writer bypasses this session's identity map.
    db.execute(
        update(WorkflowRecord)
        .where(WorkflowRecord.id == "wf_refresh")
        .values(name="After")
        .execution_options(synchronize_session=False)
    )
    db.commit()

    assert repo.get("wf_refresh").name == "Before"
    refreshed = repo.get(
        "wf_refresh", for_update=True, populate_existing=True
    )
    assert refreshed is not None
    assert refreshed.name == "After"


def test_list_page_scopes_orders_counts_and_paginates(db: Session) -> None:
    user = _user(db)
    other = _user(db, "other-owner@example.com")
    now = datetime.now(UTC)
    _workflow(
        db, user, "wf_page_old", updated_at=now - timedelta(hours=2)
    )
    _workflow(
        db, user, "wf_page_new", updated_at=now - timedelta(minutes=1)
    )
    _workflow(
        db, user, "wf_page_mid", updated_at=now - timedelta(hours=1)
    )
    _workflow(
        db, other, "wf_page_other", updated_at=now
    )
    db.commit()

    repo = WorkflowRepository(db)
    page, total = repo.list_page(
        ["wf_page_old", "wf_page_new", "wf_page_mid"], page=1, page_size=2
    )
    assert total == 3
    assert [rec.id for rec in page] == ["wf_page_new", "wf_page_mid"]

    second, second_total = repo.list_page(
        ["wf_page_old", "wf_page_new", "wf_page_mid"], page=2, page_size=2
    )
    assert second_total == 3
    assert [rec.id for rec in second] == ["wf_page_old"]

    assert repo.list_page([], page=1, page_size=10) == ([], 0)


def test_names_by_ids(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_name_a", name="Alpha")
    _workflow(db, user, "wf_name_b", name="Beta")
    db.commit()

    repo = WorkflowRepository(db)
    assert repo.names_by_ids(["wf_name_a", "wf_name_b"]) == {
        "wf_name_a": "Alpha",
        "wf_name_b": "Beta",
    }
    assert repo.names_by_ids(["wf_name_a", "wf_missing"]) == {"wf_name_a": "Alpha"}
    assert repo.names_by_ids([]) == {}


def test_list_versions_orders_and_scopes(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_versions")
    _workflow(db, user, "wf_versions_other")
    _version(db, user, "wf_versions", 1)
    _version(db, user, "wf_versions", 3)
    _version(db, user, "wf_versions", 2)
    _version(db, user, "wf_versions_other", 7)
    db.commit()

    repo = WorkflowRepository(db)
    assert [rec.version for rec in repo.list_versions("wf_versions")] == [3, 2, 1]
    assert [
        rec.version for rec in repo.list_versions("wf_versions_other")
    ] == [7]
    assert repo.list_versions("wf_missing") == []


def test_get_version_scopes_to_workflow(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_version_get")
    _workflow(db, user, "wf_version_get_other")
    _version(db, user, "wf_version_get", 2, version_id="ver_get_two")
    _version(db, user, "wf_version_get_other", 2, version_id="ver_other_two")
    db.commit()

    repo = WorkflowRepository(db)
    rec = repo.get_version("wf_version_get", 2)
    assert rec is not None
    assert rec.id == "ver_get_two"
    assert repo.get_version("wf_version_get", 1) is None
    assert repo.get_version("wf_version_get_other", 2).id == "ver_other_two"


def test_list_shares_and_get_share(db: Session) -> None:
    user = _user(db)
    first = _user(db, "share-first@example.com")
    second = _user(db, "share-second@example.com")
    _workflow(db, user, "wf_share")
    _workflow(db, user, "wf_share_other")
    _share(db, "wf_share", first, "view")
    _share(db, "wf_share", second, "edit")
    _share(db, "wf_share_other", first, "view")
    db.commit()

    repo = WorkflowRepository(db)
    shares = repo.list_shares("wf_share")
    assert {(share.user_id, share.permission) for share in shares} == {
        (first.id, "view"),
        (second.id, "edit"),
    }
    assert repo.list_shares("wf_missing") == []

    share = repo.get_share("wf_share", second.id)
    assert share is not None
    assert share.permission == "edit"
    assert repo.get_share("wf_share", user.id) is None
    assert repo.get_share("wf_share_other", second.id) is None


def test_list_activation_events_filters_and_orders(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_activation")
    now = datetime.now(UTC)
    _audit(
        db,
        action="workflow.activate",
        target_id="wf_activation",
        created_at=now - timedelta(minutes=3),
        user=user,
    )
    _audit(
        db,
        action="workflow.update",
        target_id="wf_activation",
        created_at=now - timedelta(minutes=2),
        user=user,
    )
    _audit(
        db,
        action="workflow.deactivate",
        target_id="wf_activation",
        created_at=now - timedelta(minutes=1),
        user=user,
    )
    _audit(
        db,
        action="workflow.activate",
        target_id="wf_other_target",
        created_at=now,
        user=user,
    )
    db.commit()

    events = WorkflowRepository(db).list_activation_events("wf_activation")
    assert [event.action for event in events] == [
        "workflow.deactivate",
        "workflow.activate",
    ]
    assert WorkflowRepository(db).list_activation_events("wf_missing") == []
