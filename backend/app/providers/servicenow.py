"""ServiceNow provider client.

Implements the publicly documented ServiceNow Table API v1
(https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI):

- Base: https://{instance}.service-now.com/api/now/table/{table}
- Auth: Basic (username/password) or OAuth2 Bearer (access_token)
- Ops: list/get/create/update/delete records; sysparm_query, sysparm_limit,
  sysparm_offset, sysparm_fields, sysparm_orderby supported for list.
- 429/5xx retryable; 401/403/404 mapped to normalized errors.
"""

from __future__ import annotations

import base64
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


def _base_and_headers(creds: dict) -> tuple[str, dict[str, str]]:
    instance = str((creds or {}).get("instance") or "").strip().rstrip("/")
    if "://" in instance:
        instance = instance.split("://", 1)[1]
    instance = instance.split("/")[0]
    # Strip any service-now suffix duplication: accept bare hostname or short name.
    if not instance:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "ServiceNow connector needs a 'servicenow' credential with instance.",
            retryable=False,
        )
    if "." not in instance:
        instance = f"{instance}.service-now.com"
    base = f"https://{instance}/api/now/table"

    access_token = str((creds or {}).get("access_token") or "").strip()
    username = str((creds or {}).get("username") or "").strip()
    password = str((creds or {}).get("password") or "")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    elif username and password:
        basic = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    else:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "ServiceNow connector needs Basic (username/password) or OAuth (access_token).",
            retryable=False,
        )
    return base, headers


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        if isinstance(err, dict) and (err.get("message") or err.get("detail")):
            detail = f": {str(err.get('message') or err.get('detail'))[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"ServiceNow auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"ServiceNow forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"ServiceNow resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"ServiceNow rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"ServiceNow unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"ServiceNow rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class ServiceNowProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe: fetch one sys_user row."""
        data = await self._get(creds, "sys_user", "", "test connection", params={"sysparm_limit": "1"})
        result = data.get("result") if isinstance(data, dict) else None
        count = len(result) if isinstance(result, list) else 0
        return {"ok": True, "message": f"Connected ({count} probe row)."} if count else {"ok": True, "message": "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        base, headers = _base_and_headers(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{base}{path}",
                    headers=headers, params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"ServiceNow unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def _get(self, creds: dict, table: str, suffix: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        table = str(table or "").strip()
        if not table:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"{what} needs a table name.", retryable=False)
        return await self._request(creds, "GET", f"/{table}{suffix}", what, params=params, timeout=timeout)

    async def list_records(
        self, creds: dict, table: str, query: str = "", limit: int = 25,
        offset: int = 0, fields: str = "", orderby: str = "",
        timeout: float = 30.0,
    ) -> dict:
        params: dict[str, Any] = {
            "sysparm_limit": str(max(1, min(int(limit or 25), 100))),
            "sysparm_offset": str(max(0, int(offset or 0))),
        }
        if query:
            params["sysparm_query"] = query
        if fields:
            params["sysparm_fields"] = fields
        if orderby:
            params["sysparm_orderby"] = orderby
        return await self._get(creds, table, "", "list_records", params=params, timeout=timeout)

    async def get_record(self, creds: dict, table: str, sys_id: str, timeout: float = 30.0) -> dict:
        if not str(sys_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_record needs a sys_id.", retryable=False)
        return await self._get(creds, table, f"/{sys_id}", "get_record", timeout=timeout)

    async def create_record(self, creds: dict, table: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        table = str(table or "").strip()
        if not table:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_record needs a table.", retryable=False)
        if not isinstance(fields, dict) or not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_record needs a fields object.", retryable=False)
        base, headers = _base_and_headers(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", f"{base}/{table}", headers=headers, json=fields, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"ServiceNow unreachable during create_record: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "create_record", payload)
        return payload if isinstance(payload, dict) else {}

    async def update_record(
        self, creds: dict, table: str, sys_id: str, fields: dict[str, Any], timeout: float = 30.0,
    ) -> dict:
        table = str(table or "").strip()
        if not table:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_record needs a table.", retryable=False)
        if not str(sys_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_record needs a sys_id.", retryable=False)
        if not isinstance(fields, dict) or not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_record needs fields to update.", retryable=False)
        base, headers = _base_and_headers(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "PATCH", f"{base}/{table}/{sys_id}", headers=headers, json=fields, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"ServiceNow unreachable during update_record: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "update_record", payload)
        return payload if isinstance(payload, dict) else {}

    async def delete_record(self, creds: dict, table: str, sys_id: str, timeout: float = 30.0) -> dict:
        table = str(table or "").strip()
        if not table:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "delete_record needs a table.", retryable=False)
        if not str(sys_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "delete_record needs a sys_id.", retryable=False)
        base, headers = _base_and_headers(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "DELETE", f"{base}/{table}/{sys_id}", headers=headers, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"ServiceNow unreachable during delete_record: {exc}", retryable=True,
            ) from exc
        if response.status_code in (200, 202, 204):
            try:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("result") is not None:
                    return payload
            except Exception:
                pass
            return {"result": {"sys_id": sys_id, "deleted": True}}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "delete_record", payload)
        return payload if isinstance(payload, dict) else {}
