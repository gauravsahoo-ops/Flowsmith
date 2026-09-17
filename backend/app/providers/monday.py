"""Monday.com provider client.

Monday GraphQL API v2 with API-token Bearer auth.
Ops: boards, items, updates. 429/5xx retryable; GraphQL errors mapped.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

MONDAY_API_URL = "https://api.monday.com/v2"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("api_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Monday connector needs a 'monday' credential with api_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, errors: list | None = None) -> None:
    # Transport status wins over GraphQL error payloads: a 429/5xx carrying
    # errors is still retryable, and auth mapping stays status-driven.
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Monday rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Monday unavailable during {what}.", retryable=True)
    if errors:
        msg = str(errors[0].get("message", ""))[:200] if isinstance(errors[0], dict) else str(errors[0])[:200]
        if "auth" in msg.lower() or status == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Monday auth failed during {what}.", retryable=False)
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Monday rejected {what}: {msg}", retryable=False)
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Monday auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Monday forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Monday resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Monday rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Monday unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Monday rejected {what}: {body[:200]}.", retryable=False)


class MondayProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (viewer)."""
        data = await self._gql(creds, "query { me { id name } }", {}, "test connection")
        name = (data.get("me", {}) or {}).get("name", "")
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _gql(self, creds: dict, query: str, variables: dict[str, Any], what: str, timeout: float = 30.0) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", MONDAY_API_URL,
                    headers={"Authorization": _key(creds), "Content-Type": "application/json"},
                    json={"query": query, "variables": variables}, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Monday unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload.get("errors") if isinstance(payload, dict) else None)
        return payload.get("data", {}) if isinstance(payload, dict) else {}

    async def list_boards(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        data = await self._gql(
            creds, "query($limit: Int) { boards(limit: $limit) { id name } }",
            {"limit": max(1, min(int(limit or 25), 100))}, "list_boards", timeout,
        )
        return {"boards": data.get("boards", [])}

    async def get_board(self, creds: dict, board_id: str, timeout: float = 30.0) -> dict:
        if not str(board_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_board needs a board_id.", retryable=False)
        data = await self._gql(
            creds, "query($id: ID!) { boards(ids: [$id]) { id name groups { id title } } }",
            {"id": board_id}, "get_board", timeout,
        )
        boards = data.get("boards", [])
        if not boards:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, "Monday board missing.", retryable=False)
        return {"board": boards[0]}

    async def list_items(self, creds: dict, board_id: str, limit: int = 25, timeout: float = 30.0) -> dict:
        if not str(board_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "list_items needs a board_id.", retryable=False)
        data = await self._gql(
            creds, "query($board: ID!, $limit: Int) { boards(ids: [$board]) { items_page(limit: $limit) { items { id name } } } }",
            {"board": board_id, "limit": max(1, min(int(limit or 25), 100))}, "list_items", timeout,
        )
        boards = data.get("boards", [])
        items = ((boards[0].get("items_page") or {}).get("items", []) if boards else [])
        return {"items": items}

    async def create_item(
        self, creds: dict, board_id: str, item_name: str, group_id: str = "", timeout: float = 30.0,
    ) -> dict:
        if not str(board_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_item needs a board_id.", retryable=False)
        if not str(item_name or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_item needs an item_name.", retryable=False)
        data = await self._gql(
            creds,
            "mutation($board: ID!, $group: String, $name: String!) { create_item(board_id: $board, group_id: $group, item_name: $name) { id name } }",
            {"board": board_id, "group": group_id or None, "name": item_name},
            "create_item", timeout,
        )
        return {"item": data.get("create_item", {})}

    async def add_update(self, creds: dict, item_id: str, body: str, timeout: float = 30.0) -> dict:
        if not str(item_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_update needs an item_id.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_update needs a body.", retryable=False)
        data = await self._gql(
            creds,
            "mutation($item: ID!, $body: String!) { create_update(item_id: $item, body: $body) { id } }",
            {"item": item_id, "body": body}, "add_update", timeout,
        )
        return {"update": data.get("create_update", {})}
