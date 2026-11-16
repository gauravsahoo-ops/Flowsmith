"""Human approval inbox and decision API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.access import PERMISSION_EDIT, accessible_ids, get_permission
from app.api.auth import get_current_user
from app.api.common import ok
from app.approvals import service as approvals
from app.audit import log_event
from app.db import get_db
from app.models import ApprovalRequest, Execution, User
from app.repositories.approvals import ApprovalRepository

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecisionBody(BaseModel):
    approved: bool
    nonce: str = Field(min_length=8, max_length=128)
    comment: str = Field(default="", max_length=2000)


def _visible_request(db: Session, request_id: str, user: User) -> ApprovalRequest:
    request = ApprovalRepository(db).get(request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval request not found.")
    execution = db.get(Execution, request.run_id) if request.run_id else None
    if execution is not None and get_permission(db, execution.workflow_id, user) is not None:
        return request
    if request.requested_by == user.id:
        return request
    if user.id in (request.approvers or []):
        return request
    if getattr(user, "role", "") == "admin":
        return request
    # Do not reveal existence to unauthorized users.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval request not found.")


def _decidable_request(db: Session, request_id: str, user: User) -> ApprovalRequest:
    """Visibility is not approval authority.

    A view-only share may see a request, but only an editor, an explicitly
    listed approver, or an admin may record a decision. This prevents a
    read-only collaborator from approving a tool side effect.
    """
    request = _visible_request(db, request_id, user)
    execution = db.get(Execution, request.run_id) if request.run_id else None
    if user.id in (request.approvers or []):
        return request
    if getattr(user, "role", "") == "admin":
        return request
    if execution is not None:
        permission = get_permission(db, execution.workflow_id, user)
        if permission == PERMISSION_EDIT:
            return request
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You cannot decide this approval request."
    )


@router.get("")
def list_approvals(
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List approval requests for workflows the caller can access."""
    ids = accessible_ids(db, user)
    if not ids:
        return ok([])
    repo = ApprovalRepository(db)
    rows = repo.list_for_workflows(ids, status=status_filter, limit=limit)
    # Approvers may not have workflow access yet (they are invited to the
    # decision, not necessarily the workspace). Include requests where the
    # user is explicitly listed. Keep the scan bounded by status/limit.
    if status_filter:
        candidates = repo.list_recent(status=status_filter, limit=limit)
        seen = {row.id for row in rows}
        for row in candidates:
            if row.id not in seen and user.id in (row.approvers or []):
                rows.append(row)
    rows.sort(key=lambda row: row.created_at, reverse=True)
    return ok([approvals.to_dict(row) for row in rows[:limit]])


@router.get("/{request_id}")
def get_approval(
    request_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = _visible_request(db, request_id, user)
    return ok(approvals.to_dict(request))


@router.post("/{request_id}/decide")
def decide_approval(
    request_id: str,
    body: DecisionBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _decidable_request(db, request_id, user)
    try:
        request = approvals.decide(
            db,
            request_id,
            user_id=user.id,
            approved=body.approved,
            nonce=body.nonce,
            comment=body.comment,
        )
    except approvals.ApprovalError as exc:
        raise HTTPException(
            exc.http_status,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    log_event(
        db,
        "approval.decided",
        target_type="approval",
        target_id=request_id,
        user_id=user.id,
        detail={"status": request.status, "approved": body.approved},
    )
    return ok(approvals.to_dict(request))
