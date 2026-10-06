"""Google Cloud BigQuery provider client (Phase 40).

Integrates with Google Cloud BigQuery REST API v2:
https://bigquery.googleapis.com/bigquery/v2/projects/{projectId}

Supports:
- query (POST /queries)
- get_query_results (GET /queries/{jobId})
- list_datasets (GET /datasets)
- list_tables (GET /datasets/{datasetId}/tables)
- get_table (GET /datasets/{datasetId}/tables/{tableId})
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.bigquery")
_extract_bigquery_error = json_error_message("error", "message")

BIGQUERY_API_BASE = "https://bigquery.googleapis.com/bigquery/v2/projects"


class BigQueryProviderClient(BaseProviderClient):
    """Client for Google BigQuery REST API v2."""

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("BigQuery uses Google OAuth access tokens or service account credentials.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> tuple[str, str]:
        project_id = str(creds.get("project_id") or creds.get("projectId") or "").strip()
        if not project_id:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "BigQuery connector requires a 'project_id'.",
                retryable=False,
            )
        token = str(creds.get("access_token") or creds.get("token") or creds.get("api_key") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "BigQuery connector requires an 'access_token' (Google OAuth2 or Service Account token).",
                retryable=False,
            )
        return project_id, token

    async def request_bigquery(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        project_id, token = self._validate_creds(creds)
        url = f"{BIGQUERY_API_BASE}/{project_id}/{path.lstrip('/')}"

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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"BigQuery request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"BigQuery request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_bigquery_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"BigQuery query error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "BigQuery authentication token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"BigQuery access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"BigQuery dataset/table not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "BigQuery quota exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"BigQuery server error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def query(
        self,
        creds: dict[str, Any],
        query_sql: str,
        *,
        max_results: int = 100,
        timeout_ms: int = 30000,
        use_legacy_sql: bool = False,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        body = {
            "query": query_sql,
            "maxResults": max_results,
            "timeoutMs": timeout_ms,
            "useLegacySql": use_legacy_sql,
        }
        return await self.request_bigquery(creds, "POST", "queries", json_body=body, timeout=timeout)

    async def get_query_results(
        self,
        creds: dict[str, Any],
        job_id: str,
        *,
        page_token: Optional[str] = None,
        max_results: int = 100,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        return await self.request_bigquery(creds, "GET", f"queries/{job_id}", params=params, timeout=timeout)

    async def list_datasets(
        self,
        creds: dict[str, Any],
        *,
        max_results: int = 50,
        page_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        return await self.request_bigquery(creds, "GET", "datasets", params=params, timeout=timeout)

    async def list_tables(
        self,
        creds: dict[str, Any],
        dataset_id: str,
        *,
        max_results: int = 50,
        page_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        return await self.request_bigquery(creds, "GET", f"datasets/{dataset_id}/tables", params=params, timeout=timeout)

    async def get_table(
        self,
        creds: dict[str, Any],
        dataset_id: str,
        table_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_bigquery(creds, "GET", f"datasets/{dataset_id}/tables/{table_id}", timeout=timeout)
