"""Provider-specific inbound webhook trigger tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from tests.test_api.conftest import auth_headers, register


def _setup(client):
    user = register(client)
    return auth_headers(user["token"])


def _activate(client, headers, node_type: str, path: str, secret: str):
    workflow = {
        "id": f"wf_{path}",
        "name": f"{node_type} workflow",
        "nodes": [{
            "id": "trigger",
            "type": node_type,
            "parameters": {"path": path, "method": "POST", "secret": secret},
        }],
        "connections": [],
        "settings": {},
    }
    created = client.post("/api/workflows", json=workflow, headers=headers)
    assert created.status_code == 201, created.text
    activated = client.patch(
        f"/api/workflows/wf_{path}/active", json={"active": True}, headers=headers
    )
    assert activated.status_code == 200, activated.text


def test_provider_trigger_nodes_and_github_signature(client):
    from app.nodes.registry import NODE_REGISTRY

    from app.triggers.registry import WEBHOOK_TRIGGER_TYPES

    for node_type in (
        "github_trigger", "gitlab_trigger", "stripe_trigger", "shopify_trigger",
        "slack_trigger", "typeform_trigger",
    ):
        assert node_type in NODE_REGISTRY
        assert node_type in WEBHOOK_TRIGGER_TYPES

    headers = _setup(client)
    path = "github-trigger-test-1234567890"
    secret = "github-secret-123"
    _activate(client, headers, "github_trigger", path, secret)
    payload = b'{"action":"opened"}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"x-hub-signature-256": f"sha256={signature}"},
    )
    assert accepted.status_code == 202, accepted.text


def test_gitlab_trigger_token_header(client):
    from app.db import get_session
    from app.models import WebhookTrigger
    from app.triggers.registry import WEBHOOK_TRIGGER_TYPES

    assert "gitlab_trigger" in WEBHOOK_TRIGGER_TYPES
    headers = _setup(client)
    path = "gitlab-trigger-test-1234567890"
    secret = "gitlab-webhook-token"
    _activate(client, headers, "gitlab_trigger", path, secret)
    db = get_session()
    try:
        assert db.query(WebhookTrigger).filter(WebhookTrigger.path == path).count() == 1
    finally:
        db.close()
    payload = b'{"object_kind":"push"}'
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"X-Gitlab-Token": secret},
    )
    assert accepted.status_code == 202, accepted.text

    rejected = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"X-Gitlab-Token": "wrong-token"},
    )
    assert rejected.status_code == 401, rejected.text
    assert client.post(f"/api/webhooks/{path}", content=payload).status_code == 401


def test_shopify_typeform_and_slack_trigger_signatures(client):
    headers = _setup(client)

    shopify_path = "shopify-trigger-test-1234567890"
    shopify_secret = "shopify-secret"
    _activate(client, headers, "shopify_trigger", shopify_path, shopify_secret)
    shopify_payload = b'{"id":1}'
    shopify_sig = base64.b64encode(
        hmac.new(shopify_secret.encode(), shopify_payload, hashlib.sha256).digest()
    ).decode()
    shopify_response = client.post(
        f"/api/webhooks/{shopify_path}",
        content=shopify_payload,
        headers={"x-shopify-hmac-sha256": shopify_sig},
    )
    assert shopify_response.status_code == 202, shopify_response.text

    typeform_path = "typeform-trigger-test-1234567890"
    typeform_secret = "typeform-secret"
    _activate(client, headers, "typeform_trigger", typeform_path, typeform_secret)
    typeform_payload = b'{"event_id":"e1"}'
    typeform_sig = base64.b64encode(
        hmac.new(typeform_secret.encode(), typeform_payload, hashlib.sha256).digest()
    ).decode()
    assert client.post(
        f"/api/webhooks/{typeform_path}",
        content=typeform_payload,
        headers={"typeform-signature": f"sha256={typeform_sig}"},
    ).status_code == 202

    slack_path = "slack-trigger-test-1234567890"
    slack_secret = "slack-secret"
    _activate(client, headers, "slack_trigger", slack_path, slack_secret)
    slack_payload = b'{"type":"event_callback"}'
    timestamp = str(int(time.time()))
    slack_sig = "v0=" + hmac.new(
        slack_secret.encode(),
        f"v0:{timestamp}:".encode() + slack_payload,
        hashlib.sha256,
    ).hexdigest()
    assert client.post(
        f"/api/webhooks/{slack_path}",
        content=slack_payload,
        headers={
            "x-slack-signature": slack_sig,
            "x-slack-request-timestamp": timestamp,
        },
    ).status_code == 202

    stripe_path = "stripe-trigger-test-1234567890"
    stripe_secret = "stripe-secret"
    _activate(client, headers, "stripe_trigger", stripe_path, stripe_secret)
    stripe_payload = b'{"type":"invoice.paid"}'
    stripe_ts = str(int(time.time()))
    stripe_sig = hmac.new(
        stripe_secret.encode(),
        f"{stripe_ts}.".encode() + stripe_payload,
        hashlib.sha256,
    ).hexdigest()
    assert client.post(
        f"/api/webhooks/{stripe_path}",
        content=stripe_payload,
        headers={"stripe-signature": f"t={stripe_ts},v1={stripe_sig}"},
    ).status_code == 202
