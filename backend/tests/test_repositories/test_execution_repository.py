"""ExecutionRepository read-core tests (no FastAPI, no TestClient)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.base import NO_VALUE

from app.db import get_session
from app.models import (
    ApiRequestTelemetry,
    Execution,
    ExecutionRetryHistory,
    ExecutionStep,
    User,
    WorkflowRecord,
)
from app.repositories import ExecutionFilters, ExecutionRepository


def _user(db: Session, email: str = "owner@example.com") -> User:
    user = User(email=email, password_hash="x", role="member", active=True)
    db.add(user)
    db.flush()
    return user


def _workflow(
    db: Session,
    user: User,
    workflow_id: str,
    *,
    name: str = "Repository Workflow",
    description: str = "",
) -> WorkflowRecord:
    rec = WorkflowRecord(
        id=workflow_id,
        user_id=user.id,
        name=name,
        description=description,
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
    **overrides: Any,
) -> Execution:
    values: dict[str, Any] = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "user_id": user.id,
        "workflow_version": 1,
        "workflow_data": {"id": workflow_id, "nodes": [], "connections": []},
        "trigger": "manual",
        "status": "success",
        "started_at": datetime.now(UTC),
    }
    values.update(overrides)
    rec = Execution(**values)
    db.add(rec)
    db.flush()
    return rec


def _count_selects(db: Session, action: Callable[[], object]) -> int:
    statements: list[str] = []

    def _listener(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _listener)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", _listener)
    return len(statements)


def test_get_returns_existing_and_missing(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_get")
    _execution(db, user=user, workflow_id="wf_get", execution_id="exec_get")
    db.commit()

    repo = ExecutionRepository(db)
    rec = repo.get("exec_get")
    assert rec is not None
    assert rec.id == "exec_get"
    assert repo.get("exec_missing") is None


def test_list_page_scopes_to_given_workflows(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_scope_a")
    _workflow(db, user, "wf_scope_b")
    _execution(db, user=user, workflow_id="wf_scope_a", execution_id="exec_scope_a")
    _execution(db, user=user, workflow_id="wf_scope_b", execution_id="exec_scope_b")
    db.commit()

    repo = ExecutionRepository(db)
    scoped, total = repo.list_page(["wf_scope_a"])
    assert total == 1
    assert [rec.id for rec in scoped] == ["exec_scope_a"]

    narrowed, narrowed_total = repo.list_page(
        ["wf_scope_a", "wf_scope_b"],
        filters=ExecutionFilters(workflow_id="wf_scope_b"),
    )
    assert narrowed_total == 1
    assert [rec.id for rec in narrowed] == ["exec_scope_b"]

    leaked, leaked_total = repo.list_page(
        ["wf_scope_a"],
        filters=ExecutionFilters(workflow_id="wf_scope_b"),
    )
    assert leaked == []
    assert leaked_total == 0


def test_total_is_unpaginated_while_page_is_limited(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_page")
    now = datetime.now(UTC)
    for index in range(5):
        _execution(
            db,
            user=user,
            workflow_id="wf_page",
            execution_id=f"exec_page_{index}",
            started_at=now - timedelta(minutes=index),
        )
    db.commit()

    recs, total = ExecutionRepository(db).list_page(
        ["wf_page"], page=2, page_size=2
    )
    assert total == 5
    assert len(recs) == 2


def test_status_alias_groups(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_status")
    statuses = (
        "failed",
        "error",
        "timeout",
        "success",
        "running",
        "queued",
        "waiting_approval",
        "waiting_auth",
        "cancelled",
        "cancelling",
    )
    for status in statuses:
        _execution(
            db,
            user=user,
            workflow_id="wf_status",
            execution_id=f"exec_status_{status}",
            status=status,
        )
    db.commit()

    repo = ExecutionRepository(db)

    def statuses_for(value: str) -> set[str]:
        rows, _ = repo.list_page(
            ["wf_status"],
            filters=ExecutionFilters(status=value),
            page_size=100,
        )
        return {row.status for row in rows}

    assert statuses_for("FAILED") == {"failed", "error", "timeout"}
    assert statuses_for("running") == {
        "running",
        "queued",
        "waiting_approval",
        "waiting_auth",
    }
    assert statuses_for("Cancelled") == {"cancelled", "cancelling"}
    assert statuses_for("success") == {"success"}


def test_connector_filter_matches_source_or_destination(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_conn")
    _execution(
        db,
        user=user,
        workflow_id="wf_conn",
        execution_id="exec_conn_source",
        source_connector="hubspot",
        destination_connector="salesforce",
    )
    _execution(
        db,
        user=user,
        workflow_id="wf_conn",
        execution_id="exec_conn_dest",
        source_connector="stripe",
        destination_connector="postgres",
    )
    _execution(
        db,
        user=user,
        workflow_id="wf_conn",
        execution_id="exec_conn_other",
        source_connector="hubspot",
        destination_connector="slack",
    )
    db.commit()

    repo = ExecutionRepository(db)

    def ids_for(term: str) -> set[str]:
        rows, _ = repo.list_page(
            ["wf_conn"],
            filters=ExecutionFilters(connector=term),
            page_size=100,
        )
        return {row.id for row in rows}

    assert ids_for("salesforce") == {"exec_conn_source"}
    assert ids_for("hubspot") == {"exec_conn_source", "exec_conn_other"}
    assert ids_for("HUBSPOT") == {"exec_conn_source", "exec_conn_other"}


def test_started_at_window_is_inclusive(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_dates")
    now = datetime.now(UTC)
    start = now - timedelta(hours=2)
    middle = now - timedelta(hours=1)
    end = now
    _execution(
        db, user=user, workflow_id="wf_dates", execution_id="exec_date_old",
        started_at=start,
    )
    _execution(
        db, user=user, workflow_id="wf_dates", execution_id="exec_date_mid",
        started_at=middle,
    )
    _execution(
        db, user=user, workflow_id="wf_dates", execution_id="exec_date_new",
        started_at=end,
    )
    db.commit()

    recs, total = ExecutionRepository(db).list_page(
        ["wf_dates"],
        filters=ExecutionFilters(started_after=start, started_before=middle),
        page_size=100,
    )
    assert total == 2
    assert {rec.id for rec in recs} == {"exec_date_old", "exec_date_mid"}


def test_search_matches_workflow_name(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_search_name", name="Acme Customer Sync")
    _workflow(db, user, "wf_search_other", name="Invoice Batch")
    _execution(
        db, user=user, workflow_id="wf_search_name", execution_id="exec_search_name"
    )
    _execution(
        db, user=user, workflow_id="wf_search_other", execution_id="exec_search_other"
    )
    db.commit()

    recs, total = ExecutionRepository(db).list_page(
        ["wf_search_name", "wf_search_other"],
        filters=ExecutionFilters(search="Acme"),
        page_size=100,
    )
    assert total == 1
    assert [rec.id for rec in recs] == ["exec_search_name"]


def test_search_matches_execution_step(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_search_step")
    _execution(
        db, user=user, workflow_id="wf_search_step", execution_id="exec_step_match"
    )
    _execution(
        db, user=user, workflow_id="wf_search_step", execution_id="exec_step_plain"
    )
    db.add(
        ExecutionStep(
            execution_id="exec_step_match",
            node_id="node_enrich",
            node_type="set_data",
            step_name="enrich_contact",
            started_at=datetime.now(UTC),
            inputs={"contact": "Ada"},
        )
    )
    db.commit()

    recs, total = ExecutionRepository(db).list_page(
        ["wf_search_step"],
        filters=ExecutionFilters(search="enrich_contact"),
        page_size=100,
    )
    assert total == 1
    assert [rec.id for rec in recs] == ["exec_step_match"]


def test_search_matches_api_telemetry(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_search_api")
    _execution(
        db, user=user, workflow_id="wf_search_api", execution_id="exec_api_match"
    )
    _execution(
        db, user=user, workflow_id="wf_search_api", execution_id="exec_api_plain"
    )
    now = datetime.now(UTC)
    db.add(
        ApiRequestTelemetry(
            execution_id="exec_api_match",
            http_method="POST",
            endpoint_url="https://api.example.com/v2/orders",
            connector_name="example",
            request_timestamp=now,
            created_at=now,
        )
    )
    db.commit()

    recs, total = ExecutionRepository(db).list_page(
        ["wf_search_api"],
        filters=ExecutionFilters(search="v2/orders"),
        page_size=100,
    )
    assert total == 1
    assert [rec.id for rec in recs] == ["exec_api_match"]


def test_sort_ties_are_broken_by_execution_id_desc(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_sort")
    started = datetime.now(UTC) - timedelta(minutes=10)
    _execution(
        db, user=user, workflow_id="wf_sort", execution_id="exec_sort_a",
        started_at=started, records_processed=1,
    )
    _execution(
        db, user=user, workflow_id="wf_sort", execution_id="exec_sort_b",
        started_at=started, records_processed=2,
    )
    _execution(
        db, user=user, workflow_id="wf_sort", execution_id="exec_sort_c",
        started_at=started, records_processed=2,
    )
    db.commit()

    recs, _ = ExecutionRepository(db).list_page(
        ["wf_sort"],
        sort_by="records_processed",
        sort_dir="desc",
        page_size=100,
    )
    assert [rec.id for rec in recs] == ["exec_sort_c", "exec_sort_b", "exec_sort_a"]


def test_unknown_sort_falls_back_to_started_at(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_sort_fallback")
    now = datetime.now(UTC)
    _execution(
        db, user=user, workflow_id="wf_sort_fallback", execution_id="exec_fallback_old",
        started_at=now - timedelta(hours=2),
    )
    _execution(
        db, user=user, workflow_id="wf_sort_fallback", execution_id="exec_fallback_mid",
        started_at=now - timedelta(hours=1),
    )
    _execution(
        db, user=user, workflow_id="wf_sort_fallback", execution_id="exec_fallback_new",
        started_at=now,
    )
    db.commit()

    repo = ExecutionRepository(db)
    desc, _ = repo.list_page(
        ["wf_sort_fallback"], sort_by="not_a_column", sort_dir="desc"
    )
    assert [rec.id for rec in desc] == [
        "exec_fallback_new",
        "exec_fallback_mid",
        "exec_fallback_old",
    ]

    asc, _ = repo.list_page(
        ["wf_sort_fallback"], sort_by="not_a_column", sort_dir="asc"
    )
    assert [rec.id for rec in asc] == [
        "exec_fallback_old",
        "exec_fallback_mid",
        "exec_fallback_new",
    ]


def test_heavy_columns_are_deferred_on_a_fresh_session(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_defer")
    _execution(
        db,
        user=user,
        workflow_id="wf_defer",
        execution_id="exec_defer",
        workflow_data={"id": "wf_defer", "nodes": [{"id": "n1"}], "connections": []},
        results={"outputs": {"n1": {"main": [{"ok": True}]}}},
        node_statuses={"n1": "success"},
        trace=[{"node_id": "n1", "status": "success"}],
    )
    db.commit()

    with get_session() as fresh:
        recs, total = ExecutionRepository(fresh).list_page(["wf_defer"])
        assert total == 1
        rec = recs[0]
        unloaded = sa_inspect(rec).unloaded
        assert {"trace", "results", "workflow_data", "node_statuses"} <= unloaded
        assert rec.__dict__.get("trace", NO_VALUE) is NO_VALUE
        assert rec.__dict__.get("results", NO_VALUE) is NO_VALUE
        assert rec.__dict__.get("workflow_data", NO_VALUE) is NO_VALUE
        assert rec.__dict__.get("node_statuses", NO_VALUE) is NO_VALUE

        # The deferred values must still be loadable through the same session.
        assert rec.trace == [{"node_id": "n1", "status": "success"}]


def test_empty_workflow_ids_returns_empty_page(db: Session) -> None:
    recs, total = ExecutionRepository(db).list_page([])
    assert recs == []
    assert total == 0


def test_query_budget_without_search_is_two_selects(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_budget")
    _execution(db, user=user, workflow_id="wf_budget", execution_id="exec_budget")
    db.commit()

    with get_session() as fresh:
        count = _count_selects(
            fresh, lambda: ExecutionRepository(fresh).list_page(["wf_budget"])
        )
    assert count == 2


def test_query_budget_with_search_is_at_most_eight_selects(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_budget_search")
    _execution(
        db, user=user, workflow_id="wf_budget_search", execution_id="exec_budget_search"
    )
    db.commit()

    with get_session() as fresh:
        count = _count_selects(
            fresh,
            lambda: ExecutionRepository(fresh).list_page(
                ["wf_budget_search"],
                filters=ExecutionFilters(search="no-such-term-zzz"),
            ),
        )
    assert count <= 8


def test_count_error_types_is_scoped_and_ordered(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_err_scoped")
    _workflow(db, user, "wf_err_other")
    now = datetime.now(UTC)
    for index, error_type in enumerate(
        ("AUTH_ERROR", "AUTH_ERROR", "NETWORK_ERROR", "NETWORK_ERROR", "RATE_LIMIT")
    ):
        _execution(
            db,
            user=user,
            workflow_id="wf_err_scoped",
            execution_id=f"exec_err_{index}",
            status="failed",
            error_type=error_type,
            started_at=now - timedelta(minutes=index),
        )
    _execution(
        db,
        user=user,
        workflow_id="wf_err_other",
        execution_id="exec_err_other",
        status="failed",
        error_type="AUTH_ERROR",
    )
    _execution(
        db,
        user=user,
        workflow_id="wf_err_scoped",
        execution_id="exec_err_none",
        status="success",
        error_type=None,
    )
    db.commit()

    repo = ExecutionRepository(db)
    assert repo.count_error_types(["wf_err_scoped"]) == [
        ("AUTH_ERROR", 2),
        ("NETWORK_ERROR", 2),
        ("RATE_LIMIT", 1),
    ]
    assert repo.count_error_types(["wf_err_other"]) == [("AUTH_ERROR", 1)]
    assert repo.count_error_types([]) == []


def test_list_steps_orders_by_sequence_number(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_steps")
    _execution(db, user=user, workflow_id="wf_steps", execution_id="exec_steps")
    _execution(db, user=user, workflow_id="wf_steps", execution_id="exec_other_steps")
    now = datetime.now(UTC)
    db.add_all(
        [
            ExecutionStep(
                id="step_three",
                execution_id="exec_steps",
                node_id="n3",
                node_type="set_data",
                sequence_number=3,
                started_at=now,
            ),
            ExecutionStep(
                id="step_one",
                execution_id="exec_steps",
                node_id="n1",
                node_type="set_data",
                sequence_number=1,
                started_at=now,
            ),
            ExecutionStep(
                id="step_two",
                execution_id="exec_steps",
                node_id="n2",
                node_type="set_data",
                sequence_number=2,
                started_at=now,
            ),
            ExecutionStep(
                id="step_other",
                execution_id="exec_other_steps",
                node_id="other",
                node_type="set_data",
                sequence_number=0,
                started_at=now,
            ),
        ]
    )
    db.commit()

    steps = ExecutionRepository(db).list_steps("exec_steps")
    assert [step.id for step in steps] == ["step_one", "step_two", "step_three"]


def test_list_api_requests_pagination_and_focus_page(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_requests")
    _execution(db, user=user, workflow_id="wf_requests", execution_id="exec_requests")
    now = datetime.now(UTC)
    request_ids: list[str] = []
    for index in range(5):
        request = ApiRequestTelemetry(
            id=f"req_{index}",
            execution_id="exec_requests",
            http_method="GET",
            endpoint_url=f"https://api.example.com/v1/items/{index}",
            connector_name="example",
            request_timestamp=now + timedelta(seconds=index),
            created_at=now + timedelta(seconds=index),
            request_payload={"index": index},
            response_payload={"ok": True},
        )
        db.add(request)
        request_ids.append(request.id)
    db.commit()

    repo = ExecutionRepository(db)
    rows, total, page = repo.list_api_requests(
        "exec_requests", page=2, page_size=2
    )
    assert total == 5
    assert page == 2
    assert [row.id for row in rows] == request_ids[2:4]

    focused, focused_total, focused_page = repo.list_api_requests(
        "exec_requests",
        page=1,
        page_size=2,
        focus_request_id=request_ids[4],
    )
    assert focused_total == 5
    assert focused_page == 3
    assert [row.id for row in focused] == [request_ids[4]]

    missing_focus, _, missing_page = repo.list_api_requests(
        "exec_requests",
        page=1,
        page_size=2,
        focus_request_id="req_missing",
    )
    assert missing_page == 1
    assert [row.id for row in missing_focus] == request_ids[:2]


def test_api_request_payload_columns_are_deferred(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_requests_defer")
    _execution(
        db, user=user, workflow_id="wf_requests_defer", execution_id="exec_req_defer"
    )
    now = datetime.now(UTC)
    db.add(
        ApiRequestTelemetry(
            id="req_defer",
            execution_id="exec_req_defer",
            http_method="POST",
            endpoint_url="https://api.example.com/v1/items",
            connector_name="example",
            request_timestamp=now,
            created_at=now,
            request_payload={"secret": "payload"},
            response_payload={"ok": True},
        )
    )
    db.commit()

    with get_session() as fresh:
        rows, _, _ = ExecutionRepository(fresh).list_api_requests(
            "exec_req_defer", page=1, page_size=10
        )
        assert len(rows) == 1
        unloaded = sa_inspect(rows[0]).unloaded
        assert {"request_payload", "response_payload"} <= unloaded
        assert rows[0].request_payload == {"secret": "payload"}


def test_get_api_request_scopes_to_execution(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_request_detail")
    _execution(
        db, user=user, workflow_id="wf_request_detail", execution_id="exec_req_a"
    )
    _execution(
        db, user=user, workflow_id="wf_request_detail", execution_id="exec_req_b"
    )
    now = datetime.now(UTC)
    db.add(
        ApiRequestTelemetry(
            id="req_detail",
            execution_id="exec_req_a",
            http_method="GET",
            endpoint_url="https://api.example.com/v1/items/1",
            connector_name="example",
            request_timestamp=now,
            created_at=now,
        )
    )
    db.commit()

    repo = ExecutionRepository(db)
    req = repo.get_api_request("exec_req_a", "req_detail")
    assert req is not None
    assert req.id == "req_detail"
    assert repo.get_api_request("exec_req_b", "req_detail") is None
    assert repo.get_api_request("exec_req_a", "req_missing") is None


def test_list_retries_orders_by_attempt_number(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_retries")
    for execution_id in (
        "exec_retry_parent",
        "exec_retry_1",
        "exec_retry_2",
        "exec_retry_other",
    ):
        _execution(
            db, user=user, workflow_id="wf_retries", execution_id=execution_id
        )
    db.add_all(
        [
            ExecutionRetryHistory(
                id="retry_attempt_2",
                original_execution_id="exec_retry_parent",
                retry_execution_id="exec_retry_2",
                attempt_number=2,
                retry_trigger="manual",
                status="success",
            ),
            ExecutionRetryHistory(
                id="retry_attempt_1",
                original_execution_id="exec_retry_parent",
                retry_execution_id="exec_retry_1",
                attempt_number=1,
                retry_trigger="manual",
                status="failed",
            ),
            ExecutionRetryHistory(
                id="retry_attempt_3_as_retry",
                original_execution_id="exec_retry_other",
                retry_execution_id="exec_retry_parent",
                attempt_number=3,
                retry_trigger="manual",
                status="success",
            ),
            ExecutionRetryHistory(
                id="retry_unrelated",
                original_execution_id="exec_retry_other",
                retry_execution_id="exec_retry_other",
                attempt_number=9,
                retry_trigger="manual",
                status="success",
            ),
        ]
    )
    db.commit()

    rows = ExecutionRepository(db).list_retries("exec_retry_parent")
    assert [row.id for row in rows] == [
        "retry_attempt_1",
        "retry_attempt_2",
        "retry_attempt_3_as_retry",
    ]
    assert ExecutionRepository(db).list_retries("exec_retry_1")[0].id == "retry_attempt_1"


def test_latest_for_workflow_and_latest_with_results(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_latest")
    _workflow(db, user, "wf_latest_other")
    now = datetime.now(UTC)
    _execution(
        db,
        user=user,
        workflow_id="wf_latest",
        execution_id="exec_latest_results_old",
        results={"outputs": {"n1": {"main": [{"old": True}]}}},
        started_at=now - timedelta(hours=2),
    )
    _execution(
        db,
        user=user,
        workflow_id="wf_latest",
        execution_id="exec_latest_no_results",
        results=None,
        started_at=now,
    )
    _execution(
        db,
        user=user,
        workflow_id="wf_latest",
        execution_id="exec_latest_results_new",
        results={"outputs": {"n1": {"main": [{"new": True}]}}},
        started_at=now - timedelta(hours=1),
    )
    _execution(
        db,
        user=user,
        workflow_id="wf_latest_other",
        execution_id="exec_latest_other",
        results={"outputs": {"n1": {"main": [{"other": True}]}}},
        started_at=now,
    )
    db.commit()

    repo = ExecutionRepository(db)
    latest = repo.latest_for_workflow("wf_latest")
    assert latest is not None
    assert latest.id == "exec_latest_no_results"
    assert repo.latest_for_workflow("wf_missing") is None

    with_results = repo.latest_with_results("wf_latest")
    assert [rec.id for rec in with_results] == [
        "exec_latest_results_new",
        "exec_latest_results_old",
    ]
    limited = repo.latest_with_results("wf_latest", limit=1)
    assert [rec.id for rec in limited] == ["exec_latest_results_new"]
    assert repo.latest_with_results("wf_latest_other")[0].id == "exec_latest_other"


def test_list_for_export_orders_filters_and_limits(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_export")
    now = datetime.now(UTC)
    for index in range(3):
        _execution(
            db,
            user=user,
            workflow_id="wf_export",
            execution_id=f"exec_export_{index}",
            status="failed" if index == 0 else "success",
            started_at=now - timedelta(minutes=index),
        )
    db.commit()

    repo = ExecutionRepository(db)
    rows = repo.list_for_export(["wf_export"], limit=2)
    assert [rec.id for rec in rows] == ["exec_export_0", "exec_export_1"]

    filtered = repo.list_for_export(
        ["wf_export"],
        filters=ExecutionFilters(status="failed"),
        limit=10,
    )
    assert [rec.id for rec in filtered] == ["exec_export_0"]
    assert repo.list_for_export([], limit=10) == []


def test_list_for_export_is_one_select(db: Session) -> None:
    user = _user(db)
    _workflow(db, user, "wf_export_budget")
    _execution(
        db,
        user=user,
        workflow_id="wf_export_budget",
        execution_id="exec_export_budget",
    )
    db.commit()

    with get_session() as fresh:
        count = _count_selects(
            fresh,
            lambda: ExecutionRepository(fresh).list_for_export(
                ["wf_export_budget"], limit=10
            ),
        )
    assert count == 1
