"""Coda collaborative documents provider client (Phase 40).

Integrates with Coda REST API v1:
https://coda.io/apis/v1

Supports:
- list_docs (GET /docs)
- get_doc (GET /docs/{docId})
- list_tables (GET /docs/{docId}/tables)
- list_rows (GET /docs/{docId}/tables/{tableIdOrName}/rows)
- insert_rows (POST /docs/{docId}/tables/{tableIdOrName}/rows)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.coda")
_extract_coda_error = json_error_message("message", "statusCode")

CODA_API_BASE = "https://coda.io/apis/v1"


class CodaProviderClient(BaseProviderClient):
    """Client for Coda REST API v1."""

    api_base = CODA_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Coda uses Bearer API Tokens.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        token = str(creds.get("api_key") or creds.get("token") or creds.get("access_token") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Coda connector requires an 'api_key' or 'token'.",
                retryable=False,
            )
        return token

    async def request_coda(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        token = self._validate_creds(creds)
        url = f"{self.api_base}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {token}",
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Coda request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Coda request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201, 202):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_coda_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Coda error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Coda API token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Coda access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Coda resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Coda rate limit reached.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Coda service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def list_docs(
        self,
        creds: dict[str, Any],
        *,
        limit: int = 50,
        page_token: Optional[str] = None,
        query: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if page_token:
            params["pageToken"] = page_token
        if query:
            params["query"] = query
        return await self.request_coda(creds, "GET", "docs", params=params, timeout=timeout)

    async def get_doc(
        self,
        creds: dict[str, Any],
        doc_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_coda(creds, "GET", f"docs/{doc_id}", timeout=timeout)

    async def list_tables(
        self,
        creds: dict[str, Any],
        doc_id: str,
        *,
        limit: int = 50,
        page_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if page_token:
            params["pageToken"] = page_token
        return await self.request_coda(creds, "GET", f"docs/{doc_id}/tables", params=params, timeout=timeout)

    async def list_rows(
        self,
        creds: dict[str, Any],
        doc_id: str,
        table_id: str,
        *,
        limit: int = 50,
        page_token: Optional[str] = None,
        query: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if page_token:
            params["pageToken"] = page_token
        if query:
            params["query"] = query
        return await self.request_coda(creds, "GET", f"docs/{doc_id}/tables/{table_id}/rows", params=params, timeout=timeout)

    async def insert_rows(
        self,
        creds: dict[str, Any],
        doc_id: str,
        table_id: str,
        rows: List[Dict[str, Any]],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {"rows": rows}
        return await self.request_coda(creds, "POST", f"docs/{doc_id}/tables/{table_id}/rows", json_body=body, timeout=timeout)
