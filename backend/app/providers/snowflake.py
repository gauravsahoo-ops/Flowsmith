"""Snowflake Data Cloud provider client (Phase 39 Native Cloud Data Connector).

Integrates with the Snowflake SQL REST API v2:
https://<account_identifier>.snowflakecomputing.com/api/v2/statements

Supports:
- execute_statement (synchronous or polling asynchronous queries)
- get_statement_status / retrieve results
- cancel_statement
- describe_table (schema introspection)
- list_tables (catalog discovery)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.snowflake")
_extract_snowflake_error = json_error_message("message", "sqlState")


class SnowflakeProviderClient(BaseProviderClient):
    """Client for Snowflake SQL REST API v2."""

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Snowflake SQL API uses OAuth tokens or Keypair JWTs.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
        account = str(creds.get("account") or creds.get("account_identifier") or "").strip().lower()
        if not account:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Snowflake connector requires an 'account' identifier (e.g. 'xy12345.us-east-1' or 'orgname-accountname').",
                retryable=False,
            )
        # Remove .snowflakecomputing.com if user accidentally passed full hostname
        account = account.replace(".snowflakecomputing.com", "").strip()

        token = str(creds.get("token") or creds.get("api_key") or creds.get("access_token") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Snowflake connector requires a 'token' or 'api_key' (OAuth Bearer or Keypair JWT).",
                retryable=False,
            )

        defaults = {
            "warehouse": str(creds.get("warehouse") or "").strip(),
            "database": str(creds.get("database") or "").strip(),
            "schema": str(creds.get("schema") or "").strip(),
            "role": str(creds.get("role") or "").strip(),
        }
        return account, token, defaults

    def _get_api_base(self, account: str) -> str:
        return f"https://{account}.snowflakecomputing.com/api/v2/statements"

    async def request_snowflake(
        self,
        account: str,
        token: str,
        method: str,
        path: str = "",
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        base_url = self._get_api_base(account)
        url = f"{base_url}/{path.lstrip('/')}" if path else base_url

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "FlowSmith-Snowflake-Client/1.0",
        }

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    json=json_body if json_body else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Snowflake request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Snowflake request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 202):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_snowflake_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Snowflake query error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Snowflake authentication failed: invalid token or expired JWT.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Snowflake access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Snowflake statement or resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Snowflake API rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Snowflake service error ({resp.status_code}): {resp.text[:200]}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def execute_statement(
        self,
        creds: dict[str, Any],
        statement: str,
        *,
        warehouse: Optional[str] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        role: Optional[str] = None,
        timeout: float = 60.0,
        wait_for_completion: bool = True,
        poll_interval: float = 1.0,
        max_poll_time: float = 30.0,
    ) -> dict[str, Any]:
        account, token, defaults = self._validate_creds(creds)
        body: dict[str, Any] = {
            "statement": statement,
            "timeout": int(timeout),
        }
        wh = warehouse or defaults.get("warehouse")
        db = database or defaults.get("database")
        sc = schema or defaults.get("schema")
        ro = role or defaults.get("role")

        if wh:
            body["warehouse"] = wh
        if db:
            body["database"] = db
        if sc:
            body["schema"] = sc
        if ro:
            body["role"] = ro

        res = await self.request_snowflake(account, token, "POST", json_body=body, timeout=timeout)
        statement_handle = res.get("statementHandle")

        if not wait_for_completion or not statement_handle:
            return res

        # If query is still executing asynchronously (202 or code 333334), poll for results
        code = str(res.get("code") or "")
        elapsed = 0.0
        while code in ("333334", "090001") or res.get("status") == "running":
            if elapsed >= max_poll_time:
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            res = await self.request_snowflake(account, token, "GET", statement_handle, timeout=timeout)
            code = str(res.get("code") or "")

        return res

    async def get_statement(
        self,
        creds: dict[str, Any],
        statement_handle: str,
        *,
        partition: int = 0,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        account, token, _ = self._validate_creds(creds)
        params = {"partition": partition} if partition > 0 else None
        return await self.request_snowflake(account, token, "GET", statement_handle, params=params, timeout=timeout)

    async def cancel_statement(
        self,
        creds: dict[str, Any],
        statement_handle: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        account, token, _ = self._validate_creds(creds)
        path = f"{statement_handle}/cancel"
        return await self.request_snowflake(account, token, "POST", path, timeout=timeout)

    async def describe_table(
        self,
        creds: dict[str, Any],
        table_name: str,
        *,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        qualified = table_name
        if database and schema:
            qualified = f'"{database}"."{schema}"."{table_name}"'
        elif schema:
            qualified = f'"{schema}"."{table_name}"'

        sql = f"DESCRIBE TABLE {qualified}"
        return await self.execute_statement(creds, sql, database=database, schema=schema, timeout=timeout)

    async def list_tables(
        self,
        creds: dict[str, Any],
        *,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        if database and schema:
            sql = f'SHOW TABLES IN SCHEMA "{database}"."{schema}"'
        elif schema:
            sql = f'SHOW TABLES IN SCHEMA "{schema}"'
        elif database:
            sql = f'SHOW TABLES IN DATABASE "{database}"'
        else:
            sql = "SHOW TABLES"
        return await self.execute_statement(creds, sql, database=database, schema=schema, timeout=timeout)
