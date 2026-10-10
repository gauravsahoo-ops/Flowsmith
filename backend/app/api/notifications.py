"""Error Notifications and Alerts API endpoints.

Exposes notifications, error event lifecycle management (acknowledge/resolve),
user notification preferences, and test email sending.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.config import get_settings
from app.db import get_db
from app.models.error_event import ErrorEvent, NotificationPreference, NotificationRecord
from app.models.user import User

logger = logging.getLogger("api.notifications")

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class UpdatePreferencesRequest(BaseModel):
    email_enabled: bool | None = None
    notify_on_failure: bool | None = None
    notify_on_auth_expired: bool | None = None
    notify_on_rate_limit: bool | None = None
    notify_on_warning: bool | None = None
    cooldown_minutes: int | None = None
    custom_email: str | None = None


def _serialize_event(ev: ErrorEvent, include_tech: bool = False) -> dict[str, Any]:
    data = {
        "id": ev.id,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
        "severity": ev.severity,
        "category": ev.category,
        "code": ev.code,
        "title": ev.title,
        "message": ev.message,
        "resolution": ev.resolution,
        "workflow_id": ev.workflow_id,
        "workflow_name": ev.workflow_name,
        "execution_id": ev.execution_id,
        "node_id": ev.node_id,
        "node_name": ev.node_name,
        "connector_type": ev.connector_type,
        "credential_id": ev.credential_id,
        "attempt_number": ev.attempt_number,
        "retry_exhausted": ev.retry_exhausted,
        "status": ev.status,
        "trace_id": ev.trace_id,
        "acknowledged_at": ev.acknowledged_at.isoformat() if ev.acknowledged_at else None,
        "resolved_at": ev.resolved_at.isoformat() if ev.resolved_at else None,
    }
    if include_tech:
        data["technical_details"] = ev.technical_details
    return data


@router.get("")
def list_notifications(
    severity: str | None = None,
    category: str | None = None,
    workflow_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    resolved: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List error events relevant to current user with filtering."""
    query = select(ErrorEvent)

    # Multi-tenant and user isolation
    if user.role != "admin":
        query = query.where(
            (ErrorEvent.user_id == user.id)
            | (
                (ErrorEvent.workspace_id == user.workspace_id)
                & (ErrorEvent.workspace_id.isnot(None))
            )
        )

    if severity:
        query = query.where(ErrorEvent.severity == severity.upper())
    if category:
        query = query.where(ErrorEvent.category == category)
    if workflow_id:
        query = query.where(ErrorEvent.workflow_id == workflow_id)
    if status_filter:
        query = query.where(ErrorEvent.status == status_filter)
    if resolved is False:
        query = query.where(ErrorEvent.resolved_at.is_(None))
    elif resolved is True:
        query = query.where(ErrorEvent.resolved_at.isnot(None))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    events = db.scalars(query.order_by(desc(ErrorEvent.created_at)).offset(offset).limit(limit)).all()

    return ok({
        "total": total,
        "items": [_serialize_event(e) for e in events],
        "limit": limit,
        "offset": offset,
    })


@router.get("/stats")
def get_notification_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Summary counts for badges and dashboard widgets."""
    base_filter = [ErrorEvent.user_id == user.id] if user.role != "admin" else []

    unresolved_count = db.scalar(
        select(func.count(ErrorEvent.id)).where(
            *base_filter, ErrorEvent.resolved_at.is_(None)
        )
    ) or 0

    critical_count = db.scalar(
        select(func.count(ErrorEvent.id)).where(
            *base_filter,
            ErrorEvent.resolved_at.is_(None),
            ErrorEvent.severity == "CRITICAL",
        )
    ) or 0

    return ok({
        "unresolved_count": unresolved_count,
        "critical_count": critical_count,
    })


@router.get("/preferences")
def get_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve current user's notification preferences."""
    pref = db.get(NotificationPreference, user.id)
    if not pref:
        pref = NotificationPreference(user_id=user.id)
        db.add(pref)
        db.commit()
        db.refresh(pref)

    return ok({
        "email_enabled": pref.email_enabled,
        "notify_on_failure": pref.notify_on_failure,
        "notify_on_auth_expired": pref.notify_on_auth_expired,
        "notify_on_rate_limit": pref.notify_on_rate_limit,
        "notify_on_warning": pref.notify_on_warning,
        "cooldown_minutes": pref.cooldown_minutes,
        "custom_email": pref.custom_email,
        "default_email": user.email,
    })


