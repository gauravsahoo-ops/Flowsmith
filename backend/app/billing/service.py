"""Billing service (Phase 34): subscriptions, plans, quota enforcement.

- Subscriptions are per-organization and created lazily (free default),
  so no migration/backfill is needed for existing orgs.
- Plan limits live in PLANS; ``enterprise`` is unlimited (-1).
- Enforcement resolves workflow -> workspace -> organization ->
  subscription and raises HTTP 402 with an upgrade hint when a quota is
  exhausted. Self-host deployments can disable checks with
  BILLING_ENFORCEMENT=false.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, Subscription, WorkflowRecord, Workspace

PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free",
        "max_executions_month": 100,
        "max_workflows": 5,
        "price_month": 0,
    },
    "starter": {
        "name": "Starter",
        "max_executions_month": 1000,
        "max_workflows": 25,
        "price_month": 2900,
    },
    "pro": {
        "name": "Professional",
        "max_executions_month": 10000,
        "max_workflows": 100,
        "price_month": 9900,
    },
    "enterprise": {
        "name": "Enterprise",
        "max_executions_month": -1,
        "max_workflows": -1,
        "price_month": 0,  # custom contract
    },
}

# Plans that can be purchased via Stripe checkout.
PURCHASABLE_PLANS = ("starter", "pro")


def get_or_create_subscription(db: Session, organization_id: str) -> Subscription:
    sub = db.scalars(
        select(Subscription).where(Subscription.organization_id == organization_id)
    ).first()
    if sub is None:
        sub = Subscription(organization_id=organization_id, plan="free", status="active")
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub


def resolve_organization_for_workspace(db: Session, workspace_id: str | None) -> Organization | None:
    if not workspace_id:
        return None
    ws = db.get(Workspace, workspace_id)
    if ws is None or not ws.organization_id:
        return None
    return db.get(Organization, ws.organization_id)


def plan_for_workspace(db: Session, workspace_id: str | None) -> tuple[str, dict[str, Any]]:
    """(plan_key, plan_def) for a workspace; free when unscoped/unknown."""
    org = resolve_organization_for_workspace(db, workspace_id)
    if org is None:
        return "free", PLANS["free"]
    sub = get_or_create_subscription(db, org.id)
    if sub.status == "canceled" or sub.plan not in PLANS:
        return "free", PLANS["free"]
    return sub.plan, PLANS[sub.plan]


def workspace_usage(db: Session, workspace_id: str) -> dict[str, int]:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    from app.models import Execution

    wf_ids = select(WorkflowRecord.id).where(WorkflowRecord.workspace_id == workspace_id)
    executions_month = db.execute(
        select(Execution.id).where(
            Execution.workflow_id.in_(wf_ids.scalar_subquery()),
            Execution.started_at >= month_start,
        )
    ).scalars().all()
    # Quota semantics (Phase 34): count ALL stored workflows of the
    # workspace (not just armed ones) - a plan buys storage for work.
    workflows_total = db.execute(
        select(WorkflowRecord.id).where(
            WorkflowRecord.workspace_id == workspace_id,
            WorkflowRecord.deleted_at.is_(None),
        )
    ).scalars().all()
    return {
        "executions_month": len(executions_month),
        "workflows_total": len(workflows_total),
    }


def check_within_limit(db: Session, workspace_id: str | None, limit_type: str) -> dict[str, Any]:
    """Limit check without raising — used by the check-limit endpoint."""
    plan_key, plan = plan_for_workspace(db, workspace_id)
    usage = workspace_usage(db, workspace_id) if workspace_id else {"executions_month": 0, "workflows_total": 0}
    current, max_limit = {
        "executions": (usage["executions_month"], plan["max_executions_month"]),
        "workflows": (usage["workflows_total"], plan["max_workflows"]),
    }.get(limit_type, (0, -1))
    within = max_limit == -1 or current < max_limit
    return {
        "limit_type": limit_type,
        "current": current,
        "max": max_limit,
        # Display name for UI + machine key for logic.
        "plan": plan["name"],
        "plan_key": plan_key,
        "within_limit": bool(within),
    }


def enforce_plan_limit(db: Session, workspace_id: str | None, limit_type: str) -> dict[str, Any] | None:
    """Raise HTTP 402 when the workspace's plan quota is exhausted.

    Returns the limit report when within limits. No-op entirely when
    BILLING_ENFORCEMENT=false (self-host mode).
    """
    from app.config import get_settings

    if not get_settings().billing_enforcement:
        return None
    report = check_within_limit(db, workspace_id, limit_type)
    if report["within_limit"]:
        return report
    raise HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"Plan limit reached: {report['current']}/{report['max']} {limit_type} "
            f"on the {report['plan']} plan. Upgrade to continue."
        ),
    )


def _apply_subscription_update(
    db: Session,
    sub: Subscription,
    *,
    plan: str | None = None,
    status: str | None = None,
    customer: str | None = None,
    stripe_sub: str | None = None,
    session_id: str | None = None,
    period_end: datetime | None = None,
) -> None:
    if plan is not None and plan in PLANS:
        sub.plan = plan
    if status is not None:
        sub.status = status
    if customer:
        sub.stripe_customer_id = str(customer)
    if stripe_sub:
        sub.stripe_subscription_id = str(stripe_sub)
    if session_id:
        sub.stripe_checkout_session_id = str(session_id)
    if period_end is not None:
        sub.current_period_end = period_end
    db.commit()


def apply_webhook_event(db: Session, event: dict[str, Any], *, applier=_apply_subscription_update) -> str:
    """Apply one verified Stripe event to the matching subscription.

    Returns the action taken ('activated'|'updated'|'canceled'|'ignored').
    """
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    def _org_id() -> str:
        # Checkout sessions carry client_reference_id / metadata;
        # subscription objects carry metadata only.
        return (
            obj.get("client_reference_id")
            or (obj.get("metadata") or {}).get("organization_id")
            or ""
        )

    if etype == "checkout.session.completed":
        org_id = _org_id()
        if not org_id:
            return "ignored"
        sub = get_or_create_subscription(db, org_id)
        applier(
            db, sub,
            plan=(obj.get("metadata") or {}).get("plan", sub.plan),
            status="active",
            customer=obj.get("customer") or "",
            stripe_sub=obj.get("subscription") or "",
            session_id=obj.get("id") or "",
        )
        return "activated"

    if etype == "customer.subscription.updated":
        org_id = _org_id()
        if not org_id:
            return "ignored"
        sub = get_or_create_subscription(db, org_id)
        statuses: dict[str | None, str] = {
            "active": "active", "trialing": "trialing", "past_due": "past_due", "canceled": "canceled",
        }
        period_end = obj.get("current_period_end")
        new_status = obj.get("status")
        applier(
            db, sub,
            plan=(obj.get("metadata") or {}).get("plan", sub.plan),
            status=statuses.get(new_status if isinstance(new_status, str) else None, sub.status),
            stripe_sub=obj.get("id") or sub.stripe_subscription_id,
            period_end=datetime.fromtimestamp(period_end, UTC) if period_end else None,
        )
        return "updated"

    if etype == "customer.subscription.deleted":
        org_id = _org_id()
        if not org_id:
            return "ignored"
        sub = get_or_create_subscription(db, org_id)
        applier(db, sub, plan="free", status="canceled")
        return "canceled"

    return "ignored"

