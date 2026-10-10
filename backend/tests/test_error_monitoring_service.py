"""Integration tests for ErrorMonitoringService and Notification APIs."""

import pytest
from sqlalchemy import select
from app.db import get_session
from app.models.error_event import ErrorEvent, NotificationPreference, NotificationRecord
from app.models.user import User
from app.services.error_monitoring import ErrorMonitoringService
from app.services.email_notifications import send_email_notification_sync


def _create_test_user(email: str = "testuser@example.com") -> User:
    with get_session() as db:
        user = User(
            email=email,
            password_hash="mockhash",
            role="member",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def test_capture_error_persists_event():
    user = _create_test_user("user1@example.com")
    with get_session() as db:
        event = ErrorMonitoringService.capture_error(
            db=db,
            error_data={"message": "Token refresh failed 401: unauthorized", "status_code": 401},
            user_id=user.id,
            connector_type="salesforce",
        )
        assert event is not None
        assert event.category == "AUTH_SESSION_EXPIRED"
        assert event.severity == "CRITICAL"
        assert "Salesforce" in event.title
        assert event.status in ("NOTIFICATION_PENDING", "NOTIFIED")
        assert event.user_id == user.id

        # Verify NotificationRecord was created
        notif = db.scalar(
            select(NotificationRecord).where(NotificationRecord.error_event_id == event.id)
        )
        assert notif is not None
        assert notif.recipient_email == "user1@example.com"
        assert notif.channel == "email"


def test_deduplication_and_cooldown_suppression():
    user = _create_test_user("user2@example.com")
    with get_session() as db:
        # First event
        ev1 = ErrorMonitoringService.capture_error(
            db=db,
            error_data={"message": "Rate limit exceeded", "status_code": 429},
            user_id=user.id,
            connector_type="dynamics_crm",
        )
        assert ev1 is not None
        assert ev1.status in ("NOTIFICATION_PENDING", "NOTIFIED")

        # Second identical event immediately after (cooldown active)
        ev2 = ErrorMonitoringService.capture_error(
            db=db,
            error_data={"message": "Rate limit exceeded", "status_code": 429},
            user_id=user.id,
            connector_type="dynamics_crm",
        )
        assert ev2 is not None
        assert ev2.status == "SUPPRESSED"
        assert ev2.fingerprint == ev1.fingerprint

        # Ensure no second notification record was queued
        records = db.scalars(
            select(NotificationRecord).where(NotificationRecord.error_event_id == ev2.id)
        ).all()
        assert len(records) == 0


def test_notification_preference_disables_emails():
    user = _create_test_user("user3@example.com")
    with get_session() as db:
        pref = NotificationPreference(user_id=user.id, email_enabled=False)
        db.add(pref)
        db.commit()

        ev = ErrorMonitoringService.capture_error(
            db=db,
            error_data={"message": "Failed node step"},
            user_id=user.id,
            node_name="HTTP Request",
        )
        assert ev is not None
        assert ev.status == "SUPPRESSED"

        records = db.scalars(
            select(NotificationRecord).where(NotificationRecord.error_event_id == ev.id)
        ).all()
        assert len(records) == 0


def test_send_email_notification_sync():
    user = _create_test_user("user4@example.com")
    with get_session() as db:
        ev = ErrorMonitoringService.capture_error(
            db=db,
            error_data={"message": "Expression syntax error in JSON transform"},
            user_id=user.id,
            node_name="Transform Data",
        )
        notif = db.scalar(
            select(NotificationRecord).where(NotificationRecord.error_event_id == ev.id)
        )
        assert notif is not None

        # Execute delivery
        success = send_email_notification_sync(notif.id)
        assert success is True

        db.refresh(notif)
        db.refresh(ev)
        assert notif.status == "SENT"
        assert notif.sent_at is not None
        assert ev.status == "NOTIFIED"
