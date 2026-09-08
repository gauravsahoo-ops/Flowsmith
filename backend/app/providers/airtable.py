"""Airtable provider client (Phase 11 business connectors).

Personal-access-token auth against ``api.airtable.com/v0``.

Pagination: list_records follows the opaque ``offset`` cursor Airtable
returns until exhausted or ``max_pages`` is hit.
"""

from __future__ import annotations

import re
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message

AIRTABLE_API_BASE = "https://api.airtable.com/v0"
_ID_RE = re.compile(r"^app[A-Za-z0-9]{6,}$")
_REC_RE = re.compile(r"^rec[A-Za-z0-9]{6,}$")
_TBL_SAFE = re.compile(r"^[^/]+$")
_extract_airtable_error = json_error_message("message", "error")


def _base_id(value: str) -> str:
    vid = str(value or "").strip()
    if not _ID_RE.match(vid):
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "An Airtable base id looks like appXXXXXXXXXXXX.", retryable=False)
    return vid


class AirtableProviderClient(BaseProviderClient):
    api_base = AIRTABLE_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:  # pragma: no cover
        raise NotImplementedError("Airtable uses personal access tokens.")

    @staticmethod
    def _creds(creds: dict) -> dict:
        if not str((creds or {}).get("personal_access_token") or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Airtable connector needs an 'airtable' credential with a personal access token.",
                retryable=False,
            )
        return creds

    @staticmethod
    def _table(value: str) -> str:
        table = str(value or "").strip()
        if not table or not _TBL_SAFE.match(table):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A table name/id is required.", retryable=False)
        from urllib.parse import quote

        return quote(table, safe="")

    async def request_airtable(self, creds: dict, method: str, path: str, *,
                               json_body: dict | None = None, params: dict | None = None,
                               timeout: float = 30.0, what: str = "request"):
        response = await self.authorized_request(
            creds=self._creds(creds), method=method,
            url=f"{AIRTABLE_API_BASE}{path}", json_body=json_body, params=params,
            private_token_field="personal_access_token",
            timeout=timeout, what=what,
            extract_error_message=_extract_airtable_error,
        )
        if response.status_code == 429:
            delay = response.headers.get("Retry-After")
            raise make_connector_error(
                ConnectorErrorCode.RATE_LIMITED, f"Airtable {what} rate limited.",
                retryable=True, retry_after=float(delay) if delay else None,
            )
        if response.status_code >= 400:
            code, retryable = self._map_status_error(response.status_code, what)
            raise make_connector_error(
                code,
                f"Airtable {what} failed ({response.status_code}). {_extract_airtable_error(response)}".strip(),
                retryable=retryable,
            )
        return response

    async def list_records(self, creds: dict, base_id: str, table_name: str,
                           view: str = "", filter_by_formula: str = "",
                           page_size: int = 100, max_pages: int = 3,
                           timeout: float = 30.0) -> dict:
        bid = _base_id(base_id)
        tbl = self._table(table_name)
        page_size = min(max(int(page_size or 100), 1), 100)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        records: list[dict] = []
        offset: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"pageSize": page_size}
            if offset:
                params["offset"] = offset
            if view:
                params["view"] = view
            if filter_by_formula:
                params["filterByFormula"] = filter_by_formula
            response = await self.request_airtable(
                creds, "GET", f"/{bid}/{tbl}", params=params,
                timeout=timeout, what="list records",
            )
            data = response.json()
            records.extend(data.get("records") or [])
            offset = data.get("offset")
            if not offset:
                break
        return {"records": records, "count": len(records)}

    async def get_record(self, creds: dict, base_id: str, table_name: str,
                         record_id: str, timeout: float = 30.0) -> dict:
        bid = _base_id(base_id)
        tbl = self._table(table_name)
        rid = str(record_id or "").strip()
        if not _REC_RE.match(rid):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A record id looks like recXXXXXXXXXXXX.", retryable=False)
        response = await self.request_airtable(
            creds, "GET", f"/{bid}/{tbl}/{rid}", timeout=timeout, what="get record",
        )
        return {"record": response.json()}

    async def create_record(self, creds: dict, base_id: str, table_name: str,
                            fields: dict, timeout: float = 30.0) -> dict:
        bid = _base_id(base_id)
        tbl = self._table(table_name)
        if not isinstance(fields, dict) or not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_record requires a fields map.", retryable=False)
        response = await self.request_airtable(
            creds, "POST", f"/{bid}/{tbl}", json_body={"fields": fields},
            timeout=timeout, what="create record",
        )
        record = response.json()
        return {"record_id": record.get("id", ""), "fields": record.get("fields", {}), "success": True}

    async def update_record(self, creds: dict, base_id: str, table_name: str,
                            record_id: str, fields: dict, timeout: float = 30.0) -> dict:
        bid = _base_id(base_id)
        tbl = self._table(table_name)
        rid = str(record_id or "").strip()
        if not _REC_RE.match(rid):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A record id looks like recXXXXXXXXXXXX.", retryable=False)
        if not isinstance(fields, dict) or not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_record requires a fields map.", retryable=False)
        response = await self.request_airtable(
            creds, "PATCH", f"/{bid}/{tbl}/{rid}", json_body={"fields": fields},
            timeout=timeout, what="update record",
        )
        record = response.json()
        return {"record_id": record.get("id", ""), "fields": record.get("fields", {}), "success": True}
