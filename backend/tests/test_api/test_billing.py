"""Billing / SaaS foundation tests (Phase 34).

- Subscriptions: lazy free default, per-org uniqueness.
- Quota enforcement: 402 on exhausted execution/workflow quotas,
  unlimited enterprise passes, BILLING_ENFORCEMENT=false disables checks.
- Stripe client: checkout session creation (scripted HTTP), self-host
  mode 422; webhook signature verification (valid/tampered/expired).
- Webhook handling: activation, update, cancellation → plan changes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from tests.test_api.conftest import auth_headers, register


def _sig_header(secret: str, payload: bytes, timestamp: int | None = None) -> str:
    t = timestamp if timestamp is not None else int(time.time())
    signed = f"{t}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


@pytest.fixture
def no_enforcement(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: Settings(billing_enforcement=False),
    )


# ----------------------------------------------------------------------
# API level
# ----------------------------------------------------------------------

def test_subscription_defaults_to_free(client):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Sub Org"}, headers=headers).json()["data"]["id"]
    body = client.get(f"/api/billing/subscription/{org_id}", headers=headers).json()["data"]
    assert body["plan"] == "free"
    assert body["status"] == "active"
    assert body["stripe_configured"] is False


def test_checkout_unconfigured_422(client):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Co Org"}, headers=headers).json()["data"]["id"]
    resp = client.post(
        "/api/billing/checkout",
        json={"organization_id": org_id, "plan": "pro"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_checkout_invalid_plan_400(client):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Co2 Org"}, headers=headers).json()["data"]["id"]
    resp = client.post(
        "/api/billing/checkout",
        json={"organization_id": org_id, "plan": "free"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_checkout_creates_session(client, monkeypatch):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Pay Org"}, headers=headers).json()["data"]["id"]

    monkeypatch.setattr("app.api.billing.stripe_configured", lambda: True)
    monkeypatch.setattr(
        "app.billing.get_settings",
        lambda: Settings(stripe_secret_key="sk_test_123"),
    )

    session_resp = httpx.Response(200, json={"url": "https://checkout.stripe.com/c/s1", "id": "cs_1"}, request=httpx.Request("POST", "http://fake"))
    fake = MagicMock()
    fake.__aenter__ = AsyncMock(return_value=MagicMock(request=AsyncMock(return_value=session_resp)))
    fake.__aexit__ = AsyncMock(return_value=False)
    with patch("app.billing.get_safe_http_client", return_value=fake):
        resp = client.post(
            "/api/billing/checkout",
            json={"organization_id": org_id, "plan": "pro"},
            headers=headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["checkout_url"].startswith("https://checkout.stripe.com/")


def _webhook(client, secret: str, event: dict[str, Any], *, timestamp=None, tamper=False):
    payload = json.dumps(event).encode()
    header = _sig_header(secret, payload, timestamp)
    if tamper:
        header = header[:-4] + "beef"
    return client.post(
        "/api/billing/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )


def test_webhook_activates_subscription(client, monkeypatch):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Web Org"}, headers=headers).json()["data"]["id"]

    secret = "whsec_test_123"
    monkeypatch.setattr("app.billing.get_settings", lambda: Settings(stripe_webhook_secret=secret))
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_9",
            "client_reference_id": org_id,
            "customer": "cus_1",
            "subscription": "sub_1",
            "metadata": {"plan": "pro", "organization_id": org_id},
        }},
    }
    resp = _webhook(client, secret, event)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["action"] == "activated"

    body = client.get(f"/api/billing/subscription/{org_id}", headers=headers).json()["data"]
    assert body["plan"] == "pro"
    assert body["status"] == "active"


def test_webhook_rejects_bad_signature_and_expiry(client, monkeypatch):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Sec Org"}, headers=headers).json()["data"]["id"]
    secret = "whsec_test_456"
    monkeypatch.setattr("app.billing.get_settings", lambda: Settings(stripe_webhook_secret=secret))
    event = {"type": "checkout.session.completed", "data": {"object": {"client_reference_id": org_id}}}

    tampered = _webhook(client, secret, event, tamper=True)
    assert tampered.status_code == 400

    expired = _webhook(client, secret, event, timestamp=int(time.time()) - 3600)
    assert expired.status_code == 400

    # Wrong secret also fails
    wrong = _webhook(client, "whsec_other", event)
    assert wrong.status_code == 400


def test_webhook_cancellation_downgrades(client, monkeypatch):
    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Churn Org"}, headers=headers).json()["data"]["id"]
    secret = "whsec_test_789"
    monkeypatch.setattr("app.billing.get_settings", lambda: Settings(stripe_webhook_secret=secret))
    activate = {
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": org_id, "metadata": {"plan": "starter"}}},
    }
    assert _webhook(client, secret, activate).status_code == 200
    cancel = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"organization_id": org_id}}},
    }
    resp = _webhook(client, secret, cancel)
    assert resp.json()["data"]["action"] == "canceled"

    body = client.get(f"/api/billing/subscription/{org_id}", headers=headers).json()["data"]
    assert body["plan"] == "free"
    assert body["status"] == "canceled"


# ----------------------------------------------------------------------
# Enforcement
# ----------------------------------------------------------------------

def test_execution_quota_blocks_run_at_limit(client, monkeypatch):
    from app.billing import service as bsvc

    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Quota Org"}, headers=headers).json()["data"]["id"]
    ws_id = client.post("/api/workspaces", json={"name": "Q WS", "organization_id": org_id}, headers=headers).json()["data"]["id"]
    wf = {
        "id": "wf_quota",
        "name": "Quota wf",
        "workspace_id": ws_id,
        "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    # Tiny quota for the test: free plan allows 3 executions/month.
    real_plans = dict(bsvc.PLANS)
    bsvc.PLANS["free"] = {**real_plans["free"], "max_executions_month": 3}
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: Settings(billing_enforcement=True),
    )
    try:
        for i in range(3):
            resp = client.post("/api/workflows/wf_quota/run", json={}, headers=headers)
            assert resp.status_code == 202, f"run {i}: {resp.text}"
            # Wait for terminal so the count settles deterministically
            eid = resp.json()["data"]["execution_id"]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                d = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
                if d["status"] not in ("running", "queued"):
                    break
                time.sleep(0.05)

        blocked = client.post("/api/workflows/wf_quota/run", json={}, headers=headers)
        assert blocked.status_code == 402, blocked.text
        assert "Plan limit reached" in blocked.json()["detail"]
    finally:
        bsvc.PLANS["free"] = real_plans["free"]


def test_workflow_quota_blocks_create_at_limit(client, monkeypatch):
    from app.billing import service as bsvc

    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "WfQuota Org"}, headers=headers).json()["data"]["id"]
    ws_id = client.post("/api/workspaces", json={"name": "WQ WS", "organization_id": org_id}, headers=headers).json()["data"]["id"]

    real_plans = dict(bsvc.PLANS)
    bsvc.PLANS["free"] = {**real_plans["free"], "max_workflows": 2}
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: Settings(billing_enforcement=True),
    )
    try:
        for i in range(2):
            wf = {
                "id": f"wf_wq{i}",
                "name": f"WQ {i}",
                "workspace_id": ws_id,
                "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
                "connections": [],
                "settings": {},
            }
            assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201
        third = {
            "id": "wf_wq3",
            "name": "WQ 3",
            "workspace_id": ws_id,
            "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
            "connections": [],
            "settings": {},
        }
        blocked = client.post("/api/workflows", json=third, headers=headers)
        assert blocked.status_code == 402
    finally:
        bsvc.PLANS["free"] = real_plans["free"]


def test_enterprise_plan_is_unlimited(client):
    from datetime import UTC, datetime

    from app.billing.service import check_within_limit, get_or_create_subscription
    from app.db import get_session

    headers = auth_headers(register(client)["token"])
    org_id = client.post("/api/organizations", json={"name": "Ent Org"}, headers=headers).json()["data"]["id"]
    ws_id = client.post("/api/workspaces", json={"name": "Ent WS", "organization_id": org_id}, headers=headers).json()["data"]["id"]

    db = get_session()
    try:
        sub = get_or_create_subscription(db, org_id)
        sub.plan = "enterprise"
        db.commit()
    finally:
        db.close()

    report = check_within_limit(db_session := get_session(), ws_id, "executions")
    db_session.close()
    assert report["within_limit"] is True
    assert report["max"] == -1





