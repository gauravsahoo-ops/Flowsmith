"""Dropbox provider client.

Dropbox API v2 (api.dropboxapi.com) with Bearer OAuth access token.
Ops: list folder, get metadata, create folder, delete, upload small text
files. 429/5xx retryable; error_summary mapped to typed errors.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

DROPBOX_API_BASE = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT_BASE = "https://content.dropboxapi.com/2"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("access_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Dropbox connector needs a 'dropbox' credential with access_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        summary = payload.get("error_summary")
        if summary:
            detail = f": {str(summary)[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Dropbox auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Dropbox forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Dropbox path missing during {what}{detail}.", retryable=False)
    if status == 409:
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Dropbox endpoint error during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Dropbox rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Dropbox unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Dropbox rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class DropboxProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (current account)."""
        data = await self._rpc(creds, "/users/get_current_account", {}, "test connection")
        name = ((data.get("name") or {}) if isinstance(data, dict) else {}).get("display_name", "")
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _rpc(self, creds: dict, path: str, body: dict[str, Any], what: str, timeout: float = 30.0) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", f"{DROPBOX_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {_key(creds)}", "Content-Type": "application/json"},
                    json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Dropbox unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def list_folder(self, creds: dict, path: str = "", limit: int = 25, timeout: float = 30.0) -> dict:
        return await self._rpc(creds, "/files/list_folder",
                               {"path": path or "", "recursive": False, "limit": max(1, min(int(limit or 25), 2000))},
                               "list_folder", timeout)

    async def get_metadata(self, creds: dict, path: str, timeout: float = 30.0) -> dict:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_metadata needs a path.", retryable=False)
        return await self._rpc(creds, "/files/get_metadata", {"path": path}, "get_metadata", timeout)

    async def create_folder(self, creds: dict, path: str, timeout: float = 30.0) -> dict:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_folder needs a path.", retryable=False)
        return await self._rpc(creds, "/files/create_folder_v2", {"path": path, "autorename": False}, "create_folder", timeout)

    async def delete(self, creds: dict, path: str, timeout: float = 30.0) -> dict:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "delete needs a path.", retryable=False)
        return await self._rpc(creds, "/files/delete_v2", {"path": path}, "delete", timeout)

    async def upload_text(self, creds: dict, path: str, content: str, timeout: float = 60.0) -> dict:
        import json as _json

        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "upload_text needs a path.", retryable=False)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", f"{DROPBOX_CONTENT_BASE}/files/upload",
                    headers={
                        "Authorization": f"Bearer {_key(creds)}",
                        "Content-Type": "application/octet-stream",
                        "Dropbox-API-Arg": _json.dumps({"path": path, "mode": "overwrite"}),
                    },
                    data=str(content or "").encode("utf-8"),
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Dropbox unreachable during upload_text: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "upload_text", payload)
        return payload if isinstance(payload, dict) else {}
