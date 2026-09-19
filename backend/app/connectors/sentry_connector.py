"""Sentry developer monitoring and error tracking connector implementing ConnectorSDK."""

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


class SentryConnector(ConnectorSDK, ConnectorOperations):
    """Sentry connector for error tracking, issue management, and event alerting."""

    connector_id = "sentry"
    display_name = "Sentry"
    description = "List, inspect, and manage errors and unresolved issues in Sentry."
    category = ConnectorCategory.API
    version = "1.0.0"
    node_types = ["sentry"]

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    async def connect(self, credentials: Dict[str, Any]) -> bool:
        self.credentials = credentials or {}
        return True

    async def disconnect(self) -> None:
        self.credentials = {}

    def _get_headers(self, creds: Dict[str, Any]) -> Dict[str, str]:
        token = creds.get("auth_token") or creds.get("api_key") or ""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def op_health_check(self) -> ConnectorHealthCheck:
        token = self.credentials.get("auth_token") or self.credentials.get("api_key") or ""
        if not token:
            return ConnectorHealthCheck(
                status=ConnectorStatus.UNHEALTHY,
                message="Missing Sentry Auth Token",
            )
        headers = self._get_headers(self.credentials)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://sentry.io/api/0/api-tokens/", headers=headers)
                if res.status_code in (200, 403):
                    return ConnectorHealthCheck(status=ConnectorStatus.HEALTHY, message="Sentry connection active")
                return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=str(e))

    async def op_execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        creds = self.credentials or {}
        token = creds.get("auth_token") or creds.get("api_key") or ""
        if not token:
            raise make_connector_error("Sentry Auth Token is required.", code=ConnectorErrorCode.CONFIG_MISSING)

        org_slug = params.get("organization_slug") or creds.get("organization_slug") or ""
        headers = self._get_headers(creds)
        base_url = "https://sentry.io/api/0"
        timeout = float(params.get("timeout_seconds", 30.0))

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if operation == "list_issues":
                    project_slug = params.get("project_slug", "")
                    query = params.get("query", "is:unresolved")
                    endpoint = f"{base_url}/projects/{org_slug}/{project_slug}/issues/" if (org_slug and project_slug) else f"{base_url}/organizations/{org_slug}/issues/"
                    res = await client.get(endpoint, headers=headers, params={"query": query})
                    res.raise_for_status()
                    return {"issues": res.json()}

                elif operation == "get_issue":
                    issue_id = params.get("issue_id", "").strip()
                    res = await client.get(f"{base_url}/issues/{issue_id}/", headers=headers)
                    res.raise_for_status()
                    return res.json()

                elif operation == "resolve_issue":
                    issue_id = params.get("issue_id", "").strip()
                    status_val = params.get("status", "resolved")
                    res = await client.put(f"{base_url}/issues/{issue_id}/", headers=headers, json={"status": status_val})
                    res.raise_for_status()
                    return res.json()

                elif operation == "health_check":
                    check = await self.op_health_check()
                    return check.model_dump()

                else:
                    raise make_connector_error(f"Unsupported Sentry operation: {operation}", code=ConnectorErrorCode.VALIDATION_FAILED)
            except httpx.HTTPStatusError as e:
                raise make_connector_error(f"Sentry API error: {e.response.text}", code=ConnectorErrorCode.REMOTE_ERROR)
            except Exception as e:
                raise make_connector_error(str(e), code=ConnectorErrorCode.EXECUTION_FAILED)
