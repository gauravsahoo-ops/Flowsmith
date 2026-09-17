"""Mailchimp provider client.

Mailchimp Marketing API v3 with HTTP Basic auth (any username + API key).
The API key suffix selects the datacenter (e.g. key ending -us21).
Ops: list/get audiences, add/get/update members. 429/5xx retryable.
"""

from __future__ import annotations

import base64
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


def _auth(creds: dict) -> tuple[str, str]:
    api_key = str((creds or {}).get("api_key") or "").strip()
    datacenter = str((creds or {}).get("datacenter") or "").strip()
    if not api_key:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Mailchimp connector needs a 'mailchimp' credential with api_key.",
            retryable=False,
        )
    if not datacenter and "-" in api_key:
        datacenter = api_key.rsplit("-", 1)[1].strip()
    if not datacenter:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Mailchimp datacenter unknown: use an API key ending in -usXX or set datacenter explicitly.",
            retryable=False,
        )
    basic = base64.b64encode(f"anystring:{api_key}".encode()).decode()
    return basic, f"https://{datacenter}.api.mailchimp.com/3.0"


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("detail") or payload.get("title")
        if err:
            detail = f": {str(err)[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Mailchimp auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Mailchimp forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Mailchimp resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Mailchimp rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Mailchimp unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Mailchimp rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class MailchimpProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (account root)."""
        data = await self._get(creds, "/", "test connection")
        account = data.get("account_id", "") if isinstance(data, dict) else ""
        return {"ok": True, "message": f"Connected (account {account})." if account else "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        basic, base = _auth(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{base}{path}",
                    headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
                    params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Mailchimp unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request(creds, "GET", path, what, params=params, timeout=timeout)

    async def list_lists(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        return await self._get(creds, "/lists", "list_lists",
                               params={"count": max(1, min(int(limit or 25), 1000))}, timeout=timeout)

    async def get_list(self, creds: dict, list_id: str, timeout: float = 30.0) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_list needs a list_id.", retryable=False)
        return await self._get(creds, f"/lists/{list_id}", "get_list", timeout=timeout)

    @staticmethod
    def _subscriber_hash(email: str) -> str:
        import hashlib

        return hashlib.md5(email.strip().lower().encode()).hexdigest()

    async def add_member(self, creds: dict, list_id: str, email: str, status: str = "subscribed", timeout: float = 30.0) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_member needs a list_id.", retryable=False)
        if not str(email or "").strip() or "@" not in email:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_member needs a valid email.", retryable=False)
        if status not in ("subscribed", "pending", "unsubscribed", "cleaned"):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_member status must be subscribed/pending/unsubscribed/cleaned.", retryable=False)
        return await self._request(creds, "POST", f"/lists/{list_id}/members", "add_member",
                                   body={"email_address": email, "status": status}, timeout=timeout)

    async def get_member(self, creds: dict, list_id: str, email: str, timeout: float = 30.0) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_member needs a list_id.", retryable=False)
        if not str(email or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_member needs an email.", retryable=False)
        return await self._get(creds, f"/lists/{list_id}/members/{self._subscriber_hash(email)}", "get_member", timeout=timeout)

    async def update_member(self, creds: dict, list_id: str, email: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_member needs a list_id.", retryable=False)
        if not str(email or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_member needs an email.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_member needs fields to update.", retryable=False)
        return await self._request(creds, "PATCH", f"/lists/{list_id}/members/{self._subscriber_hash(email)}",
                                   "update_member", body=fields, timeout=timeout)
