"""Workflow read repository: records, versions, shares, activation events.

This module owns query construction for workflow reads. Permission checks,
HTTP 404 hiding, commits, flushes, and all write paths stay at the caller, so
the repository is a pure persistence seam.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import WORKFLOW_ACTIVATE, WORKFLOW_DEACTIVATE
from app.models import (
    AuditEvent,
    WorkflowRecord,
    WorkflowShare,
    WorkflowVersionRecord,
)


class WorkflowRepository:
    """Read queries for the workflow aggregate."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get(
        self,
        workflow_id: str,
        *,
        for_update: bool = False,
        populate_existing: bool = False,
    ) -> WorkflowRecord | None:
        """Load one non-deleted workflow record.

        Mirrors the row fetch behind ``access.get_workflow`` without the
        permission or 404 policy: missing and soft-deleted rows both return
        ``None``.
        """
        if not for_update and not populate_existing:
            rec = self._db.get(WorkflowRecord, workflow_id)
        else:
            stmt = select(WorkflowRecord).where(WorkflowRecord.id == workflow_id)
            if for_update:
                stmt = stmt.with_for_update()
            if populate_existing:
                stmt = stmt.execution_options(populate_existing=True)
            rec = self._db.scalar(stmt)
        if rec is None or rec.deleted_at is not None:
            return None
        return rec

    def list_page(
        self,
        workflow_ids: Iterable[str],
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[WorkflowRecord], int]:
        """Return one page plus the unpaginated total, newest update first."""
        ids = list(workflow_ids)
        if not ids:
            return [], 0

        total = (
            self._db.scalar(
                select(func.count())
                .select_from(WorkflowRecord)
                .where(WorkflowRecord.id.in_(ids))
            )
            or 0
        )
        recs = self._db.scalars(
            select(WorkflowRecord)
            .where(WorkflowRecord.id.in_(ids))
            .order_by(WorkflowRecord.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(recs), int(total)

    def names_by_ids(self, workflow_ids: Iterable[str]) -> dict[str, str]:
        """Map workflow ids to display names, skipping unknown ids."""
        ids = list(workflow_ids)
        if not ids:
            return {}
        rows = self._db.execute(
            select(WorkflowRecord.id, WorkflowRecord.name).where(
                WorkflowRecord.id.in_(ids)
            )
        ).all()
        return {str(workflow_id): str(name) for workflow_id, name in rows}

    def list_versions(self, workflow_id: str) -> list[WorkflowVersionRecord]:
        """Immutable snapshots for one workflow, newest version first."""
        return list(
            self._db.scalars(
                select(WorkflowVersionRecord)
                .where(WorkflowVersionRecord.workflow_id == workflow_id)
                .order_by(WorkflowVersionRecord.version.desc())
            ).all()
        )

    def get_version(
        self, workflow_id: str, version: int
    ) -> WorkflowVersionRecord | None:
        """Load one snapshot by workflow id and version number."""
        return self._db.scalar(
            select(WorkflowVersionRecord).where(
                WorkflowVersionRecord.workflow_id == workflow_id,
                WorkflowVersionRecord.version == version,
            )
        )

    def list_shares(self, workflow_id: str) -> list[WorkflowShare]:
        """Explicit shares for one workflow (no ordering contract)."""
        return list(
            self._db.scalars(
                select(WorkflowShare).where(
                    WorkflowShare.workflow_id == workflow_id
                )
            ).all()
        )

    def get_share(self, workflow_id: str, user_id: int) -> WorkflowShare | None:
        """Load one explicit workflow share."""
        return self._db.scalar(
            select(WorkflowShare).where(
                WorkflowShare.workflow_id == workflow_id,
                WorkflowShare.user_id == user_id,
            )
        )

    def list_activation_events(self, workflow_id: str) -> list[AuditEvent]:
        """Activation/deactivation audit rows, newest first."""
        return list(
            self._db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.target_id == workflow_id,
                    AuditEvent.action.in_(
                        [WORKFLOW_ACTIVATE, WORKFLOW_DEACTIVATE]
                    ),
                )
                .order_by(AuditEvent.created_at.desc())
            ).all()
        )
