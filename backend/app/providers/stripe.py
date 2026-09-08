"""Stripe provider client (Phase 11 business connectors).

Secret-key auth over the form-encoded REST API. Write operations carry
a deterministic ``Idempotency-Key`` derived from the execution context
so engine retries can never double-charge/double-create.

Pagination: list endpoints walk ``starting_after`` cursors.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import json_error_message
from app.security.safe_http_client import get_safe_http_client

STRIPE_API_BASE = "https://api.stripe.com/v1"
_extract_stripe_error = json_error_message("message")


def _require_secret_key(creds: dict) -> str:
    key = str((creds or {}).get("secret_key") or "").strip()
    if not key:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Stripe connector needs a 'stripe' credential with a secret key (sk_…).",
            retryable=False,
        )
    return key


def idempotency_key(context: dict | None, operation: str, payload: dict) -> str:
    """Stable per-(execution, node payload) key — identical across engine
    retries of the same logical write, different across executions."""
    seed = json.dumps(
        {
            "exec": str((context or {}).get("execution_id") or ""),
            "op": operation,
            "payload": payload,
        },
        sort_keys=True, default=str,
    )
    return hashlib.sha256(seed.encode()).hexdigest()[:48]


class StripeProviderClient:
    """Low-level Stripe REST client (form-encoded bodies)."""

    async def request_stripe(
        self, creds: dict, method: str, path: str, *,
        form: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        idempotency_key_value: str = "",
        timeout: float = 30.0, what: str = "request",
    ) -> httpx.Response:
        secret = _require_secret_key(creds)
        headers: dict[str, str] = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "identity",
        }
        if idempotency_key_value:
            headers["Idempotency-Key"] = idempotency_key_value
        url = f"{STRIPE_API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode({k: v for k, v in query.items() if v is not None})}"
        body = urlencode({k: v for k, v in (form or {}).items() if v is not None})
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, url,
                    data=body or None, headers=headers, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Stripe unreachable: {exc}", retryable=True,
            ) from exc
        retry_after = response.headers.get("Retry-After")
        if response.status_code == 429:
            raise make_connector_error(
                ConnectorErrorCode.RATE_LIMITED,
                f"Stripe {what} rate limited.",
                retryable=True,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 400:
            code_map = {401: ConnectorErrorCode.AUTH_FAILED, 403: ConnectorErrorCode.FORBIDDEN,
                        404: ConnectorErrorCode.NOT_FOUND}
            code = code_map.get(
                response.status_code,
                ConnectorErrorCode.UNAVAILABLE if response.status_code >= 500 else ConnectorErrorCode.BAD_REQUEST,
            )
            raise make_connector_error(
                code,
                f"Stripe {what} failed ({response.status_code}). {_extract_stripe_error(response)}".strip(),
                retryable=response.status_code >= 500,
            )
        return response

    @staticmethod
    def _customer_summary(c: dict) -> dict:
        return {
            "id": c.get("id"),
            "email": c.get("email"),
            "name": c.get("name"),
            "created": c.get("created"),
            "balance": c.get("balance"),
        }

    async def create_customer(self, creds: dict, email: str, name: str = "",
                              metadata: dict[str, str] | None = None,
                              idem_key: str = "", timeout: float = 30.0) -> dict:
        email_clean = str(email or "").strip()
        if not email_clean or "@" not in email_clean:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_customer requires an email.", retryable=False)
        form: dict[str, Any] = {"email": email_clean}
        if name:
            form["name"] = name
        for mk, mv in (metadata or {}).items():
            form[f"metadata[{mk}]"] = str(mv)
        response = await self.request_stripe(
            creds, "POST", "/customers", form=form, idempotency_key_value=idem_key,
            timeout=timeout, what="create customer",
        )
        customer = response.json()
        out = self._customer_summary(customer)
        out["success"] = True
        return out

    async def get_customer(self, creds: dict, customer_id: str, timeout: float = 30.0) -> dict:
        cid = str(customer_id or "").strip()
        if not cid.startswith("cus_"):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A customer id looks like cus_…", retryable=False)
        response = await self.request_stripe(
            creds, "GET", f"/customers/{cid}", timeout=timeout, what="get customer",
        )
        return self._customer_summary(response.json())

    async def list_customers(self, creds: dict, limit: int = 50, max_pages: int = 3,
                             email_filter: str = "", timeout: float = 30.0) -> dict:
        limit = min(max(int(limit or 50), 1), 100)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        customers: list[dict] = []
        starting_after: str | None = None
        has_more = False
        for _ in range(max_pages):
            query: dict[str, Any] = {"limit": limit}
            if starting_after:
                query["starting_after"] = starting_after
            if email_filter:
                query["email"] = email_filter
            response = await self.request_stripe(
                creds, "GET", "/customers", query=query,
                timeout=timeout, what="list customers",
            )
            data = response.json()
            customers.extend(self._customer_summary(c) for c in data.get("data", []))
            has_more = bool(data.get("has_more"))
            batch = data.get("data") or []
            starting_after = batch[-1]["id"] if batch and has_more else None
            if not has_more or not starting_after:
                break
        return {"customers": customers, "count": len(customers), "has_more": has_more}

    async def create_payment_intent(self, creds: dict, amount_cents: int, currency: str = "usd",
                                    customer_id: str = "", description: str = "",
                                    idem_key: str = "", timeout: float = 30.0) -> dict:
        try:
            amount = int(amount_cents)
        except (TypeError, ValueError) as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "amount must be integer cents.", retryable=False) from exc
        if amount <= 0:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "amount must be positive.", retryable=False)
        currency_clean = str(currency or "usd").strip().lower()
        if not currency_clean.isalpha() or len(currency_clean) != 3:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "currency must be a 3-letter code.", retryable=False)
        form: dict[str, Any] = {"amount": amount, "currency": currency_clean}
        if customer_id:
            form["customer"] = customer_id
        if description:
            form["description"] = description
        response = await self.request_stripe(
            creds, "POST", "/payment_intents", form=form, idempotency_key_value=idem_key,
            timeout=timeout, what="create payment intent",
        )
        data = response.json()
        return {"intent_id": data.get("id", ""), "status": data.get("status", ""),
                "client_secret": data.get("client_secret", ""), "amount": amount, "currency": currency_clean}
