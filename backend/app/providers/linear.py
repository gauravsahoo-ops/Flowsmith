"""Linear provider client (Batch B, original implementation).

GraphQL API with API-key Bearer auth. Ops: list team issues, get issue,
create issue, update issue, add comment. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

LINEAR_API_URL = "https://api.linear.app/graphql"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("api_key") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Linear connector needs a 'linear' credential with api_key.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, errors: list | None = None) -> None:
    if errors:
        msg = str(errors[0].get("message", ""))[:200] if isinstance(errors[0], dict) else str(errors[0])[:200]
        if "auth" in msg.lower() or status == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Linear auth failed during {what}.", retryable=False)
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Linear rejected {what}: {msg}", retryable=False)
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Linear auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Linear forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Linear resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Linear rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Linear unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Linear rejected {what}: {body[:200]}", retryable=False)


class LinearProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (viewer)."""
        data = await self._gql(
            creds, "query { viewer { id name } }", {}, "test connection",
        )
        viewer = data.get("viewer", {}) or {}
        name = viewer.get("name", "")
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _gql(self, creds: dict, query: str, variables: dict[str, Any], what: str, timeout: float = 30.0) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", LINEAR_API_URL,
                    headers={"Authorization": _key(creds), "Content-Type": "application/json"},
                    json={"query": query, "variables": variables}, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Linear unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload.get("errors") if isinstance(payload, dict) else None)
        return payload.get("data", {}) if isinstance(payload, dict) else {}

    async def list_issues(self, creds: dict, team_id: str, limit: int = 25, timeout: float = 30.0) -> list:
        if not str(team_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "list_issues needs a team_id.", retryable=False)
        data = await self._gql(
            creds,
            "query($teamId: String!, $first: Int!) { team(id: $teamId) { issues(first: $first) { nodes { id title state { name } } } } }",
            {"teamId": team_id.strip(), "first": max(1, min(limit, 100))}, "list issues", timeout,
        )
        try:
            return data["team"]["issues"]["nodes"]
        except Exception:
            return []

    async def get_issue(self, creds: dict, issue_id: str, timeout: float = 30.0) -> dict:
        if not str(issue_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_issue needs an issue_id.", retryable=False)
        data = await self._gql(
            creds, "query($id: String!) { issue(id: $id) { id title description state { name } } }",
            {"id": issue_id.strip()}, "get issue", timeout,
        )
        issue = data.get("issue", {})
        return issue if isinstance(issue, dict) else {}

    async def create_issue(self, creds: dict, team_id: str, title: str, description: str = "", timeout: float = 30.0) -> dict:
        if not str(team_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_issue needs a team_id.", retryable=False)
        if not str(title or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_issue needs a title.", retryable=False)
        data = await self._gql(
            creds,
            "mutation($teamId: String!, $title: String!, $desc: String) { issueCreate(input: {teamId: $teamId, title: $title, description: $desc}) { issue { id title } success } }",
            {"teamId": team_id.strip(), "title": title.strip(), "desc": description or ""}, "create issue", timeout,
        )
        issue = (data.get("issueCreate") or {}).get("issue", {})
        return issue if isinstance(issue, dict) else {}

    async def update_issue(self, creds: dict, issue_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(issue_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_issue needs an issue_id.", retryable=False)
        allowed = {k: v for k, v in (fields or {}).items() if k in ("title", "description") and str(v or "").strip()}
        if not allowed:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_issue needs title and/or description.", retryable=False)
        data = await self._gql(
            creds,
            "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { issue { id title } success } }",
            {"id": issue_id.strip(), "input": allowed}, "update issue", timeout,
        )
        issue = (data.get("issueUpdate") or {}).get("issue", {})
        return issue if isinstance(issue, dict) else {}

    async def add_comment(self, creds: dict, issue_id: str, body: str, timeout: float = 30.0) -> dict:
        if not str(issue_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs an issue_id.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs body text.", retryable=False)
        data = await self._gql(
            creds,
            "mutation($issueId: String!, $body: String!) { commentCreate(input: {issueId: $issueId, body: $body}) { comment { id body } success } }",
            {"issueId": issue_id.strip(), "body": body.strip()}, "add comment", timeout,
        )
        comment = (data.get("commentCreate") or {}).get("comment", {})
        return comment if isinstance(comment, dict) else {}
