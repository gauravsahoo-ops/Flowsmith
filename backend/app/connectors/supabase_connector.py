"""Supabase connector implementing ConnectorSDK (PostgREST & RPC)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorError,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


class SupabaseConnector(ConnectorSDK, ConnectorOperations):
    """Supabase connector for database querying, mutations, and Edge Functions/RPC."""

    connector_id = "supabase"
    display_name = "Supabase"
    description = "Query tables, insert/update/delete records, and call RPC functions in Supabase."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> List[str]:
        return ["supabase"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        self.credentials = config or {}
        return True

    async def disconnect(self) -> None:
        self.credentials = {}

    def _get_headers(self, creds: Dict[str, Any]) -> Dict[str, str]:
        key = creds.get("service_role_key") or creds.get("anon_key") or creds.get("api_key") or ""
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def op_health_check(self) -> ConnectorHealthCheck:
        url = (self.credentials.get("url") or self.credentials.get("supabase_url") or "").rstrip("/")
        if not url:
            return ConnectorHealthCheck(
                healthy=False,
                message="Missing Supabase project URL",
            )
        headers = self._get_headers(self.credentials)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{url}/rest/v1/", headers=headers)
                if res.status_code in (200, 404):
                    return ConnectorHealthCheck(healthy=True, message="Supabase API reachable")
                return ConnectorHealthCheck(healthy=False, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(healthy=False, message=str(e))

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        creds = (context or {}).get("credentials", {}).get("supabase") or self.credentials or {}
        url = (creds.get("url") or creds.get("supabase_url") or "").rstrip("/")
        if not url:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Supabase URL is required.",
                retryable=False,
            )
        headers = self._get_headers(creds)
        params = payload or {}
        table = params.get("table", "").strip()
        timeout = float(params.get("timeout_seconds", 30.0))

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if operation == "select_rows":
                    query_params = {}
                    if params.get("select"):
                        query_params["select"] = params["select"]
                    if params.get("filter"):
                        for k, v in params["filter"].items():
                            query_params[k] = v
                    if params.get("limit"):
                        query_params["limit"] = str(params["limit"])

                    res = await client.get(f"{url}/rest/v1/{table}", headers=headers, params=query_params)
                    res.raise_for_status()
                    return {"data": res.json()}

                elif operation == "insert_row":
                    body = params.get("data") or {}
                    res = await client.post(f"{url}/rest/v1/{table}", headers=headers, json=body)
                    res.raise_for_status()
                    return {"data": res.json()}

                elif operation == "update_row":
                    body = params.get("data") or {}
                    filter_col = params.get("match_column", "id")
                    filter_val = params.get("match_value", "")
                    q = {f"{filter_col}": f"eq.{filter_val}"}
                    res = await client.patch(f"{url}/rest/v1/{table}", headers=headers, params=q, json=body)
                    res.raise_for_status()
                    return {"data": res.json()}

                elif operation == "delete_row":
                    filter_col = params.get("match_column", "id")
                    filter_val = params.get("match_value", "")
                    q = {f"{filter_col}": f"eq.{filter_val}"}
                    res = await client.delete(f"{url}/rest/v1/{table}", headers=headers, params=q)
                    res.raise_for_status()
                    return {"data": res.json()}

                elif operation == "rpc_call":
                    func_name = params.get("function_name", "").strip()
                    args = params.get("args") or {}
                    res = await client.post(f"{url}/rest/v1/rpc/{func_name}", headers=headers, json=args)
                    res.raise_for_status()
                    return {"data": res.json()}

                elif operation == "health_check":
                    check = await self.op_health_check()
                    return check.model_dump()

                else:
                    raise make_connector_error(
                        ConnectorErrorCode.VALIDATION_FAILED,
                        f"Unsupported Supabase operation: {operation}",
                        retryable=False,
                    )
            except ConnectorError:
                raise
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                code = (
                    ConnectorErrorCode.AUTH_FAILED
                    if status_code == 401
                    else ConnectorErrorCode.FORBIDDEN
                    if status_code == 403
                    else ConnectorErrorCode.NOT_FOUND
                    if status_code == 404
                    else ConnectorErrorCode.RATE_LIMITED
                    if status_code == 429
                    else ConnectorErrorCode.UNAVAILABLE
                    if status_code >= 500
                    else ConnectorErrorCode.BAD_REQUEST
                )
                raise make_connector_error(
                    code,
                    f"Supabase API error: {e.response.text}",
                    retryable=status_code >= 500 or status_code == 429,
                ) from e
            except Exception as e:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    str(e),
                    retryable=False,
                ) from e
