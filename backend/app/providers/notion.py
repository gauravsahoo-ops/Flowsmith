"""Notion provider client (Phase 11 business connectors).

Internal-integration token auth (``secret_…`` / ``ntn_…``). Pages the
connector can touch are exactly those shared with the integration.

Pagination: ``query_database`` follows ``start_cursor``/``has_more``.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message

NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,}$")
_extract_notion_error = json_error_message("message")


class NotionProviderClient(BaseProviderClient):
    api_base = NOTION_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:  # pragma: no cover
        raise NotImplementedError("Notion uses static integration tokens.")

    @staticmethod
    def _creds(creds: dict) -> dict:
        if not str((creds or {}).get("integration_token") or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Notion connector needs a 'notion' credential with an integration token.",
                retryable=False,
            )
        return creds

    async def request_notion(
        self, creds: dict, method: str, path: str, *,
        json_body: dict | None = None, params: dict | None = None,
        timeout: float = 30.0, what: str = "request",
    ) -> httpx.Response:
        def _check_rate_limit(response) -> None:
            retry_after_header = response.headers.get("Retry-After")
            if response.status_code == 429:
                raise make_connector_error(
                    ConnectorErrorCode.RATE_LIMITED,
                    f"Notion {what} rate limited.",
                    retryable=True,
                    retry_after=float(retry_after_header) if retry_after_header else None,
                )
            if response.status_code in (400, 409) and "rate_limited" in response.text:
                raise make_connector_error(
                    ConnectorErrorCode.RATE_LIMITED, f"Notion {what} rate limited.", retryable=True,
                )

        response = await self.authorized_request(
            creds=self._creds(creds), method=method,
            url=f"{NOTION_API_BASE}{path}", json_body=json_body, params=params,
            private_token_field="integration_token",
            headers_extra={"Notion-Version": _NOTION_VERSION},
            timeout=timeout, what=what,
            extract_error_message=_extract_notion_error,
            on_response=_check_rate_limit,
        )
        return response

    @staticmethod
    def _object_id(value: str, label: str) -> str:
        vid = str(value or "").replace("-", "").strip()
        if not _ID_RE.match(vid):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Notion {label} id.", retryable=False,
            )
        return vid

    async def query_database(
        self, creds: dict, database_id: str, filter_obj: dict | None = None,
        page_size: int = 50, max_pages: int = 3, timeout: float = 30.0,
    ) -> dict:
        db_id = self._object_id(database_id, "database")
        page_size = min(max(int(page_size or 50), 1), 100)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        pages: list[dict] = []
        cursor: str | None = None
        has_more = False
        for _ in range(max_pages):
            body: dict[str, Any] = {"page_size": page_size}
            if filter_obj:
                body["filter"] = filter_obj
            if cursor:
                body["start_cursor"] = cursor
            response = await self.request_notion(
                creds, "POST", f"/databases/{db_id}/query", json_body=body,
                timeout=timeout, what="query database",
            )
            data = response.json()
            pages.extend(self._summarize_pages(data.get("results") or []))
            has_more = bool(data.get("has_more"))
            cursor = data.get("next_cursor")
            if not has_more or not cursor:
                break
        return {"pages": pages, "count": len(pages), "has_more": has_more}

    @staticmethod
    def _summarize_pages(results: list[dict]) -> list[dict]:
        summarized = []
        for page in results:
            props_out: dict[str, Any] = {}
            for name, prop in (page.get("properties") or {}).items():
                ptype = prop.get("type")
                if ptype == "title":
                    items = prop.get("title") or []
                    props_out[name] = "".join(t.get("plain_text", "") for t in items)
                elif ptype == "rich_text":
                    items = prop.get("rich_text") or []
                    props_out[name] = "".join(t.get("plain_text", "") for t in items)
                elif ptype in ("number", "checkbox", "url", "email"):
                    props_out[name] = prop.get(ptype)
                elif ptype == "select":
                    props_out[name] = ((prop.get("select") or {}).get("name"))
                elif ptype == "status":
                    props_out[name] = ((prop.get("status") or {}).get("name"))
                elif ptype == "date":
                    props_out[name] = (prop.get("date") or {}).get("start")
            summarized.append({"id": page.get("id"), "url": page.get("url"), "properties": props_out})
        return summarized

    async def create_page(self, creds: dict, database_id: str, properties: dict,
                          timeout: float = 30.0) -> dict:
        db_id = self._object_id(database_id, "database")
        if not isinstance(properties, dict) or not properties:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "create_page requires a properties object (e.g. "
                '{"Name": {"title": [{"text": {"content": "Hi"}}]}}).',
                retryable=False,
            )
        response = await self.request_notion(
            creds, "POST", "/pages",
            json_body={"parent": {"database_id": db_id}, "properties": properties},
            timeout=timeout, what="create page",
        )
        page = response.json()
        return {"page_id": page.get("id", ""), "url": page.get("url", ""), "success": True}

    async def update_page(self, creds: dict, page_id: str, properties: dict | None = None,
                          archived: bool = False, timeout: float = 30.0) -> dict:
        pid = self._object_id(page_id, "page")
        if not properties and not archived:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "update_page requires properties or archived=true.",
                retryable=False,
            )
        body: dict[str, Any] = {"archived": bool(archived)}
        if properties:
            body["properties"] = properties
        response = await self.request_notion(
            creds, "PATCH", f"/pages/{pid}", json_body=body,
            timeout=timeout, what="update page",
        )
        page = response.json()
        return {"page_id": page.get("id", ""), "archived": page.get("archived", False), "success": True}