@router.put("/preferences")
def update_preferences(
    req: UpdatePreferencesRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update notification preferences for current user."""
    pref = db.get(NotificationPreference, user.id)
    if not pref:
        pref = NotificationPreference(user_id=user.id)
        db.add(pref)

    if req.email_enabled is not None:
        pref.email_enabled = req.email_enabled
    if req.notify_on_failure is not None:
        pref.notify_on_failure = req.notify_on_failure
    if req.notify_on_auth_expired is not None:
        pref.notify_on_auth_expired = req.notify_on_auth_expired
    if req.notify_on_rate_limit is not None:
        pref.notify_on_rate_limit = req.notify_on_rate_limit
    if req.notify_on_warning is not None:
        pref.notify_on_warning = req.notify_on_warning
    if req.cooldown_minutes is not None:
        pref.cooldown_minutes = max(1, min(1440, req.cooldown_minutes))
    if req.custom_email is not None:
        pref.custom_email = req.custom_email.strip() or None

    pref.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pref)

    return ok({
        "email_enabled": pref.email_enabled,
        "notify_on_failure": pref.notify_on_failure,
        "notify_on_auth_expired": pref.notify_on_auth_expired,
        "notify_on_rate_limit": pref.notify_on_rate_limit,
        "notify_on_warning": pref.notify_on_warning,
        "cooldown_minutes": pref.cooldown_minutes,
        "custom_email": pref.custom_email,
        "default_email": user.email,
    })


def _can_access_event(user: User, ev: ErrorEvent) -> bool:
    if user.role == "admin":
        return True
    if ev.user_id is not None and ev.user_id == user.id:
        return True
    if user.workspace_id and ev.workspace_id and ev.workspace_id == user.workspace_id:
        return True
    return False


@router.get("/{event_id}")
def get_notification_detail(
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve full details of an error event."""
    ev = db.get(ErrorEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Error event not found")

    if not _can_access_event(user, ev):
        raise HTTPException(status_code=403, detail="Forbidden")

    deliveries = db.scalars(
        select(NotificationRecord)
        .where(NotificationRecord.error_event_id == event_id)
        .order_by(desc(NotificationRecord.created_at))
    ).all()

    delivery_items = [
        {
            "id": d.id,
            "recipient_email": d.recipient_email,
            "status": d.status,
            "attempts": d.attempts,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "sent_at": d.sent_at.isoformat() if d.sent_at else None,
        }
        for d in deliveries
    ]

    result = _serialize_event(ev, include_tech=True)
    result["deliveries"] = delivery_items
    return ok(result)


@router.post("/{event_id}/acknowledge")
def acknowledge_notification(
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark an error notification as acknowledged."""
    ev = db.get(ErrorEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Error event not found")

    if not _can_access_event(user, ev):
        raise HTTPException(status_code=403, detail="Forbidden")

    ev.status = "ACKNOWLEDGED"
    ev.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return ok({"id": ev.id, "status": ev.status, "acknowledged_at": ev.acknowledged_at.isoformat()})


@router.post("/{event_id}/resolve")
def resolve_notification(
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark an error notification as resolved."""
    ev = db.get(ErrorEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Error event not found")

    if not _can_access_event(user, ev):
        raise HTTPException(status_code=403, detail="Forbidden")

    ev.status = "RESOLVED"
    ev.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return ok({"id": ev.id, "status": ev.status, "resolved_at": ev.resolved_at.isoformat()})


@router.post("/test-email")
def send_test_email(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Send a verification test email to current user using SMTP settings."""
    settings = get_settings()
    pref = db.get(NotificationPreference, user.id)
    target_email = (pref and pref.custom_email) or user.email

    from app.services.error_monitoring import ErrorMonitoringService

    # Create a simulated test event
    test_event = ErrorMonitoringService.capture_error(
        db=db,
        error_data={
            "code": "TEST_ALERT_VERIFICATION",
            "message": "This is a test notification from Flowsmith to verify that email alert delivery is working properly.",
            "status_code": 200,
        },
        user_id=user.id,
    )

    is_configured = bool(settings.smtp_host and settings.mail_from)
    return ok({
        "success": True,
        "target_email": target_email,
        "smtp_configured": is_configured,
        "smtp_host": settings.smtp_host or "(unconfigured — simulated in dev mode)",
        "event_id": test_event.id if test_event else None,
        "message": (
            f"Test email dispatched to {target_email}. "
            + ("Delivered via SMTP." if is_configured else "Simulated in local environment (SMTP unconfigured).")
        ),
    })
