"""GitHub REST provider client (Phase 11 business connectors).

Personal-access-token (PAT) or GitHub-App installation token auth.

Rate limits: GitHub returns 403 with ``X-RateLimit-Remaining: 0`` when a
secondary/primary budget is exhausted — mapped to RATE_LIMITED (retryable)
instead of FORBIDDEN so engine retries kick in.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message

GITHUB_API_BASE = "https://api.github.com"

_extract_github_error = json_error_message("message")


def _owner_repo(owner: str, repo: str) -> tuple[str, str]:
    owner_clean = str(owner or "").strip().strip("/")
    repo_clean = str(repo or "").strip().strip("/").removesuffix(".git")
    if not owner_clean or not repo_clean or any(c not in _SAFE for c in owner_clean + repo_clean):
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, "owner and repo must be plain names.", retryable=False,
        )
    return owner_clean, repo_clean


_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
_NUMBER_RE = re.compile(r"^\d+$")


class GitHubProviderClient(BaseProviderClient):
    api_base = GITHUB_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:  # pragma: no cover
        raise NotImplementedError("GitHub uses static access tokens.")

    @staticmethod
    def _creds(creds: dict) -> dict:
        token = str((creds or {}).get("access_token") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "GitHub connector needs a 'github' credential with an access token.",
                retryable=False,
            )
        return creds

    async def request_github(
        self, creds: dict, method: str, path: str, *,
        json_body: dict | None = None, params: dict | None = None,
        timeout: float = 30.0, what: str = "request",
    ):
        def _check_rate_limit(response) -> None:
            """Primary/secondary budget exhaustion arrives as 403 with a
            zero remaining-budget header — retryable, unlike plain 403."""
            if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
                reset_header = response.headers.get("X-RateLimit-Reset")
                delay = max(float(reset_header) - time.time(), 1.0) if reset_header else None
                raise make_connector_error(
                    ConnectorErrorCode.RATE_LIMITED,
                    "GitHub API rate limit exhausted.",
                    retryable=True,
                    retry_after=min(delay, 60.0) if delay else None,
                )

        response = await self.authorized_request(
            creds=self._creds(creds), method=method,
            url=f"{GITHUB_API_BASE}{path}", json_body=json_body, params=params,
            private_token_field="access_token", timeout=timeout, what=what,
            headers_extra={"X-GitHub-Api-Version": "2022-11-28"},
            extract_error_message=_extract_github_error,
            on_response=_check_rate_limit,
        )
        if response.status_code >= 400:
            code, retryable = self._map_status_error(response.status_code, what)
            raise make_connector_error(
                code,
                f"GitHub {what} failed ({response.status_code}). {_extract_github_error(response)}".strip(),
                retryable=retryable,
            )
        return response

    async def get_repo(self, creds: dict, owner: str, repo: str, timeout: float = 30.0) -> dict:
        o, r = _owner_repo(owner, repo)
        response = await self.request_github(
            creds, "GET", f"/repos/{o}/{r}", timeout=timeout, what="get repository",
        )
        data = response.json()
        return {
            "full_name": data.get("full_name"),
            "default_branch": data.get("default_branch"),
            "stars": data.get("stargazers_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "url": data.get("html_url"),
        }

    async def create_issue(
        self, creds: dict, owner: str, repo: str, title: str,
        body: str = "", labels: list[str] | None = None, timeout: float = 30.0,
    ) -> dict:
        o, r = _owner_repo(owner, repo)
        if not str(title or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_issue requires a title.", retryable=False)
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = [str(lb) for lb in labels]
        response = await self.request_github(
            creds, "POST", f"/repos/{o}/{r}/issues", json_body=payload,
            timeout=timeout, what="create issue",
        )
        data = response.json()
        return {"number": data.get("number"), "url": data.get("html_url"), "state": data.get("state")}

    async def add_comment(self, creds: dict, owner: str, repo: str, issue_number: int,
                          body: str, timeout: float = 30.0) -> dict:
        o, r = _owner_repo(owner, repo)
        number = str(issue_number or "").strip()
        if not _NUMBER_RE.match(number):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "issue_number must be numeric.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment requires a body.", retryable=False)
        response = await self.request_github(
            creds, "POST", f"/repos/{o}/{r}/issues/{number}/comments",
            json_body={"body": body}, timeout=timeout, what="add comment",
        )
        data = response.json()
        return {"comment_id": data.get("id"), "url": data.get("html_url")}

    async def list_issues(
        self, creds: dict, owner: str, repo: str, state: str = "open",
        per_page: int = 50, max_pages: int = 3, timeout: float = 30.0,
    ) -> dict:
        o, r = _owner_repo(owner, repo)
        if state not in ("open", "closed", "all"):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "state must be open|closed|all.", retryable=False)
        per_page = min(max(int(per_page or 50), 1), 100)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        issues: list[dict] = []
        for page in range(1, max_pages + 1):
            response = await self.request_github(
                creds, "GET", f"/repos/{o}/{r}/issues",
                params={
                    "state": state, "per_page": per_page, "page": page,
                    "sort": "updated", "direction": "desc",
                },
                timeout=timeout, what="list issues",
            )
            batch = [
                {
                    "number": i.get("number"), "title": i.get("title"), "state": i.get("state"),
                    "url": i.get("html_url"), "is_pr": "pull_request" in i,
                }
                for i in response.json()
            ]
            issues.extend(batch)
            if len(batch) < per_page:
                break
        return {"issues": issues, "count": len(issues)}
