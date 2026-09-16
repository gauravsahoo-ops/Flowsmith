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
CREDENTIAL_RECONNECT = "credential.reconnect"
CREDENTIAL_SWEEP = "credential.auto_refresh_sweep"
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


def collect_sweep_audit(db: Session, sweep_id: str) -> dict[str, Any]:
    """Reassemble one credential sweep's audit pages (no hand-grouping).

    Lookup is a single indexed ``(action, target_id)`` equality query
    (``ix_audit_action_target``) — no table scan and no legacy fallback:
    every writer of ``credential.auto_refresh_sweep`` rows always sets
    ``target_id=f"credential-sweep:{sweep_id}"``.

    Returns {"sweep_id", "complete", "pages", "page_count", "user_ids",
    "user_count", "stats"}. ``complete`` is True only when every numbered
    page 1..N is present; ``user_ids`` is the concatenated owner list in
    page order and ``stats`` are the page-1 summary counts. Returns
    ``complete=False`` with empty lists when no page is found.
    """
    rows = db.query(AuditEvent).filter(
        AuditEvent.action == CREDENTIAL_SWEEP,
        AuditEvent.target_id == f"credential-sweep:{sweep_id}",
    ).all()
    pages: list[dict[str, Any]] = []
    for r in rows:
        detail: Any = getattr(r, "detail", None)
        if isinstance(detail, dict) and detail.get("sweep_id") == sweep_id:
            pages.append(detail)
    if not pages:
        return {
            "sweep_id": sweep_id,
            "complete": False,
            "pages": 0,
            "page_count": 0,
            "user_ids": [],
            "user_count": 0,
            "stats": {},
        }
    pages.sort(key=lambda d: int(d.get("page", 1)))
    first: dict[str, Any] = pages[0]
    expected = int(first.get("pages", len(pages)) or len(pages))
    page_numbers = [int(d.get("page", 0)) for d in pages]
    complete = (
        len(pages) == expected
        and page_numbers == list(range(1, expected + 1))
    )
    user_ids: list[int] = []
    for d in pages:
        ids = d.get("user_ids") or []
        user_ids.extend(int(i) for i in ids)
    stats = {
        k: first[k] for k in (
            "checked", "refreshed", "skipped", "failed",
            "skipped_locked", "skipped_deleted", "skipped_decrypt",
            "skipped_not_eligible", "skipped_unverified", "window_minutes",
        ) if k in first
    }
    return {
        "sweep_id": sweep_id,
        "complete": complete,
        "pages": expected,
        "page_count": len(pages),
        "user_ids": user_ids,
        "user_count": int(first.get("user_count", len(user_ids))),
        "stats": stats,
    }
