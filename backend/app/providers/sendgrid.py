"""Twilio SendGrid email provider client (Phase 40).

Integrates with SendGrid REST API v3:
https://api.sendgrid.com/v3

Supports:
- send_mail (POST /mail/send)
- list_contacts (GET /marketing/contacts)
- add_contact (PUT /marketing/contacts)
- get_stats (GET /stats)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.sendgrid")
_extract_sendgrid_error = json_error_message("errors", "message")

SENDGRID_API_BASE = "https://api.sendgrid.com/v3"


class SendGridProviderClient(BaseProviderClient):
    """Client for Twilio SendGrid REST API v3."""

    api_base = SENDGRID_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("SendGrid uses Bearer API Keys.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        api_key = str(creds.get("api_key") or creds.get("token") or "").strip()
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "SendGrid connector requires an 'api_key'.",
                retryable=False,
            )
        return api_key

    async def request_sendgrid(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        api_key = self._validate_creds(creds)
        url = f"{self.api_base}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    json=json_body if json_body is not None else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"SendGrid request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"SendGrid request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201, 202):
            if resp.status_code == 202 and not resp.text.strip():
                return {"success": True, "status_code": 202, "message": "Email accepted for delivery"}
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_sendgrid_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"SendGrid error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "SendGrid API key is invalid.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"SendGrid forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"SendGrid resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "SendGrid rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"SendGrid service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def send_mail(
        self,
        creds: dict[str, Any],
        to_email: str,
        from_email: str,
        subject: str,
        content: str,
        *,
        is_html: bool = False,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email},
            "subject": subject,
            "content": [
                {"type": "text/html" if is_html else "text/plain", "value": content}
            ],
        }
        return await self.request_sendgrid(creds, "POST", "mail/send", json_body=body, timeout=timeout)

    async def list_contacts(
        self,
        creds: dict[str, Any],
        *,
        page_size: int = 50,
        page_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        return await self.request_sendgrid(creds, "GET", "marketing/contacts", params=params, timeout=timeout)

    async def add_contact(
        self,
        creds: dict[str, Any],
        email: str,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        contact: dict[str, Any] = {"email": email}
        if first_name:
            contact["first_name"] = first_name
        if last_name:
            contact["last_name"] = last_name
        body = {"contacts": [contact]}
        return await self.request_sendgrid(creds, "PUT", "marketing/contacts", json_body=body, timeout=timeout)

    async def get_stats(
        self,
        creds: dict[str, Any],
        start_date: str,
        *,
        end_date: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        return await self.request_sendgrid(creds, "GET", "stats", params=params, timeout=timeout)
