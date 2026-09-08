"""Jira Cloud provider client (Phase 11 business connectors).

Basic auth (email + API token) against ``{site}/rest/api/3``. The site
comes from the credential (e.g. ``https://acme.atlassian.net``) and is
validated so it can never smuggle a different host.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any
from urllib.parse import urlparse

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import json_error_message
from app.security.safe_http_client import get_safe_http_client

JIRA_API_PATH = "/rest/api/3"
_ISSUE_KEY_RE = __import__("re").compile(r"^[A-Z][A-Z0-9]*-\d+$")
_extract_jira_error = json_error_message("errorMessages", "message")


def _require_creds(creds: dict) -> tuple[str, str, str]:
    site = str((creds or {}).get("site_url") or "").strip().rstrip("/")
    email = str(creds.get("email") or "").strip()
    token = str(creds.get("api_token") or "").strip()
    if not (site and email and token):
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Jira connector needs a 'jira' credential with site_url, email and api_token.",
            retryable=False,
        )
    parsed = urlparse(site)
    if parsed.scheme != "https" or not parsed.hostname:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Jira site_url must be an https URL, e.g. https://acme.atlassian.net.",
            retryable=False,
        )
    return site, email, token


def _basic_header(email: str, token: str) -> str:
    raw = base64.b64encode(f"{email}:{token}".encode()).decode()
    return f"Basic {raw}"


class JiraProviderClient:
    """Low-level Jira REST v3 client (no OAuth machinery needed)."""

    async def request_jira(
        self, creds: dict, method: str, path: str, *,
        json_body: dict | None = None, params: dict | None = None,
        timeout: float = 30.0, what: str = "request",
    ) -> httpx.Response:
        site, email, token = _require_creds(creds)
        try:
            header = _basic_header(email, token)
        except (binascii.Error, UnicodeEncodeError) as exc:  # pragma: no cover
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED, "Jira credential could not be encoded.", retryable=False,
            ) from exc
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{site}{JIRA_API_PATH}{path}",
                    json=json_body or None, params=params or None,
                    headers={
                        "Authorization": header,
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Jira unreachable: {exc}", retryable=True,
            ) from exc
        if response.status_code >= 400:
            code_map = {
                401: ConnectorErrorCode.AUTH_FAILED,
                403: ConnectorErrorCode.FORBIDDEN,
                404: ConnectorErrorCode.NOT_FOUND,
            }
            retryable = response.status_code == 429 or response.status_code >= 500
            code = (
                ConnectorErrorCode.RATE_LIMITED
                if response.status_code == 429
                else code_map.get(response.status_code, ConnectorErrorCode.BAD_REQUEST)
            )
            raise make_connector_error(
                code,
                f"Jira {what} failed ({response.status_code}). {_extract_jira_error(response)}".strip(),
                retryable=retryable,
            )
        return response

    async def search(self, creds: dict, jql: str, max_results: int = 50,
                     max_pages: int = 3, timeout: float = 30.0) -> dict:
        query = str(jql or "").strip()
        if not query:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=search requires a JQL query.", retryable=False)
        max_results = min(max(int(max_results or 50), 1), 100)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        issues: list[dict] = []
        start_at = 0
        total: int | None = None
        for _ in range(max_pages):
            response = await self.request_jira(
                creds, "GET", "/search",
                params={"jql": query, "startAt": start_at, "maxResults": max_results,
                        "fields": "summary,status,assignee,issuetype,priority"},
                timeout=timeout, what="search",
            )
            data = response.json()
            batch = [
                {
                    "key": i.get("key"),
                    "summary": ((i.get("fields") or {}).get("summary")),
                    "status": (((i.get("fields") or {}).get("status") or {}).get("name")),
                    "issue_type": (((i.get("fields") or {}).get("issuetype") or {}).get("name")),
                    "url": f"{_require_creds(creds)[0]}/browse/{i.get('key')}",
                }
                for i in data.get("issues", [])
            ]
            issues.extend(batch)
            total = int(data.get("total", len(issues)))
            start_at += len(batch)
            if not batch or start_at >= total:
                break
        return {"issues": issues, "count": len(issues), "total": total}

    async def create_issue(self, creds: dict, project_key: str, issue_type: str,
                           summary: str, description: str = "",
                           extra_fields: dict | None = None, timeout: float = 30.0) -> dict:
        project = str(project_key or "").strip()
        itype = str(issue_type or "").strip() or "Task"
        title = str(summary or "").strip()
        if not project or not title:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "create_issue requires project_key and summary.",
                retryable=False,
            )
        fields: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": itype},
            "summary": title,
        }
        if description:
            fields["description"] = {
                "type": "doc", "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }],
            }
        if extra_fields:
            fields.update(extra_fields)
        response = await self.request_jira(
            creds, "POST", "/issue", json_body={"fields": fields},
            timeout=timeout, what="create issue",
        )
        data = response.json()
        return {"key": data.get("key", ""), "id": data.get("id", ""), "success": True}

    async def update_issue(self, creds: dict, issue_key: str, fields: dict,
                           timeout: float = 30.0) -> dict:
        key = self._issue_key(issue_key)
        if not isinstance(fields, dict) or not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_issue requires a fields map.", retryable=False)
        await self.request_jira(
            creds, "PUT", f"/issue/{key}", json_body={"fields": fields},
            timeout=timeout, what="update issue",
        )
        return {"key": key, "success": True}

    async def add_comment(self, creds: dict, issue_key: str, body: str,
                          timeout: float = 30.0) -> dict:
        key = self._issue_key(issue_key)
        text = str(body or "").strip()
        if not text:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment requires a body.", retryable=False)
        response = await self.request_jira(
            creds, "POST", f"/issue/{key}/comment",
            json_body={"body": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }]},
            timeout=timeout, what="add comment",
        )
        data = response.json()
        return {"comment_id": data.get("id", ""), "key": key, "success": True}

    @staticmethod
    def _issue_key(value: str) -> str:
        key = str(value or "").strip().upper()
        if not _ISSUE_KEY_RE.match(key):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "A Jira issue key looks like PROJ-123.", retryable=False,
            )
        return key
