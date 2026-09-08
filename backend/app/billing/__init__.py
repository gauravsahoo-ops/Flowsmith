"""Stripe client (Phase 34) — raw REST via SafeHTTPClient, zero new deps.

Implements exactly the three things the SaaS foundation needs:

1. Checkout Sessions (subscription mode) for plan upgrades,
2. webhook signature verification (Stripe's v1 HMAC-SHA256 scheme),
3. typed results so API errors stay readable.

Self-host mode: with ``STRIPE_SECRET_KEY`` unset, checkout raises
NOT_CONFIGURED and the rest of billing keeps working (plans/usage/limits
against the free plan).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.security.safe_http_client import get_safe_http_client

STRIPE_API_BASE = "https://api.stripe.com"
WEBHOOK_TOLERANCE_SECONDS = 300


@dataclass(frozen=True)
class StripeError(Exception):
    """Safe Stripe failure (never includes card/payment details)."""

    message: str
    status: int = 502

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.message


def stripe_configured() -> bool:
    return bool(get_settings().stripe_secret_key)


async def create_checkout_session(
    *,
    organization_id: str,
    organization_name: str,
    plan: str,
    price_month_cents: int,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    """Create a subscription-mode Checkout Session with inline price data.

    Returns {checkout_url, session_id}. Raises StripeError on failure.
    """
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise StripeError(
            "Billing is not configured on this server (STRIPE_SECRET_KEY missing).",
            status=422,
        )

    form = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": organization_id,
        "metadata[organization_id]": organization_id,
        "metadata[plan]": plan,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(price_month_cents),
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][price_data][product_data][name]": f"Flowsmith {plan.title()} — {organization_name}",
        "subscription_data[metadata][organization_id]": organization_id,
        "subscription_data[metadata][plan]": plan,
    }

    try:
        async with get_safe_http_client() as client:
            response = await client.request(
                "POST",
                f"{STRIPE_API_BASE}/v1/checkout/sessions",
                data=form,
                headers={
                    "Authorization": f"Bearer {settings.stripe_secret_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=30.0,
            )
    except Exception as exc:
        raise StripeError(f"Stripe unreachable: {exc}") from exc

    if response.status_code >= 400:
        detail = ""
        try:
            err = response.json()
            detail = str(err.get("error", {}).get("message", ""))[:300]
        except Exception:
            pass
        raise StripeError(detail or f"Stripe rejected the checkout ({response.status_code}).")

    try:
        data = response.json()
        return {"checkout_url": data["url"], "session_id": data["id"]}
    except Exception as exc:
        raise StripeError("Stripe returned a malformed checkout response.") from exc


def verify_webhook_signature(payload: bytes, sig_header: str, secret: str | None = None) -> bool:
    """Verify Stripe's v1 signature header (t=…,v1=…).

    Constant-time comparison; rejects replays older than the tolerance.
    """
    secret = secret or get_settings().stripe_webhook_secret
    if not secret or not payload or not sig_header:
        return False
    parts: dict[str, str] = {}
    for chunk in sig_header.split(","):
        k, _, v = chunk.strip().partition("=")
        parts[k] = v
    timestamp = parts.get("t", "")
    signature = parts.get("v1", "")
    if not timestamp or not signature:
        return False
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False
    if age > WEBHOOK_TOLERANCE_SECONDS:
        return False
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event(payload: bytes) -> dict[str, Any]:
    """Parse a verified webhook payload into a Stripe event dict."""
    try:
        event = json.loads(payload.decode())
    except Exception as exc:
        raise StripeError("Webhook payload is not valid JSON.") from exc
    if not isinstance(event, dict) or not event.get("type"):
        raise StripeError("Webhook payload is not a Stripe event.")
    return event
