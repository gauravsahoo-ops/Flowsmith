"""Brevo provider client.

Brevo API v3 with api-key header auth.
Ops: SMTP email send, contact CRUD. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

BREVO_API_BASE = "https://api.sendinblue.com/v3"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("api_key") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Brevo connector needs a 'brevo' credential with api_key.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("message") or payload.get("code")
        if err:
            detail = f": {str(err)[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Brevo auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Brevo forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Brevo resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Brevo rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Brevo unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Brevo rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class BrevoProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (account info)."""
        data = await self._get(creds, "/account", "test connection")
        email = data.get("email", "") if isinstance(data, dict) else ""
        return {"ok": True, "message": f"Connected as {email}." if email else "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{BREVO_API_BASE}{path}",
                    headers={"api-key": _key(creds), "Content-Type": "application/json"},
                    params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Brevo unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request(creds, "GET", path, what, params=params, timeout=timeout)

    async def send_email(
        self, creds: dict, sender_email: str, to_email: str, subject: str,
        html: str = "", text: str = "", timeout: float = 30.0,
    ) -> dict:
        for label, value in (("sender", sender_email), ("to", to_email), ("subject", subject)):
            if not str(value or "").strip():
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"send_email needs {label}.", retryable=False)
        if not html and not text:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_email needs html or text content.", retryable=False)
        body: dict[str, Any] = {
            "sender": {"email": sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
        }
        if html:
            body["htmlContent"] = html
        if text:
            body["textContent"] = text
        return await self._request(creds, "POST", "/smtp/email", "send_email", body=body, timeout=timeout)

    async def list_contacts(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        return await self._get(creds, "/contacts", "list_contacts",
                               params={"limit": max(1, min(int(limit or 25), 1000))}, timeout=timeout)

    async def get_contact(self, creds: dict, email: str, timeout: float = 30.0) -> dict:
        if not str(email or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_contact needs an email.", retryable=False)
        return await self._get(creds, f"/contacts/{email}", "get_contact", timeout=timeout)

    async def create_contact(self, creds: dict, email: str, attributes: dict[str, Any] | None = None, timeout: float = 30.0) -> dict:
        if not str(email or "").strip() or "@" not in email:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_contact needs a valid email.", retryable=False)
        body: dict[str, Any] = {"email": email}
        if attributes:
            body["attributes"] = attributes
        return await self._request(creds, "POST", "/contacts", "create_contact", body=body, timeout=timeout)

    async def update_contact(self, creds: dict, email: str, attributes: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(email or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_contact needs an email.", retryable=False)
        if not attributes:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_contact needs attributes.", retryable=False)
        body: dict[str, Any] = {"attributes": {k: v for k, v in attributes.items() if k != "subscribed"}}
        if "subscribed" in attributes:
            # Brevo models subscription as a blacklist flag.
            body["emailBlacklisted"] = not bool(attributes["subscribed"])
        return await self._request(creds, "PUT", f"/contacts/{email}", "update_contact",
                                   body=body, timeout=timeout)
