"""Approval-request repository: scoped inbox and detail reads.

This is a persistence seam only. Callers (the API layer) keep visibility and
decision-authority policy, HTTP 404 hiding, and the transaction boundary; the
repository never commits, rolls back, flushes, or imports FastAPI.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, Execution


class ApprovalRepository:
    """Read queries for ``ApprovalRequest`` rows."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, request_id: str) -> ApprovalRequest | None:
        """Load one approval request by id."""
        return self._db.get(ApprovalRequest, request_id)

    def get_for_update(self, request_id: str) -> ApprovalRequest | None:
        """Load one request under a row lock (caller owns the transaction)."""
        return self._db.scalar(
            select(ApprovalRequest)
            .where(ApprovalRequest.id == request_id)
            .with_for_update()
        )

    def list_for_workflows(
        self,
        workflow_ids: Iterable[str],
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        """Requests whose run belongs to one of ``workflow_ids``.

        Newest first. An empty scope yields no rows rather than an unbounded
        query.
        """
        ids = list(workflow_ids)
        if not ids:
            return []

        stmt = (
            select(ApprovalRequest)
            .join(Execution, ApprovalRequest.run_id == Execution.id)
            .where(Execution.workflow_id.in_(ids))
            .order_by(ApprovalRequest.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        return list(self._db.scalars(stmt).all())

    def list_recent(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        """Recent requests across all workflows (bounded fallback scan).

        Approvers may be invited to a decision without workflow access, so the
        inbox needs a bounded global scan to find explicitly assigned rows.
        """
        stmt = (
            select(ApprovalRequest)
            .order_by(ApprovalRequest.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        return list(self._db.scalars(stmt).all())

    def list_pending_for_run(self, run_id: str) -> list[ApprovalRequest]:
        """Pending requests for one run, newest first."""
        return list(
            self._db.scalars(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.run_id == run_id,
                    ApprovalRequest.status == "pending",
                )
                .order_by(ApprovalRequest.created_at.desc())
            ).all()
        )

    def latest_for_run_node(
        self, run_id: str, node_id: str
    ) -> ApprovalRequest | None:
        """Most recent request for a run/node pair, whatever its status."""
        return self._db.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.run_id == run_id,
                ApprovalRequest.node_id == node_id,
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(1)
        )

    def add(self, request: ApprovalRequest) -> None:
        """Stage a new request; the caller controls flush and commit."""
        self._db.add(request)
