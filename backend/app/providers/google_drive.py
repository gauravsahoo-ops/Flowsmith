"""Google Drive provider client (Phase 11 business connectors).

Drive v3 over the shared Google OAuth app (config_prefix=google):

    GoogleDrive connector (op_execute)
        -> GoogleDriveProviderClient (this module)
            -> BaseProviderClient (token cache + 401 retry + taxonomy)
                -> SafeHTTPClient (SSRF-protected) -> Drive API

Pagination: list_files walks ``nextPageToken`` up to ``max_pages`` so a
workflow sees a bounded but deep view of a folder.
"""

from __future__ import annotations

import base64

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings as _get_settings
from app.providers.base import BaseProviderClient, json_error_message

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

_extract_drive_error = json_error_message("error", "message")


class GoogleDriveProviderClient(BaseProviderClient):
    api_base = DRIVE_API_BASE
    token_url = "https://oauth2.googleapis.com/token"

    def _client_id_secret(self) -> tuple[str, str]:
        s = _get_settings()
        return s.google_client_id, s.google_client_secret

    @staticmethod
    def _creds(creds: dict) -> dict:
        if not str((creds or {}).get("refresh_token") or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google Drive connector needs a 'google_drive' credential — connect it from the UI.",
                retryable=False,
            )
        return creds

    async def list_files(
        self,
        creds: dict,
        folder_id: str = "",
        page_size: int = 50,
        max_pages: int = 5,
        query_extra: str = "",
        timeout: float = 30.0,
    ) -> dict:
        """List files (optionally inside a folder), following nextPageToken."""
        page_size = min(max(int(page_size or 50), 1), 100)
        max_pages = min(max(int(max_pages or 1), 1), 20)
        clauses = ["trashed = false"]
        if folder_id:
            clauses.append(f"'{folder_id}' in parents")
        if query_extra:
            clauses.append(f"({query_extra})")
        params: dict = {
            "q": " and ".join(clauses),
            "pageSize": page_size,
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)",
            "orderBy": "modifiedTime desc",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        files: list[dict] = []
        next_token: str | None = None
        for _ in range(max_pages):
            page_params = dict(params)
            if next_token:
                page_params["pageToken"] = next_token
            response = await self.authorized_request(
                creds=self._creds(creds), method="GET",
                url=f"{DRIVE_API_BASE}/files", params=page_params,
                timeout=timeout, what="list files",
                extract_error_message=_extract_drive_error,
            )
            data = response.json()
            files.extend(data.get("files") or [])
            next_token = data.get("nextPageToken")
            if not next_token:
                break
        return {"files": files, "count": len(files), "has_more": bool(next_token)}

    async def get_file(self, creds: dict, file_id: str, timeout: float = 30.0) -> dict:
        response = await self.authorized_request(
            creds=self._creds(creds), method="GET",
            url=f"{DRIVE_API_BASE}/files/{file_id}",
            params={"supportsAllDrives": "true",
                    "fields": "id, name, mimeType, size, modifiedTime, webViewLink, parents"},
            timeout=timeout, what="get file",
            extract_error_message=_extract_drive_error,
        )
        return {"file": response.json()}

    async def upload_file(
        self,
        creds: dict,
        name: str,
        content: str,
        mime_type: str = "text/plain",
        folder_id: str = "",
        is_base64: bool = False,
        timeout: float = 60.0,
    ) -> dict:
        """Create a file with media content (uploadType=multipart).

        ``content`` is the text body, or base64 when ``is_base64`` —
        enough for reports/CSV/JSON exports; binary blobs should go
        through a dedicated storage path instead.
        """
        name = str(name or "").strip()
        if not name:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=upload requires a file name.", retryable=False)
        try:
            body = base64.b64decode(content) if is_base64 else content.encode("utf-8")
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid base64 content: {exc}", retryable=False,
            ) from exc

        boundary = "_automate_boundary_7f3d9"
        metadata_parts = [
            f'--{boundary}',
            "Content-Type: application/json; charset=UTF-8",
            "",
            '{"name": "%s"%s}' % (
                name.replace("\\", "\\\\").replace('"', '\\"'),
                f', "parents": ["{folder_id}"]' if folder_id else "",
            ),
        ]
        multipart = (
            "\r\n".join(metadata_parts).encode("utf-8")
            + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode("utf-8")
            + body
            + f"\r\n--{boundary}--".encode("utf-8")
        )
        # Raw call (not authorized_request) so the multipart bytes stay
        # intact — authorized_request only builds JSON/form bodies.
        token = await self._get_access_token(self._creds(creds))
        from app.security.safe_http_client import get_safe_http_client

        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST",
                    f"{DRIVE_UPLOAD_BASE}/files",
                    params={"uploadType": "multipart", "supportsAllDrives": "true"},
                    data=multipart,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": f"multipart/related; boundary={boundary}",
                    },
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Drive upload failed: {exc}", retryable=True,
            ) from exc
        if response.status_code == 401:
            self.reset()
        if response.status_code >= 400:
            code, retryable = self._map_status_error(response.status_code, "upload")
            raise make_connector_error(
                code,
                f"Upload failed ({response.status_code}). {_extract_drive_error(response)}".strip(),
                retryable=retryable,
            )
        data = response.json()
        return {"file_id": data.get("id", ""), "name": data.get("name", name), "success": True}
