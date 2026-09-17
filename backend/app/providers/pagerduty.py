"""PagerDuty provider client.

PagerDuty REST API v2 with token auth (Authorization: Token token=...).
Ops: list/get/create/update/resolve incidents, add note. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

PAGERDUTY_API_BASE = "https://api.pagerduty.com"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("api_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "PagerDuty connector needs a 'pagerduty' credential with api_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        if isinstance(err, dict) and (err.get("message") or err.get("code")):
            detail = f": {err.get('code', '')} {err.get('message', '')}".rstrip()[:200]
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"PagerDuty auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"PagerDuty forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"PagerDuty resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"PagerDuty rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"PagerDuty unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"PagerDuty rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class PagerDutyProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (abilities)."""
        data = await self._get(creds, "/abilities", "test connection")
        abilities = data.get("abilities", []) if isinstance(data, dict) else []
        return {"ok": True, "message": f"Connected ({len(abilities)} abilities)."} if abilities else {"ok": True, "message": "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{PAGERDUTY_API_BASE}{path}",
                    headers={
                        "Authorization": f"Token token={_key(creds)}",
                        "Content-Type": "application/json",
                        "Accept": "application/vnd.pagerduty+json;version=2",
                    },
                    params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"PagerDuty unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return await self._request(creds, "GET", path, what, params=params, timeout=timeout)

    async def list_incidents(self, creds: dict, limit: int = 25, urgencies: str = "", timeout: float = 30.0) -> dict:
        params: dict[str, Any] = {"limit": max(1, min(int(limit or 25), 100))}
        if urgencies:
            params["urgencies[]"] = urgencies
        return await self._get(creds, "/incidents", "list_incidents", params=params, timeout=timeout)

    async def get_incident(self, creds: dict, incident_id: str, timeout: float = 30.0) -> dict:
        if not str(incident_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_incident needs an incident_id.", retryable=False)
        return await self._get(creds, f"/incidents/{incident_id}", "get_incident", timeout=timeout)

    async def create_incident(
        self, creds: dict, title: str, service_id: str, urgency: str = "",
        description: str = "", timeout: float = 30.0,
    ) -> dict:
        if not str(title or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_incident needs a title.", retryable=False)
        if not str(service_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_incident needs a service_id.", retryable=False)
        body: dict[str, Any] = {
            "incident": {
                "type": "incident",
                "title": title,
                "service": {"id": service_id, "type": "service_reference"},
            }
        }
        if urgency:
            body["incident"]["urgency"] = urgency
        if description:
            body["incident"]["body"] = {"type": "incident_body", "details": description}
        return await self._request(creds, "POST", "/incidents", "create_incident", body=body, timeout=timeout)

    async def update_incident(
        self, creds: dict, incident_id: str, fields: dict[str, Any], timeout: float = 30.0,
    ) -> dict:
        if not str(incident_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_incident needs an incident_id.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_incident needs fields to update.", retryable=False)
        return await self._request(
            creds, "PUT", f"/incidents/{incident_id}", "update_incident",
            body={"incident": {"type": "incident", **fields}}, timeout=timeout)

    async def resolve_incident(self, creds: dict, incident_id: str, timeout: float = 30.0) -> dict:
        if not str(incident_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "resolve_incident needs an incident_id.", retryable=False)
        return await self._request(
            creds, "PUT", f"/incidents/{incident_id}", "resolve_incident",
            body={"incident": {"type": "incident", "status": "resolved"}}, timeout=timeout)

    async def add_note(self, creds: dict, incident_id: str, content: str, timeout: float = 30.0) -> dict:
        if not str(incident_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs an incident_id.", retryable=False)
        if not str(content or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs content.", retryable=False)
        return await self._request(creds, "POST", f"/incidents/{incident_id}/notes", "add_note",
                                   body={"note": {"content": content}}, timeout=timeout)
