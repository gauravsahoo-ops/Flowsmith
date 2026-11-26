"""Audit log API, scoped to the signed-in user.

Every account sees only the security-relevant events it generated. Platform
system events (no user attribution) are not exposed through this per-user API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.db import get_db
from app.models import AuditEvent, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_events(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    action: str | None = None,
    user_id: int | None = None,
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    page, size = page_params(page=page, pageSize=pageSize)
    visibility = AuditEvent.user_id == user.id

    stmt = select(AuditEvent).where(visibility)
    count_stmt = select(func.count()).select_from(AuditEvent).where(visibility)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
        count_stmt = count_stmt.where(AuditEvent.action == action)
    if user_id is not None and user_id != user.id:
        # A different account's history is indistinguishable from no history.
        stmt = stmt.where(AuditEvent.id.is_(None))
        count_stmt = count_stmt.where(AuditEvent.id.is_(None))
    total = db.scalar(count_stmt) or 0
    events = db.scalars(
        stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ok(
        [
            {
                "id": e.id,
                "created_at": e.created_at,
                "user_id": e.user_id,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "detail": e.detail,
            }
            for e in events
        ],
        {"page": page, "pageSize": size, "total": total},
    )
