"""Audit logging helper (security phase)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.metrics import audit_events
from app.models import AuditEvent

# Actions recorded by the audit log
REGISTER = "auth.register"
PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
PASSWORD_RESET = "auth.password_reset"
LOGIN = "auth.login"
LOGIN_FAILED = "auth.login_failed"
WORKFLOW_CREATE = "workflow.create"
WORKFLOW_UPDATE = "workflow.update"
WORKFLOW_DELETE = "workflow.delete"
WORKFLOW_ACTIVATE = "workflow.activate"
WORKFLOW_DEACTIVATE = "workflow.deactivate"
WORKFLOW_SHARE = "workflow.share"
WORKFLOW_UNSHARE = "workflow.unshare"
CREDENTIAL_CREATE = "credential.create"
CREDENTIAL_DELETE = "credential.delete"
SALESFORCE_CONNECT = "salesforce.connect"
SALESFORCE_CONNECT_FAILED = "salesforce.connect_failed"
SALESFORCE_TRIGGER_RECEIVED = "salesforce.trigger_received"
SALESFORCE_TRIGGER_REJECTED = "salesforce.trigger_rejected"
OAUTH_CONNECT = "oauth.connected"
OAUTH_CONNECT_FAILED = "oauth.connect_failed"
AI_GENERATE = "ai.generate"
AI_ASSIST = "ai.assist"
USER_ROLE_CHANGE = "user.role_change"
USER_STATE_CHANGE = "user.state_change"
EXECUTION_RUN = "execution.run"
EXECUTION_RETRY = "execution.retry"
EXECUTION_CANCEL = "execution.cancel"
EXECUTION_RESUME = "execution.resume"
WORKFLOW_TEST_CREATE = "workflow_test.create"
WORKFLOW_TEST_RUN = "workflow_test.run"
ADMIN_PRUNE = "admin.prune"


def log_event(
    db: Session,
    action: str,
    *,
    target_type: str = "",
    target_id: str = "",
    user_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record an event (commits immediately so it survives the caller's
    outcome; callers that already committed are unaffected)."""
    db.add(AuditEvent(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    ))
    db.commit()
    audit_events.inc()
