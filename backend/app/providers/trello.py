"""Trello provider client (Batch B, original implementation).

API-key auth via ``?key=..&token=..`` query params. Ops covered:
list board cards, get one card, create a card on a list, add a comment.
Rate limits answer 429 — surfaced as retryable with Retry-After.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

TRELLO_API_BASE = "https://api.trello.com/1"


def _creds(creds: dict) -> tuple[str, str]:
    key = str((creds or {}).get("api_key") or "").strip()
    token = str((creds or {}).get("api_token") or "").strip()
    if not key or not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Trello connector needs a 'trello' credential with api_key + api_token.",
            retryable=False,
        )
    return key, token


def _raise_for_status(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Trello auth failed during {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Trello resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Trello rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Trello unavailable during {what}: {body[:200]}", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Trello rejected {what}: {body[:200]}", retryable=False)


class TrelloProviderClient:
    async def _request(
        self,
        method: str,
        path: str,
        creds: dict,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
        what: str,
    ) -> Any:
        key, token = _creds(creds)
        query = {"key": key, "token": token, **(params or {})}
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{TRELLO_API_BASE}{path}", params=query,
                    json=json_body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Trello unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise_for_status(response.status_code, response.text, what)
        try:
            return response.json()
        except Exception:
            return {}

    async def list_cards(self, creds: dict, board_id: str, timeout: float = 30.0) -> list:
        board = str(board_id or "").strip()
        if not board:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "list_cards needs a board_id.", retryable=False)
        data = await self._request("GET", f"/boards/{board}/cards", creds, timeout=timeout, what="list cards")
        return data if isinstance(data, list) else []

    async def get_card(self, creds: dict, card_id: str, timeout: float = 30.0) -> dict:
        card = str(card_id or "").strip()
        if not card:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_card needs a card_id.", retryable=False)
        data = await self._request("GET", f"/cards/{card}", creds, timeout=timeout, what="get card")
        return data if isinstance(data, dict) else {}

    async def create_card(self, creds: dict, list_id: str, name: str, desc: str = "", timeout: float = 30.0) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_card needs a list_id.", retryable=False)
        if not str(name or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_card needs a name.", retryable=False)
        data = await self._request(
            "POST", "/cards", creds,
            params={"idList": list_id.strip(), "name": name.strip(), "desc": desc or ""},
            timeout=timeout, what="create card",
        )
        return data if isinstance(data, dict) else {}

    async def add_comment(self, creds: dict, card_id: str, text: str, timeout: float = 30.0) -> dict:
        card = str(card_id or "").strip()
        if not card:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a card_id.", retryable=False)
        if not str(text or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs text.", retryable=False)
        data = await self._request(
            "POST", f"/cards/{card}/actions/comments", creds,
            params={"text": text.strip()}, timeout=timeout, what="add comment",
        )
        return data if isinstance(data, dict) else {}
