"""Freshdesk provider client.

Freshdesk API v2 with email/API-token Basic auth.
Ops: ticket list/get/create/update + notes. 429/5xx retryable.
"""

from __future__ import annotations

import base64
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


def _auth(creds: dict) -> tuple[str, str]:
    email = str((creds or {}).get("email") or "").strip()
    api_token = str((creds or {}).get("api_token") or "").strip()
    domain = str((creds or {}).get("domain") or "").strip().rstrip("/")
    if not email or not api_token or not domain:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Freshdesk connector needs a 'freshdesk' credential with email, api_token and domain.",
            retryable=False,
        )
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    domain = domain.split(".")[0]
    basic = base64.b64encode(f"{api_token}:X".encode()).decode()
    return basic, f"https://{domain}.freshdesk.com/api/v2"


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("description") or payload.get("message")
        if err:
            detail = f": {str(err)[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Freshdesk auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Freshdesk forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Freshdesk resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Freshdesk rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Freshdesk unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Freshdesk rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class FreshdeskProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (agent profile)."""
        data = await self._get(creds, "/agents/me", "test connection")
        name = data.get("contact", {}).get("name", "") if isinstance(data, dict) else ""
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
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
                ConnectorErrorCode.UNAVAILABLE, f"Freshdesk unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request(creds, "GET", path, what, params=params, timeout=timeout)

    async def list_tickets(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        data = await self._request(creds, "GET", "/tickets", "list_tickets",
                                   params={"per_page": max(1, min(int(limit or 25), 100))}, timeout=timeout)
        items = data if isinstance(data, list) else []
        return {"tickets": items}

    async def get_ticket(self, creds: dict, ticket_id: str, timeout: float = 30.0) -> dict:
        if not str(ticket_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_ticket needs a ticket_id.", retryable=False)
        return await self._get(creds, f"/tickets/{ticket_id}", "get_ticket", timeout=timeout)

    async def create_ticket(
        self, creds: dict, subject: str, description: str, email: str,
        priority: int = 1, timeout: float = 30.0,
    ) -> dict:
        if not str(subject or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_ticket needs a subject.", retryable=False)
        if not str(description or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_ticket needs a description.", retryable=False)
        if not str(email or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_ticket needs a requester email.", retryable=False)
        return await self._request(creds, "POST", "/tickets", "create_ticket", body={
            "subject": subject, "description": description, "email": email, "priority": int(priority),
        }, timeout=timeout)

    async def update_ticket(self, creds: dict, ticket_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(ticket_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_ticket needs a ticket_id.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_ticket needs fields to update.", retryable=False)
        return await self._request(creds, "PUT", f"/tickets/{ticket_id}", "update_ticket", body=fields, timeout=timeout)

    async def add_note(self, creds: dict, ticket_id: str, body: str, private: bool = True, timeout: float = 30.0) -> dict:
        if not str(ticket_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs a ticket_id.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs a body.", retryable=False)
        return await self._request(creds, "POST", f"/tickets/{ticket_id}/notes", "add_note",
                                   body={"body": body, "private": bool(private)}, timeout=timeout)
