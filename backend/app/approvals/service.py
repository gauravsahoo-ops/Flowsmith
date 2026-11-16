"""Durable approval request service.

The service is independent of FastAPI. Route handlers translate its typed
errors into HTTP responses; workers can use the same functions when a tool or
node pauses for approval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.redact import redact_sensitive
from app.metrics import approval_decisions, approval_requests
from app.models import ApprovalRequest
from app.platform.events import (
    APPROVAL_DECIDED,
    APPROVAL_REQUESTED,
    new_event,
)
from app.platform.outbox import record_event


class ApprovalError(ValueError):
    code = "APPROVAL_ERROR"
    http_status = 400

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ApprovalNotFound(ApprovalError):
    code = "APPROVAL_NOT_FOUND"
    http_status = 404


class ApprovalConflict(ApprovalError):
    code = "APPROVAL_CONFLICT"
    http_status = 409


class ApprovalForbidden(ApprovalError):
    code = "APPROVAL_FORBIDDEN"
    http_status = 403


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_request(
    db: Session,
    *,
    run_id: str,
    node_id: str,
    reason: str,
    summary: str = "",
    tool_name: str | None = None,
    risk_tier: int = 0,
    arguments: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
    affected_resources: list[Any] | None = None,
    requested_by: int | None = None,
    approvers: list[int] | None = None,
    quorum: int = 1,
    separation_of_duties: bool = True,
    ttl_seconds: int = 86_400,
    workflow_id: str | None = None,
    organization_id: str | None = None,
    workspace_id: str | None = None,
) -> ApprovalRequest:
    if not run_id or not node_id:
        raise ApprovalConflict("run_id and node_id are required")
    if quorum < 1:
        raise ApprovalConflict("quorum must be >= 1")
    now = datetime.now(UTC)
    request = ApprovalRequest(
        run_id=run_id,
        workflow_id=workflow_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        node_id=node_id,
        tool_name=tool_name,
        risk_tier=max(0, int(risk_tier)),
        reason=reason[:255],
        summary=summary,
        arguments=redact_sensitive(arguments or {}),
        preview=redact_sensitive(preview or {}),
        affected_resources=affected_resources or [],
        requested_by=requested_by,
        approvers=approvers or [],
        quorum=quorum,
        separation_of_duties=separation_of_duties,
        status="pending",
        expires_at=now + timedelta(seconds=max(1, ttl_seconds)),
    )
    db.add(request)
    db.flush()
    record_event(
        db,
        new_event(
            APPROVAL_REQUESTED,
            tenant_id=organization_id or "unknown",
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            correlation_id=run_id,
            payload={
                "approval_id": request.id,
                "risk_tier": request.risk_tier,
                "tool_name": tool_name,
                "status": "pending",
            },
        ),
        commit=False,
    )
    db.commit()
    db.refresh(request)
    approval_requests.inc((str(request.risk_tier),))
    return request


def get_request(db: Session, request_id: str) -> ApprovalRequest:
    request = db.get(ApprovalRequest, request_id)
    if request is None:
        raise ApprovalNotFound(f"Approval request {request_id} not found.")
    return request


def list_requests(
    db: Session,
    *,
    status: str | None = "pending",
    organization_id: str | None = None,
    workspace_id: str | None = None,
    limit: int = 50,
) -> list[ApprovalRequest]:
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    if organization_id:
        stmt = stmt.where(ApprovalRequest.organization_id == organization_id)
    if workspace_id:
        stmt = stmt.where(ApprovalRequest.workspace_id == workspace_id)
    return list(db.scalars(stmt.limit(max(1, min(limit, 200)))).all())


def decide(
    db: Session,
    request_id: str,
    *,
    user_id: int,
    approved: bool,
    nonce: str,
    comment: str = "",
) -> ApprovalRequest:
    if not nonce or len(nonce) > 128:
        raise ApprovalConflict("A decision nonce is required (max 128 characters).")

    request = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .with_for_update()
    )
    if request is None:
        raise ApprovalNotFound(f"Approval request {request_id} not found.")

    # Idempotent replay: the same signed decision may be retried safely.
    if request.status != "pending":
        if request.decision_nonce == nonce:
            return request
        raise ApprovalConflict(
            f"Approval request is already {request.status}.",
            code="APPROVAL_ALREADY_DECIDED",
        )

    now = datetime.now(UTC)
    expires_at = _utc(request.expires_at)
    if expires_at is not None and expires_at <= now:
        request.status = "expired"
        request.decision = {"reason": "expired"}
        db.commit()
        db.refresh(request)
        raise ApprovalConflict("Approval request has expired.", code="APPROVAL_EXPIRED")

    if request.separation_of_duties and request.requested_by == user_id:
        raise ApprovalForbidden(
            "The requester cannot approve their own request.",
            code="SEPARATION_OF_DUTIES",
        )

    approvers = request.approvers or []
    if approvers and user_id not in approvers:
        raise ApprovalForbidden(
            "The current user is not an approver for this request.",
            code="NOT_AN_APPROVER",
        )

    decision = dict(request.decision or {})
    decisions = list(decision.get("decisions") or [])
    if any(int(item.get("user_id", -1)) == user_id for item in decisions):
        raise ApprovalConflict(
            "This user has already decided this request.",
            code="ALREADY_DECIDED_BY_USER",
        )
    decisions.append(
        {
            "user_id": user_id,
            "approved": bool(approved),
            "comment": comment[:2000],
            "at": now.isoformat(),
        }
    )
    decision["decisions"] = decisions
    decision["latest"] = {"user_id": user_id, "approved": bool(approved), "comment": comment[:2000]}
    request.decision = decision
    request.decided_by = user_id
    request.decided_at = now
    request.decision_nonce = nonce

    if not approved:
        request.status = "rejected"
    else:
        approvals = [item for item in decisions if item.get("approved")]
        if len(approvals) >= max(1, request.quorum):
            request.status = "approved"

    db.flush()
    record_event(
        db,
        new_event(
            APPROVAL_DECIDED,
            tenant_id=request.organization_id or "unknown",
            workspace_id=request.workspace_id,
            run_id=request.run_id,
            node_id=request.node_id,
            correlation_id=request.run_id,
            payload={
                "approval_id": request.id,
                "status": request.status,
                "approved": bool(approved),
                "decided_by": user_id,
            },
        ),
        commit=False,
    )
    db.commit()
    db.refresh(request)
    approval_decisions.inc((request.status,))
    return request


def cancel(db: Session, request_id: str) -> ApprovalRequest:
    request = get_request(db, request_id)
    if request.status == "pending":
        request.status = "cancelled"
        request.decision = {"reason": "cancelled"}
        db.commit()
        db.refresh(request)
    return request


def expire_stale(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    rows = list(
        db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.status == "pending",
                ApprovalRequest.expires_at.isnot(None),
                ApprovalRequest.expires_at <= now,
            )
        ).all()
    )
    for request in rows:
        request.status = "expired"
        request.decision = {**(request.decision or {}), "reason": "expired"}
    if rows:
        db.commit()
    return len(rows)


def to_dict(request: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "run_id": request.run_id,
        "workflow_id": request.workflow_id,
        "organization_id": request.organization_id,
        "workspace_id": request.workspace_id,
        "node_id": request.node_id,
        "tool_name": request.tool_name,
        "risk_tier": request.risk_tier,
        "reason": request.reason,
        "summary": request.summary,
        "arguments": request.arguments or {},
        "preview": request.preview or {},
        "affected_resources": request.affected_resources or [],
        "requested_by": request.requested_by,
        "approvers": request.approvers or [],
        "quorum": request.quorum,
        "separation_of_duties": request.separation_of_duties,
        "status": request.status,
        "decision": request.decision or {},
        "decided_by": request.decided_by,
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "expires_at": request.expires_at.isoformat() if request.expires_at else None,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
    }
