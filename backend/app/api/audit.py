"""Audit log API (security phase): admins can browse security-relevant
events with filtering and pagination.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ok, page_params
from app.api.users import get_current_admin
from app.db import get_db
from app.models import AuditEvent

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_events(
    _: object = Depends(get_current_admin),
    db: Session = Depends(get_db),
    action: str | None = None,
    user_id: int | None = None,
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    page, size = page_params(page=page, pageSize=pageSize)
    stmt = select(AuditEvent)
    count_stmt = select(func.count()).select_from(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
        count_stmt = count_stmt.where(AuditEvent.action == action)
    if user_id is not None:
        stmt = stmt.where(AuditEvent.user_id == user_id)
        count_stmt = count_stmt.where(AuditEvent.user_id == user_id)
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
