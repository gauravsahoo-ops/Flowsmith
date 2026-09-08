"""Stripe connector tests (Phase 11 business connectors).

Proves: form-encoded bodies with Bearer secret key, execution-scoped
Idempotency-Key stability/uniqueness contract, amount/currency
validation, starting_after pagination, 429 Retry-After, and a full-stack
run where the secret key never leaks into the execution record.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http
from tests.test_api.conftest import auth_headers, register

MODULE = "app.providers.stripe"
CREDS = {"secret_key": "sk_test_SECRET_VALUE"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_create_customer_sends_form_body_and_idempotency_key():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "cus_123", "email": "a@b.com", "name": "Ann", "created": 1}),
    ])
    try:
        from app.providers.stripe import StripeProviderClient, idempotency_key

        ctx = {"execution_id": "exec_1"}
        payload = {"email": "a@b.com", "name": "Ann"}
        out = asyncio.new_event_loop().run_until_complete(
            StripeProviderClient().create_customer(
                CREDS, "a@b.com", name="Ann",
                idem_key=idempotency_key(ctx, "create_customer", payload),
            )
        )
    finally:
        patcher.stop()

    assert out["id"] == "cus_123"
    method, url, kwargs = fake.calls[0]
    assert url == "https://api.stripe.com/v1/customers"
    assert kwargs["headers"]["Authorization"] == "Bearer sk_test_SECRET_VALUE"
    assert "Idempotency-Key" in kwargs["headers"]
    # Form-encoded, not JSON.
    assert kwargs["data"] == "email=a%40b.com&name=Ann"


def test_idempotency_key_stable_across_retries_unique_across_executions():
    from app.providers.stripe import idempotency_key

    payload = {"amount": 5000, "currency": "usd"}
    k1 = idempotency_key({"execution_id": "exec_A"}, "create_payment_intent", payload)
    k2 = idempotency_key({"execution_id": "exec_A"}, "create_payment_intent", payload)
    k3 = idempotency_key({"execution_id": "exec_B"}, "create_payment_intent", payload)
    k4 = idempotency_key({"execution_id": "exec_A"}, "create_customer", payload)

    # Same logical write (engine retry) -> same key.
    assert k1 == k2
    # Different execution or operation -> different key.
    assert k1 != k3
    assert k1 != k4


def test_payment_intent_validation():
    from app.providers.stripe import StripeProviderClient

    async def go(amount, currency):
        await StripeProviderClient().create_payment_intent(CREDS, amount, currency)

    loop = asyncio.new_event_loop()
    for amount, currency in ((0, "usd"), (-5, "usd"), (100, "euro")):
        try:
            loop.run_until_complete(go(amount, currency))
            raise AssertionError(f"({amount}, {currency}) should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"unexpected error type: {exc}") from exc


def test_list_customers_follows_starting_after():
    page1 = {
        "data": [{"id": "cus_a"}, {"id": "cus_b"}],
        "has_more": True,
    }
    page2 = {"data": [{"id": "cus_c"}], "has_more": False}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, page1),
        json_response(200, page2),
    ])
    try:
        from app.providers.stripe import StripeProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            StripeProviderClient().list_customers(CREDS, limit=2, max_pages=3)
        )
    finally:
        patcher.stop()

    assert [c["id"] for c in out["customers"]] == ["cus_a", "cus_b", "cus_c"]
    _, url2, _kwargs2 = fake.calls[1]
    assert "starting_after=cus_b" in url2


def test_rate_limit_maps_retry_after():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": {"message": "Too many requests"}}, headers={"Retry-After": "5"}),
    ])
    try:
        from app.providers.stripe import StripeProviderClient

        async def go():
            await StripeProviderClient().get_customer(CREDS, "cus_1")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("429 should have raised")
        except ConnectorError as exc:
            assert exc.retryable is True
            assert exc.retry_after == 5.0
        finally:
            loop.close()
    finally:
        patcher.stop()


# ----------------------------------------------------------------------
# Full stack: API -> queue -> worker -> engine -> connector
# ----------------------------------------------------------------------

def test_full_stack_stripe_customer_with_secret_leak_check(client):
    headers = auth_headers(register(client)["token"])
    resp = client.post(
        "/api/credentials",
        json={"name": "Stripe Prod", "type": "stripe", "data": CREDS},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    cred_id = resp.json()["data"]["id"]

    wf = {
        "id": "wf_stripe",
        "name": "Stripe Create Customer",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "pay",
                "type": "stripe",
                "parameters": {
                    "operation": "create_customer",
                    "email": "{{ $json.email }}",
                },
                "credentials": {"stripe": cred_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "pay"}],
        "settings": {},
    }
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201, resp.text

    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "cus_777", "email": "new@acme.com"}),
    ])
    try:
        resp = client.post(
            "/api/workflows/wf_stripe/run",
            json={"data": {"email": "new@acme.com"}},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
        execution_id = resp.json()["data"]["execution_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
            if data["status"] not in ("running", "queued", "cancelling"):
                break
            time.sleep(0.05)
    finally:
        patcher.stop()

    assert data["status"] == "success", data.get("error")
    outputs = data["results"]["outputs"]["pay"]["main"]
    assert outputs[0]["id"] == "cus_777"

    # The outgoing call used the stored key; the record never shows it.
    raw = json.dumps(data, default=str)
    assert "sk_test_SECRET_VALUE" not in raw
