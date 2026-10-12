"""Recovery Notification Service.

Dispatches in-app incidents and formatted email notifications for
credential recovery events, upcoming expirations, and manual reauthorization actions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.connection_auth_policy import ConnectionAuthPolicy
from app.models.error_event import ErrorEvent, NotificationRecord
from app.models.user import User
from app.services.email_notifications import send_email_notification_sync

logger = logging.getLogger("auth.recovery_notifications")


class RecoveryNotificationService:
    """Delivers contextual notifications for credential and session recovery."""

    @classmethod
    def _create_notification(
        cls,
        db: Session,
        policy: ConnectionAuthPolicy,
        title: str,
        message: str,
        severity: str,
        category: str,
        resolution: str,
        send_email: bool = True,
    ) -> ErrorEvent | None:
        """Create an in-app error event and optionally dispatch email notification."""
        user = db.get(User, policy.user_id)
        if not user:
            return None

        settings = get_settings()
        now = datetime.now(UTC)
        event_id = str(uuid.uuid4())
        app_url = (settings.app_base_url or "http://localhost:5173").rstrip("/")
        cta_url = f"{app_url}/credentials"

        event = ErrorEvent(
            id=event_id,
            created_at=now,
            severity=severity,
            category=category,
            code=f"RECOVERY_{category}",
            title=title,
            message=message,
            resolution=resolution,
            user_id=user.id,
            organization_id=policy.organization_id,
            workspace_id=policy.workspace_id,
            credential_id=policy.credential_id,
            connector_type=policy.provider,
            fingerprint=f"rec_notif:{policy.credential_id}:{category}",
            status="NOTIFICATION_PENDING" if (send_email and policy.notify_email) else "DETECTED",
        )
        db.add(event)
        db.commit()

        if send_email and policy.notify_email and user.email:
            notif = NotificationRecord(
                id=str(uuid.uuid4()),
                error_event_id=event.id,
                user_id=user.id,
                recipient_email=user.email,
                channel="email",
                status="PENDING",
                attempts=0,
                idempotency_key=f"rec_email:{event.id}:{user.email}",
                created_at=now,
            )
            db.add(notif)
            db.commit()
            try:
                # Synchronously or via executor deliver email
                from app.services.error_monitoring import _NOTIFICATION_EXECUTOR
                _NOTIFICATION_EXECUTOR.submit(send_email_notification_sync, notif.id)
            except Exception:
                logger.exception("Failed to dispatch recovery notification email")

        return event

    @classmethod
    def notify_reauthorization_required(
        cls,
        db: Session,
        policy: ConnectionAuthPolicy,
        credential_name: str,
        reason: str = "Refresh token expired or revoked",
    ) -> None:
        cls._create_notification(
            db=db,
            policy=policy,
            title=f"Reconnection Required: {credential_name}",
            message=f"The connection to {credential_name} ({policy.provider}) requires interactive re-authorization. Reason: {reason}.",
            severity="ERROR",
            category="AUTH_SESSION_EXPIRED",
            resolution="Go to Credentials & Connections in Flowsmith and click 'Reconnect' to re-authorize the integration.",
            send_email=policy.notify_email,
        )

    @classmethod
    def notify_manual_action_required(
        cls,
        db: Session,
        policy: ConnectionAuthPolicy,
        credential_name: str,
    ) -> None:
        cls._create_notification(
            db=db,
            policy=policy,
            title=f"Manual Authentication Required: {credential_name}",
            message=f"Connection {credential_name} has expired or needs authentication. Manual recovery mode is active.",
            severity="WARNING",
            category="MANUAL_ACTION_REQUIRED",
            resolution="Click 'Reconnect' or 'Test Connection' on the integration card to renew credentials.",
            send_email=policy.notify_email,
        )

    @classmethod
    def notify_recovery_failed(
        cls,
        db: Session,
        policy: ConnectionAuthPolicy,
        credential_name: str,
        error_message: str,
    ) -> None:
        cls._create_notification(
            db=db,
            policy=policy,
            title=f"Automatic Recovery Failed: {credential_name}",
            message=f"Flowsmith attempted to automatically renew credentials for {credential_name}, but the provider rejected the request: {error_message}.",
            severity="ERROR",
            category="AUTHENTICATION_FAILED",
            resolution="Verify your integration account status or reconnect the credential.",
            send_email=policy.notify_on_recovery_failure,
        )

    @classmethod
    def notify_recovery_succeeded(
        cls,
        db: Session,
        policy: ConnectionAuthPolicy,
        credential_name: str,
    ) -> None:
        cls._create_notification(
            db=db,
            policy=policy,
            title=f"Connection Renewed: {credential_name}",
            message=f"Authentication for {credential_name} ({policy.provider}) was automatically refreshed in the background.",
            severity="INFO",
            category="AUTO_RECOVERY_SUCCESS",
            resolution="No action needed. Your workflows will continue executing seamlessly.",
            send_email=False,  # in-app notification only
        )
