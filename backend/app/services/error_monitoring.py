"""Centralized Error Monitoring Service.

Captures, classifies, deduplicates, persists, and orchestrates email alerts
for workflow, credential, worker, and platform errors.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models.error_event import ErrorEvent, NotificationPreference, NotificationRecord
from app.models.execution import Execution
from app.models.user import User
from app.models.workflow import WorkflowRecord
from app.services.email_notifications import send_email_notification_sync
from app.services.error_classification import (
    classify_error,
    compute_fingerprint,
    sanitize_payload,
)

logger = logging.getLogger("monitoring.errors")

# Thread pool executor for non-blocking asynchronous email delivery
_NOTIFICATION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="err_notifier"
)


class ErrorMonitoringService:
    """Singleton service to capture and process error events."""

    @classmethod
    def capture_error(
        cls,
        db: Session | None,
        error_data: Any,
        user_id: int | None = None,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        node_id: str | None = None,
        node_name: str | None = None,
        connector_type: str | None = None,
        credential_id: str | None = None,
        attempt_number: int = 1,
        retry_exhausted: bool = True,
        trace_id: str | None = None,
    ) -> ErrorEvent | None:
        """Capture, classify, deduplicate, and record an error event.

        Schedules email notification if actionable and outside cooldown window.
        """
        settings = get_settings()
        if not settings.error_monitoring_enabled:
            return None

        # Resolve db session if not provided
        close_session = False
        if db is None:
            db = get_session()
            close_session = True

        try:
            # 1. Enrich workflow/user details if available
            wf_name: str | None = None
            org_id: str | None = None
            ws_id: str | None = None

            if workflow_id:
                wf_rec = db.get(WorkflowRecord, workflow_id)
                if wf_rec:
                    wf_name = wf_rec.name
                    ws_id = wf_rec.workspace_id
                    if not user_id:
                        user_id = wf_rec.user_id
                else:
                    wf_name = wf_name or workflow_id
                    workflow_id = None

            if execution_id:
                ex_rec = db.get(Execution, execution_id)
                if not ex_rec:
                    execution_id = None

            if user_id:
                u_rec = db.get(User, user_id)
                if u_rec:
                    org_id = u_rec.organization_id
                    ws_id = ws_id or u_rec.workspace_id
                else:
                    user_id = None

            # 2. Classify error
            classification = classify_error(
                error_data=error_data,
                workflow_name=wf_name,
                node_name=node_name,
                connector_type=connector_type,
            )

            # 3. Calculate fingerprint for deduplication
            fingerprint = compute_fingerprint(
                category=classification.category,
                code=classification.code,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
                connector_type=connector_type,
            )

            # 4. Check active cooldown window to prevent alert flooding
            cooldown_min = settings.error_notification_cooldown_minutes
            pref = db.get(NotificationPreference, user_id) if user_id else None
            if pref and pref.cooldown_minutes:
                cooldown_min = pref.cooldown_minutes

            now_utc = datetime.now(timezone.utc)
            cooldown_cutoff = now_utc - timedelta(minutes=cooldown_min)

            recent_event = db.scalars(
                select(ErrorEvent)
                .where(
                    ErrorEvent.fingerprint == fingerprint,
                    ErrorEvent.created_at >= cooldown_cutoff,
                )
                .order_by(ErrorEvent.created_at.desc())
            ).first()

            is_suppressed = False
            suppression_reason = None

            if recent_event:
                is_suppressed = True
                suppression_reason = "COOLDOWN_ACTIVE"
                logger.info(
                    "Error event [%s] suppressed by cooldown window (%d mins). Recent event: %s",
                    classification.code,
                    cooldown_min,
                    recent_event.id,
                )

            # 5. Check user notification preferences
            if not is_suppressed and pref and not pref.email_enabled:
                is_suppressed = True
                suppression_reason = "USER_DISABLED_EMAILS"

            if not is_suppressed and pref:
                if classification.severity == "WARNING" and not pref.notify_on_warning:
                    is_suppressed = True
                    suppression_reason = "USER_DISABLED_WARNINGS"
                elif classification.category == "CONNECTOR_RATE_LIMIT" and not pref.notify_on_rate_limit:
                    is_suppressed = True
                    suppression_reason = "USER_DISABLED_RATE_LIMIT_ALERTS"
                elif classification.category == "AUTH_SESSION_EXPIRED" and not pref.notify_on_auth_expired:
                    is_suppressed = True
                    suppression_reason = "USER_DISABLED_AUTH_ALERTS"

            # 6. Persist ErrorEvent row
            event_id = str(uuid.uuid4())
            event = ErrorEvent(
                id=event_id,
                created_at=now_utc,
                severity=classification.severity,
                category=classification.category,
                code=classification.code,
                title=classification.title,
                message=classification.message,
                resolution=classification.resolution,
                user_id=user_id,
                organization_id=org_id,
                workspace_id=ws_id,
                workflow_id=workflow_id,
                workflow_name=wf_name,
                execution_id=execution_id,
                node_id=node_id,
                node_name=node_name,
                connector_type=connector_type,
                credential_id=credential_id,
                attempt_number=attempt_number,
                retry_exhausted=retry_exhausted,
                technical_details=classification.technical_details,
                fingerprint=fingerprint,
                status="SUPPRESSED" if is_suppressed else "NOTIFICATION_PENDING",
                notification_attempts=0,
                trace_id=trace_id,
            )
            db.add(event)
            db.commit()

            # 7. Queue and dispatch email notification if not suppressed
            if not is_suppressed:
                recipient_email = None
                if pref and pref.custom_email:
                    recipient_email = pref.custom_email
                elif user_id:
                    user_row = db.get(User, user_id)
                    if user_row:
                        recipient_email = user_row.email

                # Fallback to admin email for infrastructure failures or if user email is missing
                if not recipient_email and (classification.category == "INFRASTRUCTURE_FAILURE" or not user_id):
                    recipient_email = settings.error_notification_admin_email or (
                        settings.mail_from if "@" in settings.mail_from else None
                    )

                if recipient_email:
                    idempotency_key = f"notif:{event_id}:{recipient_email}"
                    notif_record = NotificationRecord(
                        id=str(uuid.uuid4()),
                        error_event_id=event_id,
                        user_id=user_id,
                        recipient_email=recipient_email,
                        channel="email",
                        status="PENDING",
                        attempts=0,
                        idempotency_key=idempotency_key,
                        created_at=now_utc,
                    )
                    db.add(notif_record)
                    db.commit()

                    # Asynchronously dispatch email
                    _NOTIFICATION_EXECUTOR.submit(send_email_notification_sync, notif_record.id)
                else:
                    event.status = "SUPPRESSED"
                    db.commit()
                    logger.warning("No recipient email found for error event %s", event_id)

            return event
        except Exception as exc:
            logger.exception("ErrorMonitoringService failed while capturing error: %s", exc)
            return None
        finally:
            if close_session:
                db.close()

    @classmethod
    def capture_execution_error(
        cls,
        db: Session,
        execution_id: str,
        job: Any,
        error_data: Any,
        execution_rec: Execution | None = None,
    ) -> ErrorEvent | None:
        """Capture terminal workflow execution error."""
        try:
            workflow_id = None
            user_id = None
            wf_data = None
            failed_node_id = None
            failed_node_name = None
            connector_type = None

            if execution_rec:
                workflow_id = execution_rec.workflow_id
                user_id = execution_rec.user_id
                wf_data = execution_rec.workflow_data
            elif job:
                workflow_id = getattr(job, "workflow_id", None)
                user_id = getattr(job, "user_id", None)
                wf_data = getattr(job, "workflow_data", None)

            # Discover failed node from execution trace or node_statuses
            if execution_rec and execution_rec.node_statuses:
                for nid, st in execution_rec.node_statuses.items():
                    if st in ("failed", "error"):
                        failed_node_id = nid
                        break

            # Find node label and type
            if failed_node_id and wf_data and isinstance(wf_data, dict):
                nodes = wf_data.get("nodes") or []
                for n in nodes:
                    if n.get("id") == failed_node_id:
                        failed_node_name = (n.get("data") or {}).get("label") or n.get("label") or failed_node_id
                        connector_type = (n.get("data") or {}).get("nodeType") or n.get("type")
                        break

            # If error_data provides node info
            if isinstance(error_data, dict):
                failed_node_id = error_data.get("node_id") or failed_node_id
                failed_node_name = error_data.get("node_name") or failed_node_name

            return cls.capture_error(
                db=db,
                error_data=error_data,
                user_id=user_id,
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=failed_node_id,
                node_name=failed_node_name,
                connector_type=connector_type,
            )
        except Exception as exc:
            logger.exception("Failed to capture execution error for %s: %s", execution_id, exc)
            return None

    @classmethod
    def capture_credential_error(
        cls,
        user_id: int | None,
        credential_id: str,
        connector_type: str,
        error_message: str,
    ) -> ErrorEvent | None:
        """Capture external OAuth session expiry or credential revocation."""
        return cls.capture_error(
            db=None,
            error_data={
                "code": "AUTH_SESSION_EXPIRED",
                "message": error_message,
            },
            user_id=user_id,
            connector_type=connector_type,
            credential_id=credential_id,
        )
