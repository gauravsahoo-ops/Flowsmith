"""Box cloud content management provider client (Phase 39).

Integrates with Box REST API v2:
https://api.box.com/2.0 and https://upload.box.com/api/2.0

Supports:
- test_connection (GET /users/me)
- list_folder_items (GET /folders/{folder_id}/items)
- get_file (GET /files/{file_id})
- create_folder (POST /folders)
- delete_file (DELETE /files/{file_id})
- search (GET /search)
- upload_file (POST https://upload.box.com/api/2.0/files/content)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.box")
_extract_box_error = json_error_message("message", "code")

BOX_API_BASE = "https://api.box.com/2.0"
BOX_UPLOAD_BASE = "https://upload.box.com/api/2.0"


class BoxProviderClient(BaseProviderClient):
    """Client for Box REST API v2."""

    api_base = BOX_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Box connector uses Bearer access tokens or OAuth refresh.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        token = str(creds.get("access_token") or creds.get("token") or creds.get("api_key") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Box connector requires an 'access_token' or 'token'.",
                retryable=False,
            )
        return token

    async def request_box(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        is_upload: bool = False,
        timeout: float = 60.0,
    ) -> Any:
        token = self._validate_creds(creds)
        base = BOX_UPLOAD_BASE if is_upload else self.api_base
        url = f"{base}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            async with get_safe_http_client() as client:
                if files or data:
                    resp = await client.request(
                        method.upper(),
                        url,
                        headers=headers,
                        params=params,
                        data=data,
                        files=files,
                        timeout=timeout,
                    )
                else:
                    if json_body is not None:
                        headers["Content-Type"] = "application/json"
                    resp = await client.request(
                        method.upper(),
                        url,
                        headers=headers,
                        params=params,
                        json=json_body if json_body is not None else None,
                        timeout=timeout,
                    )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Box request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Box request failed: {exc}", retryable=True) from exc

        if resp.status_code == 204:
            return {"deleted": True, "status_code": 204}

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_box_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Box bad request: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Box access token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Box forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Box resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 409:
            msg = _extract_box_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Box conflict: {msg}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Box rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Box service unavailable: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        return await self.request_box(creds, "GET", "users/me")

    async def list_folder_items(
        self,
        creds: dict[str, Any],
        folder_id: str = "0",
        *,
        limit: int = 100,
        offset: int = 0,
        fields: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if fields:
            params["fields"] = fields
        path = f"folders/{folder_id}/items"
        return await self.request_box(creds, "GET", path, params=params, timeout=timeout)

    async def get_file(
        self,
        creds: dict[str, Any],
        file_id: str,
        *,
        fields: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params = {"fields": fields} if fields else None
        return await self.request_box(creds, "GET", f"files/{file_id}", params=params, timeout=timeout)

    async def create_folder(
        self,
        creds: dict[str, Any],
        name: str,
        parent_id: str = "0",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {
            "name": name,
            "parent": {"id": parent_id},
        }
        return await self.request_box(creds, "POST", "folders", json_body=body, timeout=timeout)

    async def delete_file(
        self,
        creds: dict[str, Any],
        file_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_box(creds, "DELETE", f"files/{file_id}", timeout=timeout)

    async def search(
        self,
        creds: dict[str, Any],
        query: str,
        *,
        limit: int = 30,
        offset: int = 0,
        type_filter: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        if type_filter:
            params["type"] = type_filter
        return await self.request_box(creds, "GET", "search", params=params, timeout=timeout)

    async def upload_file(
        self,
        creds: dict[str, Any],
        name: str,
        content: str | bytes,
        parent_id: str = "0",
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        attributes = {"name": name, "parent": {"id": parent_id}}
        raw_bytes = content.encode("utf-8") if isinstance(content, str) else content
        files = {
            "attributes": (None, json.dumps(attributes), "application/json"),
            "file": (name, raw_bytes, "application/octet-stream"),
        }
        return await self.request_box(creds, "POST", "files/content", files=files, is_upload=True, timeout=timeout)
