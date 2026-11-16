"""Execution read model: scoped, filtered, searchable execution history.

The SQL here is the single home for execution-list queries. It is a pure
persistence seam: no HTTP exceptions, no commits, no flushes. Callers pass
the workflow ids they are allowed to see and translate bad input themselves.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, and_, cast, func, or_, select
from sqlalchemy.orm import Session, defer

from app.models import Execution, User
from app.models.monitoring_telemetry import (
    ApiRequestTelemetry,
    ExecutionRetryHistory,
    ExecutionStep,
)
from app.models.workflow import WorkflowRecord
from app.services.telemetry_service import parse_datetime_query

logger = logging.getLogger("repositories.executions")

STATUS_FILTER_GROUPS: dict[str, tuple[str, ...]] = {
    "failed": ("failed", "error", "timeout"),
    "running": ("running", "queued", "waiting_approval", "waiting_auth"),
    "cancelled": ("cancelled", "cancelling"),
}

SORT_COLUMNS = {
    "started_at": Execution.started_at,
    "duration_ms": Execution.duration_ms,
    "records_processed": Execution.records_processed,
    "status": Execution.status,
    "id": Execution.id,
}


@dataclass(frozen=True, slots=True)
class ExecutionFilters:
    """Filters accepted by the execution list endpoint.

    Dates are parsed by the API layer so the repository stays free of HTTP
    error handling; both bounds are inclusive (``>=`` / ``<=``).
    """

    workflow_id: str | None = None
    status: str | None = None
    connector: str | None = None
    source_object: str | None = None
    destination_object: str | None = None
    http_status: int | None = None
    error_type: str | None = None
    trigger: str | None = None
    search: str | None = None
    include_children: bool = False
    started_after: datetime | None = None
    started_before: datetime | None = None


class ExecutionRepository:
    """Read queries for ``Execution`` rows."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, execution_id: str) -> Execution | None:
        """Load one execution by id, including its snapshot/trace columns."""
        return self._db.get(Execution, execution_id)

    def count_error_types(
        self, workflow_ids: Iterable[str]
    ) -> list[tuple[str, int]]:
        """Observed error categories, most frequent first, scoped to workflows."""
        ids = list(workflow_ids)
        if not ids:
            return []

        rows = self._db.execute(
            select(Execution.error_type, func.count(Execution.id))
            .where(
                Execution.workflow_id.in_(ids),
                Execution.error_type.is_not(None),
            )
            .group_by(Execution.error_type)
            .order_by(func.count(Execution.id).desc(), Execution.error_type.asc())
        ).all()
        return [
            (str(error_type), int(count))
            for error_type, count in rows
            if error_type
        ]

    def list_steps(self, execution_id: str) -> list[ExecutionStep]:
        """Structured step telemetry for one execution, in DAG order."""
        return list(
            self._db.scalars(
                select(ExecutionStep)
                .where(ExecutionStep.execution_id == execution_id)
                .order_by(ExecutionStep.sequence_number.asc())
            ).all()
        )

    def _api_requests_statement(
        self, execution_id: str
    ) -> Select[tuple[ApiRequestTelemetry]]:
        """Lightweight API-call rows (payload columns stay deferred)."""
        return (
            select(ApiRequestTelemetry)
            .options(
                defer(ApiRequestTelemetry.request_payload),
                defer(ApiRequestTelemetry.response_payload),
            )
            .where(ApiRequestTelemetry.execution_id == execution_id)
        )

    def list_api_requests(
        self,
        execution_id: str,
        *,
        page: int,
        page_size: int,
        focus_request_id: str | None = None,
    ) -> tuple[list[ApiRequestTelemetry], int, int]:
        """Return one lightweight page, the total, and the effective page.

        ``focus_request_id`` keeps the API inspector's deep-link semantics:
        when the referenced row exists, the returned page is the one that
        contains it, using the same ``created_at, id`` ordering as the list.
        """
        total = (
            self._db.scalar(
                select(func.count(ApiRequestTelemetry.id)).where(
                    ApiRequestTelemetry.execution_id == execution_id
                )
            )
            or 0
        )

        effective_page = page
        if focus_request_id:
            target = self.get_api_request(execution_id, focus_request_id)
            if target is not None:
                preceding = (
                    self._db.scalar(
                        select(func.count(ApiRequestTelemetry.id)).where(
                            ApiRequestTelemetry.execution_id == execution_id,
                            or_(
                                ApiRequestTelemetry.created_at < target.created_at,
                                and_(
                                    ApiRequestTelemetry.created_at
                                    == target.created_at,
                                    ApiRequestTelemetry.id < target.id,
                                ),
                            ),
                        )
                    )
                    or 0
                )
                effective_page = (preceding // page_size) + 1

        rows = self._db.scalars(
            self._api_requests_statement(execution_id)
            .order_by(
                ApiRequestTelemetry.created_at.asc(),
                ApiRequestTelemetry.id.asc(),
            )
            .offset((effective_page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), int(total), effective_page

    def list_api_calls(self, execution_id: str) -> list[ApiRequestTelemetry]:
        """All API-call rows for the timeline, oldest first (payload-free)."""
        return list(
            self._db.scalars(
                self._api_requests_statement(execution_id).order_by(
                    ApiRequestTelemetry.created_at.asc()
                )
            ).all()
        )

    def get_api_request(
        self, execution_id: str, request_id: str
    ) -> ApiRequestTelemetry | None:
        """Load the full request/response capture for one outbound call."""
        return self._db.scalar(
            select(ApiRequestTelemetry).where(
                ApiRequestTelemetry.execution_id == execution_id,
                ApiRequestTelemetry.id == request_id,
            )
        )

    def list_retries(self, execution_id: str) -> list[ExecutionRetryHistory]:
        """Retry attempts where the execution is either the original or retry."""
        return list(
            self._db.scalars(
                select(ExecutionRetryHistory)
                .where(
                    (ExecutionRetryHistory.original_execution_id == execution_id)
                    | (ExecutionRetryHistory.retry_execution_id == execution_id)
                )
                .order_by(ExecutionRetryHistory.attempt_number.asc())
            ).all()
        )

    def latest_for_workflow(self, workflow_id: str) -> Execution | None:
        """Most recent execution for a workflow (stable id tie-break)."""
        return self._db.scalar(
            select(Execution)
            .where(Execution.workflow_id == workflow_id)
            .order_by(Execution.started_at.desc(), Execution.id.desc())
            .limit(1)
        )

    def latest_with_results(
        self, workflow_id: str, *, limit: int = 5
    ) -> list[Execution]:
        """Newest executions that stored results, for upstream-context previews.

        JSON columns persist Python ``None`` as JSON ``null`` rather than SQL
        NULL on some dialects, so both spellings are excluded.
        """
        return list(
            self._db.scalars(
                select(Execution)
                .where(
                    Execution.workflow_id == workflow_id,
                    Execution.results.is_not(None),
                    cast(Execution.results, String) != "null",
                )
                .order_by(Execution.started_at.desc())
                .limit(limit)
            ).all()
        )

    def list_page(
        self,
        workflow_ids: Iterable[str],
        *,
        filters: ExecutionFilters | None = None,
        sort_by: str = "started_at",
        sort_dir: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Execution], int]:
        """Return one page plus the unpaginated total for the same filters."""
        ids = list(workflow_ids)
        if not ids:
            return [], 0

        active_filters = filters or ExecutionFilters()
        stmt = self._filtered_statement(ids, active_filters)

        total = self._db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0

        col = SORT_COLUMNS.get(sort_by, Execution.started_at)
        order_clause = col.asc() if sort_dir.lower() == "asc" else col.desc()
        page_stmt = (
            stmt.order_by(order_clause, Execution.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self._db.scalars(page_stmt).all()), int(total)

    def list_for_export(
        self,
        workflow_ids: Iterable[str],
        *,
        filters: ExecutionFilters | None = None,
        limit: int,
    ) -> list[Execution]:
        """Newest matching rows for CSV export, without the count query."""
        ids = list(workflow_ids)
        if not ids:
            return []

        active_filters = filters or ExecutionFilters()
        stmt = self._filtered_statement(ids, active_filters)
        return list(
            self._db.scalars(
                stmt.order_by(Execution.started_at.desc(), Execution.id.desc())
                .limit(limit)
            ).all()
        )

    def _filtered_statement(
        self,
        workflow_ids: Sequence[str],
        filters: ExecutionFilters,
    ) -> Select[tuple[Execution]]:
        stmt = self._apply_filters(self._base_statement(workflow_ids), filters)
        return self._apply_search(stmt, workflow_ids, filters)

    def _base_statement(self, workflow_ids: Sequence[str]) -> Select[tuple[Execution]]:
        """Execution rows scoped to accessible workflows, without heavy JSON."""
        return (
            select(Execution)
            .options(
                defer(Execution.trace),
                defer(Execution.results),
                defer(Execution.workflow_data),
                defer(Execution.node_statuses),
            )
            .where(Execution.workflow_id.in_(workflow_ids))
        )

    def _apply_filters(
        self,
        stmt: Select[tuple[Execution]],
        filters: ExecutionFilters,
    ) -> Select[tuple[Execution]]:
        if filters.workflow_id:
            stmt = stmt.where(Execution.workflow_id == filters.workflow_id)
        if filters.status:
            st_lower = filters.status.lower()
            status_group = STATUS_FILTER_GROUPS.get(st_lower)
            if status_group is not None:
                stmt = stmt.where(Execution.status.in_(status_group))
            elif st_lower in ("partial_success", "retrying", "success"):
                stmt = stmt.where(Execution.status == st_lower)
            else:
                stmt = stmt.where(Execution.status == filters.status)
        if filters.connector:
            conn_term = filters.connector.strip()
            stmt = stmt.where(
                (Execution.source_connector.icontains(conn_term, autoescape=True))
                | (Execution.destination_connector.icontains(conn_term, autoescape=True))
            )
        if filters.source_object:
            stmt = stmt.where(
                Execution.source_object.icontains(
                    filters.source_object.strip(), autoescape=True
                )
            )
        if filters.destination_object:
            stmt = stmt.where(
                Execution.destination_object.icontains(
                    filters.destination_object.strip(), autoescape=True
                )
            )
        if filters.http_status is not None:
            stmt = stmt.where(Execution.http_status_code == filters.http_status)
        if filters.error_type:
            stmt = stmt.where(Execution.error_type == filters.error_type)
        if filters.trigger:
            stmt = stmt.where(Execution.trigger == filters.trigger)
        if not filters.include_children and filters.trigger != "sub_workflow":
            # Child executions are checkpoints for a parent run, not
            # independently resumable runs; hide them from the default list.
            stmt = stmt.where(Execution.trigger != "sub_workflow")
        if filters.started_after is not None:
            stmt = stmt.where(Execution.started_at >= filters.started_after)
        if filters.started_before is not None:
            stmt = stmt.where(Execution.started_at <= filters.started_before)
        return stmt

    def _apply_search(
        self,
        stmt: Select[tuple[Execution]],
        workflow_ids: Sequence[str],
        filters: ExecutionFilters,
    ) -> Select[tuple[Execution]]:
        if not (filters.search and filters.search.strip()):
            return stmt

        term = filters.search.strip()
        parsed_dt = parse_datetime_query(term)
        date_win = parsed_dt.get("window") if parsed_dt else None
        dt_start, dt_end = date_win if date_win else (None, None)

        matching_wf_ids = self._matching_workflow_ids(workflow_ids, term)
        matching_user_ids = self._matching_user_ids(workflow_ids, term)
        matching_step_exec_ids = self._matching_step_execution_ids(
            workflow_ids, term, dt_start, dt_end
        )
        matching_req_exec_ids = self._matching_api_execution_ids(
            workflow_ids, term, dt_start, dt_end
        )
        matching_staged_exec_ids = self._matching_staged_execution_ids(
            workflow_ids, term, dt_start, dt_end
        )
        matching_err_exec_ids = self._matching_error_execution_ids(
            workflow_ids, term, dt_start, dt_end
        )

        predicates: list[Any] = [
            Execution.id.icontains(term, autoescape=True),
            Execution.source_connector.icontains(term, autoescape=True),
            Execution.destination_connector.icontains(term, autoescape=True),
            Execution.source_object.icontains(term, autoescape=True),
            Execution.destination_object.icontains(term, autoescape=True),
            Execution.trigger.icontains(term, autoescape=True),
            Execution.status.icontains(term, autoescape=True),
            Execution.api_endpoint.icontains(term, autoescape=True),
            Execution.http_method.icontains(term, autoescape=True),
            Execution.error_summary.icontains(term, autoescape=True),
            Execution.error_code.icontains(term, autoescape=True),
            Execution.error_type.icontains(term, autoescape=True),
            Execution.correlation_id.icontains(term, autoescape=True),
            Execution.parent_execution_id.icontains(term, autoescape=True),
            Execution.search_text.icontains(term, autoescape=True),
            cast(Execution.error, String).icontains(term, autoescape=True),
            cast(Execution.trigger_data, String).icontains(term, autoescape=True),
            cast(Execution.results, String).icontains(term, autoescape=True),
            cast(Execution.trace, String).icontains(term, autoescape=True),
            cast(Execution.workflow_data, String).icontains(term, autoescape=True),
        ]

        if dt_start and dt_end:
            predicates.append(Execution.started_at.between(dt_start, dt_end))
            predicates.append(Execution.finished_at.between(dt_start, dt_end))

        if term.isdigit() and len(term) == 3:
            try:
                predicates.append(Execution.http_status_code == int(term))
            except Exception:
                pass

        # Individual words support for multi-word search queries
        words = [w.strip() for w in term.split() if len(w.strip()) >= 2]
        if len(words) > 1:
            for word in words[:4]:
                predicates.append(Execution.search_text.icontains(word, autoescape=True))
                predicates.append(Execution.id.icontains(word, autoescape=True))
                predicates.append(Execution.status.icontains(word, autoescape=True))
                predicates.append(Execution.source_connector.icontains(word, autoescape=True))
                predicates.append(Execution.destination_connector.icontains(word, autoescape=True))
                predicates.append(Execution.error_summary.icontains(word, autoescape=True))

        if matching_wf_ids:
            predicates.append(Execution.workflow_id.in_(matching_wf_ids))
        if matching_user_ids:
            predicates.append(Execution.user_id.in_(matching_user_ids))
        if matching_step_exec_ids:
            predicates.append(Execution.id.in_(matching_step_exec_ids))
        if matching_req_exec_ids:
            predicates.append(Execution.id.in_(matching_req_exec_ids))
        if matching_staged_exec_ids:
            predicates.append(Execution.id.in_(matching_staged_exec_ids))
        if matching_err_exec_ids:
            predicates.append(Execution.id.in_(matching_err_exec_ids))

        return stmt.where(or_(*predicates))

    def _matching_workflow_ids(
        self, workflow_ids: Sequence[str], term: str
    ) -> list[str]:
        return [
            wid
            for (wid,) in self._db.execute(
                select(WorkflowRecord.id).where(
                    WorkflowRecord.id.in_(workflow_ids),
                    or_(
                        WorkflowRecord.name.icontains(term, autoescape=True),
                        WorkflowRecord.description.icontains(term, autoescape=True),
                    ),
                )
            ).all()
        ]

    def _matching_user_ids(
        self, workflow_ids: Sequence[str], term: str
    ) -> list[int]:
        return [
            uid
            for (uid,) in self._db.execute(
                select(User.id).where(
                    User.id.in_(
                        select(Execution.user_id).where(
                            Execution.workflow_id.in_(workflow_ids)
                        )
                    ),
                    User.email.icontains(term, autoescape=True),
                )
            ).all()
        ]

    def _matching_step_execution_ids(
        self,
        workflow_ids: Sequence[str],
        term: str,
        dt_start: datetime | None,
        dt_end: datetime | None,
    ) -> list[str]:
        step_preds = [
            ExecutionStep.step_name.icontains(term, autoescape=True),
            ExecutionStep.node_id.icontains(term, autoescape=True),
            ExecutionStep.node_type.icontains(term, autoescape=True),
            ExecutionStep.error_message.icontains(term, autoescape=True),
            cast(ExecutionStep.inputs, String).icontains(term, autoescape=True),
            cast(ExecutionStep.outputs, String).icontains(term, autoescape=True),
        ]
        if dt_start and dt_end:
            step_preds.append(ExecutionStep.started_at.between(dt_start, dt_end))
            step_preds.append(ExecutionStep.completed_at.between(dt_start, dt_end))

        return [
            eid
            for (eid,) in self._db.execute(
                select(ExecutionStep.execution_id)
                .join(Execution, ExecutionStep.execution_id == Execution.id)
                .where(
                    Execution.workflow_id.in_(workflow_ids),
                    or_(*step_preds),
                )
                .distinct()
                .limit(500)
            ).all()
        ]

    def _matching_api_execution_ids(
        self,
        workflow_ids: Sequence[str],
        term: str,
        dt_start: datetime | None,
        dt_end: datetime | None,
    ) -> list[str]:
        api_preds = [
            ApiRequestTelemetry.endpoint_url.icontains(term, autoescape=True),
            ApiRequestTelemetry.connector_name.icontains(term, autoescape=True),
            ApiRequestTelemetry.http_method.icontains(term, autoescape=True),
            ApiRequestTelemetry.error_message.icontains(term, autoescape=True),
            cast(ApiRequestTelemetry.request_payload, String).icontains(term, autoescape=True),
            cast(ApiRequestTelemetry.response_payload, String).icontains(term, autoescape=True),
            cast(ApiRequestTelemetry.request_headers, String).icontains(term, autoescape=True),
            cast(ApiRequestTelemetry.query_params, String).icontains(term, autoescape=True),
        ]
        if dt_start and dt_end:
            api_preds.append(
                ApiRequestTelemetry.created_at.between(dt_start, dt_end)
            )

        return [
            eid
            for (eid,) in self._db.execute(
                select(ApiRequestTelemetry.execution_id)
                .join(Execution, ApiRequestTelemetry.execution_id == Execution.id)
                .where(
                    Execution.workflow_id.in_(workflow_ids),
                    or_(*api_preds),
                )
                .distinct()
                .limit(500)
            ).all()
        ]

    def _matching_staged_execution_ids(
        self,
        workflow_ids: Sequence[str],
        term: str,
        dt_start: datetime | None,
        dt_end: datetime | None,
    ) -> list[str]:
        try:
            from app.models.staged_record import StagedContactRecord

            staged_preds = [
                StagedContactRecord.first_name.icontains(term, autoescape=True),
                StagedContactRecord.last_name.icontains(term, autoescape=True),
                StagedContactRecord.email.icontains(term, autoescape=True),
                StagedContactRecord.phone.icontains(term, autoescape=True),
                StagedContactRecord.department.icontains(term, autoescape=True),
                StagedContactRecord.title.icontains(term, autoescape=True),
                StagedContactRecord.status.icontains(term, autoescape=True),
                StagedContactRecord.mailing_street.icontains(term, autoescape=True),
                StagedContactRecord.mailing_city.icontains(term, autoescape=True),
                StagedContactRecord.mailing_state.icontains(term, autoescape=True),
                StagedContactRecord.mailing_postal_code.icontains(term, autoescape=True),
                StagedContactRecord.mailing_country.icontains(term, autoescape=True),
                StagedContactRecord.description.icontains(term, autoescape=True),
                StagedContactRecord.error_message.icontains(term, autoescape=True),
                StagedContactRecord.salesforce_id.icontains(term, autoescape=True),
                cast(StagedContactRecord.raw_data, String).icontains(term, autoescape=True),
            ]
            if dt_start and dt_end:
                staged_preds.append(
                    StagedContactRecord.created_at.between(dt_start, dt_end)
                )

            return [
                eid
                for (eid,) in self._db.execute(
                    select(StagedContactRecord.execution_id)
                    .join(
                        Execution,
                        StagedContactRecord.execution_id == Execution.id,
                    )
                    .where(
                        Execution.workflow_id.in_(workflow_ids),
                        or_(*staged_preds),
                    )
                    .distinct()
                    .limit(500)
                ).all()
            ]
        except Exception:
            logger.warning(
                "staged-record search subquery failed term=%r", term, exc_info=True
            )
            return []

    def _matching_error_execution_ids(
        self,
        workflow_ids: Sequence[str],
        term: str,
        dt_start: datetime | None,
        dt_end: datetime | None,
    ) -> list[str]:
        try:
            from app.models.error_event import ErrorEvent

            err_preds = [
                ErrorEvent.message.icontains(term, autoescape=True),
                ErrorEvent.title.icontains(term, autoescape=True),
                ErrorEvent.code.icontains(term, autoescape=True),
                ErrorEvent.category.icontains(term, autoescape=True),
                ErrorEvent.resolution.icontains(term, autoescape=True),
            ]
            if dt_start and dt_end:
                err_preds.append(ErrorEvent.created_at.between(dt_start, dt_end))

            return [
                eid
                for (eid,) in self._db.execute(
                    select(ErrorEvent.execution_id)
                    .join(Execution, ErrorEvent.execution_id == Execution.id)
                    .where(
                        Execution.workflow_id.in_(workflow_ids),
                        ErrorEvent.execution_id.isnot(None),
                        or_(*err_preds),
                    )
                    .distinct()
                    .limit(500)
                ).all()
            ]
        except Exception:
            logger.warning(
                "error-event search subquery failed term=%r", term, exc_info=True
            )
            return []
