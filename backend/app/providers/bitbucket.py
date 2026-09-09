"""Bitbucket provider client (Batch B, original implementation).

Bearer access-token auth. Ops: list workspace repos, get repo, list
pull requests, get pull request, add PR comment. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

BITBUCKET_API_BASE = "https://api.bitbucket.org/2.0"


def _token(creds: dict) -> str:
    token = str((creds or {}).get("access_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Bitbucket connector needs a 'bitbucket' credential with access_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Bitbucket auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Bitbucket forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Bitbucket resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Bitbucket rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Bitbucket unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Bitbucket rejected {what}: {body[:200]}", retryable=False)


class BitbucketProviderClient:
    async def _request(
        self, method: str, path: str, creds: dict, *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0, what: str,
    ) -> Any:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{BITBUCKET_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {_token(creds)}", "Accept": "application/json"},
                    params=params or {}, json=json_body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Bitbucket unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise(response.status_code, response.text, what)
        try:
            return response.json()
        except Exception:
            return {}

    @staticmethod
    def _repo_slug(workspace: str, repo: str) -> str:
        ws, slug = str(workspace or "").strip(), str(repo or "").strip()
        if not ws or not slug:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "workspace + repo_slug are required.", retryable=False)
        return f"{ws}/{slug}"

    async def list_repos(self, creds: dict, workspace: str, timeout: float = 30.0) -> list:
        if not str(workspace or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "list_repos needs a workspace.", retryable=False)
        data = await self._request("GET", f"/repositories/{str(workspace).strip()}", creds, what="list repos", timeout=timeout)
        items = data.get("values", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def get_repo(self, creds: dict, workspace: str, repo: str, timeout: float = 30.0) -> dict:
        data = await self._request("GET", f"/repositories/{self._repo_slug(workspace, repo)}", creds, what="get repo", timeout=timeout)
        return data if isinstance(data, dict) else {}

    async def list_pull_requests(self, creds: dict, workspace: str, repo: str, timeout: float = 30.0) -> list:
        data = await self._request(
            "GET", f"/repositories/{self._repo_slug(workspace, repo)}/pullrequests",
            creds, params={"state": "OPEN"}, what="list pull requests", timeout=timeout,
        )
        items = data.get("values", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def get_pull_request(self, creds: dict, workspace: str, repo: str, pr_id: str, timeout: float = 30.0) -> dict:
        if not str(pr_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_pull_request needs a pr_id.", retryable=False)
        data = await self._request(
            "GET", f"/repositories/{self._repo_slug(workspace, repo)}/pullrequests/{str(pr_id).strip()}",
            creds, what="get pull request", timeout=timeout,
        )
        return data if isinstance(data, dict) else {}

    async def add_comment(self, creds: dict, workspace: str, repo: str, pr_id: str, text: str, timeout: float = 30.0) -> dict:
        if not str(pr_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a pr_id.", retryable=False)
        if not str(text or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs text.", retryable=False)
        data = await self._request(
            "POST", f"/repositories/{self._repo_slug(workspace, repo)}/pullrequests/{str(pr_id).strip()}/comments",
            creds, json_body={"content": {"raw": text.strip()}}, what="add comment", timeout=timeout,
        )
        return data if isinstance(data, dict) else {}
