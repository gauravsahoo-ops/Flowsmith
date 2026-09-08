"""Google Sheets provider client (Phase 39, refactored onto BaseProviderClient).

Sheets v4 values API over shared Google OAuth machinery:

    GoogleSheets connector (op_execute)
        -> GoogleSheetsProviderClient (this module)
            -> BaseProviderClient (token cache + 401 retry + taxonomy)
                -> SafeHTTPClient (SSRF-protected) -> Sheets API
"""

from __future__ import annotations

import re

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings as _get_settings
from app.providers.base import BaseProviderClient

SHEETS_API_BASE = "https://sheets.googleapis.com/v4"


def _sheets_error_message(response) -> str:
    try:
        data = response.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            return str(err.get("message", ""))[:300]
    except Exception:
        pass
    return ""
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class GoogleSheetsProviderClient(BaseProviderClient):
    api_base = SHEETS_API_BASE
    token_url = "https://oauth2.googleapis.com/token"

    def _client_id_secret(self) -> tuple[str, str]:
        s = _get_settings()
        return s.google_client_id, s.google_client_secret

    # ------------------------------------------------------------------

    @staticmethod
    def _spreadsheet_id(value: str) -> str:
        vid = str(value or "").strip()
        if not _ID_RE.match(vid):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Invalid spreadsheet id.", retryable=False)
        return vid

    @staticmethod
    def _creds(creds: dict) -> dict:
        rt = str((creds or {}).get("refresh_token") or "").strip()
        if not rt:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google Sheets connector needs a 'google_sheets' credential — connect it from the UI.",
                retryable=False,
            )
        return creds

    async def read_values(self, creds, spreadsheet_id: str, range_: str, timeout: float = 30.0) -> dict:
        sid = self._spreadsheet_id(spreadsheet_id)
        response = await self.authorized_request(
            creds=self._creds(creds), method="GET",
            url=f"{SHEETS_API_BASE}/spreadsheets/{sid}/values/{range_}",
            params={"majorDimension": "ROWS"}, timeout=timeout,
            what="read",
            extract_error_message=_sheets_error_message,
        )
        data = response.json()
        rows = data.get("values") or []
        return {"rows": rows, "count": len(rows), "range": data.get("range", range_)}

    async def append_row(self, creds, spreadsheet_id: str, range_: str, values: list, timeout: float = 30.0) -> dict:
        sid = self._spreadsheet_id(spreadsheet_id)
        response = await self.authorized_request(
            creds=self._creds(creds), method="POST",
            url=f"{SHEETS_API_BASE}/spreadsheets/{sid}/values/{range_}:append",
            json_body={"values": [values]},
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            timeout=timeout,
            what="append",
        )
        updates = response.json().get("updates", {})
        return {"appended": True, "updated_cells": updates.get("updatedCells", 0),
                "range": updates.get("updatedRange", "")}

    async def update_values(self, creds, spreadsheet_id: str, range_: str, values: list[list], timeout: float = 30.0) -> dict:
        sid = self._spreadsheet_id(spreadsheet_id)
        response = await self.authorized_request(
            creds=self._creds(creds), method="PUT",
            url=f"{SHEETS_API_BASE}/spreadsheets/{sid}/values/{range_}",
            json_body={"values": values},
            params={"valueInputOption": "USER_ENTERED"},
            timeout=timeout,
            what="update",
        )
        data = response.json()
        return {"updated_cells": data.get("updatedCells", 0), "updated_rows": data.get("updatedRows", 0), "success": True}
