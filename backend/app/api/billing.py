"""Billing API (Phase 34): plans, usage, subscriptions, Stripe checkout,
and the signature-verified webhook.

Self-host mode (no STRIPE_SECRET_KEY): plans/usage/check-limit keep
working; checkout returns 422 and webhooks are rejected (signature
secret unset).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.billing import (
    StripeError,
    create_checkout_session,
    parse_event,
    stripe_configured,
    verify_webhook_signature,
)
from app.billing.service import (
    PLANS,
    PURCHASABLE_PLANS,
    apply_webhook_event,
    check_within_limit,
    get_or_create_subscription,
)
from app.config import get_settings
from app.db import get_db
from app.models import Organization, User

logger = logging.getLogger("billing")

router = APIRouter()


class CheckoutRequest(BaseModel):
    organization_id: str
    plan: str = Field(description="Purchasable plan: starter | pro")
    success_url: str = ""
    cancel_url: str = ""


def _require_org(db: Session, org_id: str, user: User) -> Organization:
    """Fetch the org; 404 hides existence from non-members (spec 28.1)."""
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    from sqlalchemy import select

    from app.models import OrganizationMember

    found = db.execute(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    return org


@router.get("/api/billing/plans")
def list_plans(user: User = Depends(get_current_user)) -> dict:
    """Available plans (prices in cents; enterprise is contract-based)."""
    return ok(PLANS)


@router.get("/api/billing/usage/{workspace_id}")
def get_usage(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    from app.billing.service import workspace_usage
    from app.api.workspaces import _require_ws_member

    _require_ws_member(db, workspace_id, user)
    return ok(workspace_usage(db, workspace_id))


@router.get("/api/billing/check-limit/{workspace_id}")
def check_limit(
    workspace_id: str,
    limit_type: str = "executions",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.api.workspaces import _require_ws_member

    _require_ws_member(db, workspace_id, user)
    return ok(check_within_limit(db, workspace_id, limit_type))


@router.get("/api/billing/subscription/{organization_id}")
def get_subscription(
    organization_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    org = _require_org(db, organization_id, user)
    sub = get_or_create_subscription(db, org.id)
    return ok({
        "organization_id": org.id,
        "plan": sub.plan,
        "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "stripe_configured": stripe_configured(),
    })


@router.post("/api/billing/checkout")
async def start_checkout(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if body.plan not in PURCHASABLE_PLANS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Plan must be one of {PURCHASABLE_PLANS}.")
    org = _require_org(db, body.organization_id, user)

    settings = get_settings()
    base = (settings.public_url or "").rstrip("/")
    success_url = body.success_url or f"{base}/?billing=success"
    cancel_url = body.cancel_url or f"{base}/?billing=cancelled"

    try:
        result = await create_checkout_session(
            organization_id=org.id,
            organization_name=org.name,
            plan=body.plan,
            price_month_cents=int(PLANS[body.plan]["price_month"]),
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except StripeError as exc:
        logger.error("stripe checkout failed for org %s: %s", org.id, exc)
        raise HTTPException(exc.status or 502, "Payment provider error.")

    from app.audit import log_event as _log

    _log(db, "billing.checkout_started", target_type="organization", target_id=org.id,
         user_id=user.id, detail={"plan": body.plan})
    return ok(result)


@router.post("/api/billing/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    if not verify_webhook_signature(payload, sig):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook signature.")
    event = parse_event(payload)
    action = apply_webhook_event(db, event)
    logger.info("billing webhook %s -> %s", event.get("type"), action)
    return ok({"received": True, "action": action})
