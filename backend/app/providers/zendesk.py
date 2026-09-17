"""Zendesk provider client.

Zendesk Support API with email/token Basic auth.
Ops: list/get/create/update tickets, add comment. 429/5xx retryable.
"""

from __future__ import annotations

import base64
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


def _auth(creds: dict) -> tuple[str, str]:
    email = str((creds or {}).get("email") or "").strip()
    api_token = str((creds or {}).get("api_token") or "").strip()
    subdomain = str((creds or {}).get("subdomain") or "").strip().rstrip("/")
    if not email or not api_token or not subdomain:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Zendesk connector needs a 'zendesk' credential with email, api_token and subdomain.",
            retryable=False,
        )
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    subdomain = subdomain.split(".")[0]
    basic = base64.b64encode(f"{email}/token:{api_token}".encode()).decode()
    return basic, f"https://{subdomain}.zendesk.com/api/v2"


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error") or payload.get("description")
        if err:
            detail = f": {str(err)[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Zendesk auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Zendesk forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Zendesk resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Zendesk rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Zendesk unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Zendesk rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class ZendeskProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (session user)."""
        data = await self._get(creds, "/users/me.json", "test connection")
        name = ((data.get("user") or {}) if isinstance(data, dict) else {}).get("name", "")
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

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
                ConnectorErrorCode.UNAVAILABLE, f"Zendesk unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request(creds, "GET", path, what, params=params, timeout=timeout)

    async def list_tickets(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        return await self._get(creds, "/tickets.json", "list_tickets",
                               params={"per_page": max(1, min(int(limit or 25), 100))}, timeout=timeout)

    async def get_ticket(self, creds: dict, ticket_id: str, timeout: float = 30.0) -> dict:
        if not str(ticket_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_ticket needs a ticket_id.", retryable=False)
        return await self._get(creds, f"/tickets/{ticket_id}.json", "get_ticket", timeout=timeout)

    async def create_ticket(self, creds: dict, subject: str, comment: str, priority: str = "", timeout: float = 30.0) -> dict:
        if not str(subject or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_ticket needs a subject.", retryable=False)
        if not str(comment or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_ticket needs a comment.", retryable=False)
        ticket: dict[str, Any] = {"subject": subject, "comment": {"body": comment}}
        if priority:
            ticket["priority"] = priority
        return await self._request(creds, "POST", "/tickets.json", "create_ticket",
                                   body={"ticket": ticket}, timeout=timeout)

    async def update_ticket(self, creds: dict, ticket_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(ticket_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_ticket needs a ticket_id.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_ticket needs fields to update.", retryable=False)
        return await self._request(creds, "PUT", f"/tickets/{ticket_id}.json", "update_ticket",
                                   body={"ticket": fields}, timeout=timeout)

    async def add_comment(self, creds: dict, ticket_id: str, body: str, public: bool = True, timeout: float = 30.0) -> dict:
        if not str(ticket_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a ticket_id.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a body.", retryable=False)
        return await self._request(creds, "PUT", f"/tickets/{ticket_id}.json", "add_comment",
                                   body={"ticket": {"comment": {"body": body, "public": bool(public)}}},
                                   timeout=timeout)
