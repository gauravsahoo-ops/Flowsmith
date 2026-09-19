"""Supabase connector implementing ConnectorSDK (PostgREST & RPC)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorStatus,
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
    node_types = ["supabase"]

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    async def connect(self, credentials: Dict[str, Any]) -> bool:
        self.credentials = credentials or {}
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
                status=ConnectorStatus.UNHEALTHY,
                message="Missing Supabase project URL",
            )
        headers = self._get_headers(self.credentials)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{url}/rest/v1/", headers=headers)
                if res.status_code in (200, 404):
                    return ConnectorHealthCheck(status=ConnectorStatus.HEALTHY, message="Supabase API reachable")
                return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=str(e))

    async def op_execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        creds = self.credentials or {}
        url = (creds.get("url") or creds.get("supabase_url") or "").rstrip("/")
        if not url:
            raise make_connector_error(
                "Supabase URL is required.",
                code=ConnectorErrorCode.CONFIG_MISSING,
            )
        headers = self._get_headers(creds)
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
                        f"Unsupported Supabase operation: {operation}",
                        code=ConnectorErrorCode.VALIDATION_FAILED,
                    )
            except httpx.HTTPStatusError as e:
                raise make_connector_error(
                    f"Supabase API error: {e.response.text}",
                    code=ConnectorErrorCode.REMOTE_ERROR,
                )
            except Exception as e:
                raise make_connector_error(
                    str(e),
                    code=ConnectorErrorCode.EXECUTION_FAILED,
                )
