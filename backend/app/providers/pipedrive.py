"""Pipedrive provider client.

Pipedrive REST API v1 with API-token query auth.
Ops: list/get/create/update deals, add note. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


def _auth(creds: dict) -> tuple[str, str]:
    token = str((creds or {}).get("api_token") or "").strip()
    domain = str((creds or {}).get("domain") or "").strip().rstrip("/")
    if not token or not domain:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Pipedrive connector needs a 'pipedrive' credential with api_token and domain.",
            retryable=False,
        )
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    return token, f"https://{domain}/api/v1"


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error") or payload.get("message")
        if err:
            detail = f": {str(err)[:200]}"
    if status < 400:
        if isinstance(payload, dict) and payload.get("success") is False:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Pipedrive rejected {what}{detail or ': ' + body[:200]}.", retryable=False)
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Pipedrive auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Pipedrive forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Pipedrive resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Pipedrive rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Pipedrive unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Pipedrive rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class PipedriveProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (current user)."""
        data = await self._get(creds, "/users/me", "test connection")
        name = ((data.get("data") or {}) if isinstance(data, dict) else {}).get("name", "")
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        token, base = _auth(creds)
        query = {"api_token": token, **(params or {})}
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{base}{path}", params=query, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Pipedrive unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request(creds, "GET", path, what, params=params, timeout=timeout)

    async def list_deals(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        return await self._get(creds, "/deals", "list_deals",
                               params={"limit": max(1, min(int(limit or 25), 500))}, timeout=timeout)

    async def get_deal(self, creds: dict, deal_id: str, timeout: float = 30.0) -> dict:
        if not str(deal_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_deal needs a deal_id.", retryable=False)
        return await self._get(creds, f"/deals/{deal_id}", "get_deal", timeout=timeout)

    async def create_deal(self, creds: dict, title: str, value: str = "", currency: str = "", timeout: float = 30.0) -> dict:
        if not str(title or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_deal needs a title.", retryable=False)
        body: dict[str, Any] = {"title": title}
        if value:
            body["value"] = value
        if currency:
            body["currency"] = currency
        return await self._request(creds, "POST", "/deals", "create_deal", body=body, timeout=timeout)

    async def update_deal(self, creds: dict, deal_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(deal_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_deal needs a deal_id.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_deal needs fields to update.", retryable=False)
        return await self._request(creds, "PUT", f"/deals/{deal_id}", "update_deal", body=fields, timeout=timeout)

    async def add_note(self, creds: dict, deal_id: str, content: str, timeout: float = 30.0) -> dict:
        if not str(deal_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs a deal_id.", retryable=False)
        if not str(content or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs content.", retryable=False)
        return await self._request(creds, "POST", "/notes", "add_note",
                                   body={"content": content, "deal_id": deal_id}, timeout=timeout)
