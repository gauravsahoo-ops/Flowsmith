"""GitLab provider client (Batch B, original implementation).

Personal-access-token via PRIVATE-TOKEN header. Self-hosted hosts
allowed (host field). Ops: list/get project issues, create issue,
add note, list merge requests. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

DEFAULT_HOST = "https://gitlab.com"


def _auth(creds: dict) -> tuple[str, dict[str, str]]:
    token = str((creds or {}).get("access_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "GitLab connector needs a 'gitlab' credential with access_token.",
            retryable=False,
        )
    host = str((creds or {}).get("host") or DEFAULT_HOST).strip().rstrip("/") or DEFAULT_HOST
    if not host.startswith("https://"):
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "GitLab host must be https.", retryable=False)
    return host, {"PRIVATE-TOKEN": token, "Accept": "application/json"}


def _raise(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"GitLab auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"GitLab forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"GitLab resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"GitLab rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"GitLab unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"GitLab rejected {what}: {body[:200]}", retryable=False)


class GitLabProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (/user)."""
        data = await self._request("GET", "/user", creds, what="test connection")
        name = data.get("username", "") if isinstance(data, dict) else ""
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _request(
        self, method: str, path: str, creds: dict, *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0, what: str,
    ) -> Any:
        host, headers = _auth(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{host}/api/v4{path}", headers=headers,
                    params=params or {}, json=json_body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"GitLab unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise(response.status_code, response.text, what)
        try:
            return response.json()
        except Exception:
            return {}

    @staticmethod
    def _pid(project_id: str) -> str:
        pid = str(project_id or "").strip()
        if not pid:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A project_id is required.", retryable=False)
        return quote(pid, safe="")

    async def list_issues(self, creds: dict, project_id: str, timeout: float = 30.0) -> list:
        data = await self._request("GET", f"/projects/{self._pid(project_id)}/issues", creds, timeout=timeout, what="list issues")
        return data if isinstance(data, list) else []

    async def get_issue(self, creds: dict, project_id: str, issue_iid: str, timeout: float = 30.0) -> dict:
        if not str(issue_iid or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_issue needs an issue_iid.", retryable=False)
        data = await self._request(
            "GET", f"/projects/{self._pid(project_id)}/issues/{str(issue_iid).strip()}",
            creds, timeout=timeout, what="get issue",
        )
        return data if isinstance(data, dict) else {}

    async def create_issue(self, creds: dict, project_id: str, title: str, description: str = "", timeout: float = 30.0) -> dict:
        if not str(title or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_issue needs a title.", retryable=False)
        data = await self._request(
            "POST", f"/projects/{self._pid(project_id)}/issues", creds,
            json_body={"title": title.strip(), "description": description or ""},
            timeout=timeout, what="create issue",
        )
        return data if isinstance(data, dict) else {}

    async def add_note(self, creds: dict, project_id: str, issue_iid: str, body: str, timeout: float = 30.0) -> dict:
        if not str(issue_iid or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs an issue_iid.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_note needs body text.", retryable=False)
        data = await self._request(
            "POST", f"/projects/{self._pid(project_id)}/issues/{str(issue_iid).strip()}/notes", creds,
            json_body={"body": body.strip()}, timeout=timeout, what="add note",
        )
        return data if isinstance(data, dict) else {}

    async def list_merge_requests(self, creds: dict, project_id: str, timeout: float = 30.0) -> list:
        data = await self._request(
            "GET", f"/projects/{self._pid(project_id)}/merge_requests", creds,
            params={"state": "opened"}, timeout=timeout, what="list merge requests",
        )
        return data if isinstance(data, list) else []
