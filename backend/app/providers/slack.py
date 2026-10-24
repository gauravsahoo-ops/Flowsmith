"""Slack Web API provider client (Phase 11 business connectors).

Bot-token (xoxb…) auth against api.slack.com. The legacy webhook-based
Slack *node* stays untouched; this connector is the credential-backed,
multi-operation variant.

Rate limits: Slack answers 429 with a ``Retry-After`` header — the
provider maps it onto the connector error so the engine honors it.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message

SLACK_API_BASE = "https://slack.com/api"


class SlackProviderClient(BaseProviderClient):
    api_base = SLACK_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:  # pragma: no cover
        raise NotImplementedError("Slack uses static bot tokens.")

    @staticmethod
    def _creds(creds: dict) -> dict:
        if not str((creds or {}).get("bot_token") or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Slack connector needs a 'slack' credential with a bot token (xoxb…).",
                retryable=False,
            )
        return creds

    async def request_slack(
        self, creds: dict, method: str, path: str, *,
        json_body: dict | None = None, params: dict | None = None,
        timeout: float = 30.0, what: str = "request",
    ):
        response = await self.authorized_request(
            creds=self._creds(creds), method=method,
            url=f"{SLACK_API_BASE}{path}", json_body=json_body, params=params,
            private_token_field="bot_token", timeout=timeout, what=what,
            extract_error_message=json_error_message("error"),
        )
        # Slack signals app-level failures inside a 200 body.
        try:
            data = response.json()
        except ValueError as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Slack returned malformed JSON ({what}).", retryable=True,
            ) from exc
        if not data.get("ok", False):
            error_name = str(data.get("error") or "unknown_error")
            retry_after_header = response.headers.get("Retry-After")
            retryable = error_name == "rate_limited"
            exc = make_connector_error(
                ConnectorErrorCode.RATE_LIMITED if retryable else ConnectorErrorCode.BAD_REQUEST,
                f"Slack {what} failed: {error_name}",
                retryable=retryable,
                retry_after=float(retry_after_header) if retry_after_header else None,
            )
            raise exc
        return response

    async def send_message(self, creds: dict, channel: str, text: str,
                           thread_ts: str = "", timeout: float = 30.0) -> dict:
        channel_id = str(channel or "").strip()
        message = str(text or "")
        if not channel_id:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=send requires a channel.", retryable=False)
        if not message:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=send requires message text.", retryable=False)
        body: dict[str, Any] = {"channel": channel_id, "text": message}
        if thread_ts:
            body["thread_ts"] = thread_ts
        response = await self.request_slack(
            creds, "POST", "/chat.postMessage", json_body=body,
            timeout=timeout, what="send message",
        )
        data = response.json()
        return {"ts": data.get("ts", ""), "channel": data.get("channel", channel_id), "sent": True}

    async def list_channels(self, creds: dict, limit: int = 100, max_pages: int = 3,
                            exclude_archived: bool = True, timeout: float = 30.0) -> dict:
        limit = min(max(int(limit or 100), 1), 200)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        channels: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "limit": limit,
                "exclude_archived": "true" if exclude_archived else "false",
            }
            if cursor:
                params["cursor"] = cursor
            response = await self.request_slack(
                creds, "GET", "/conversations.list", params=params,
                timeout=timeout, what="list channels",
            )
            data = response.json()
            channels.extend([
                {"id": c.get("id"), "name": c.get("name"), "is_channel": c.get("is_channel")}
                for c in data.get("channels", [])
            ])
            cursor = ((data.get("response_metadata") or {}).get("next_cursor")) or ""
            if not cursor:
                break
        return {"channels": channels, "count": len(channels)}

    async def add_reaction(self, creds: dict, channel: str, timestamp: str, name: str, timeout: float = 30.0) -> dict:
        channel_id = str(channel or "").strip()
        ts = str(timestamp or "").strip()
        emoji = str(name or "").strip().strip(":")
        if not channel_id or not ts or not emoji:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=add_reaction requires channel, timestamp, and emoji name.", retryable=False)
        body = {"channel": channel_id, "timestamp": ts, "name": emoji}
        await self.request_slack(
            creds, "POST", "/reactions.add", json_body=body,
            timeout=timeout, what="add reaction",
        )
        return {"ok": True, "channel": channel_id, "timestamp": ts, "reaction": emoji}

    async def list_users(self, creds: dict, limit: int = 100, max_pages: int = 3,
                         timeout: float = 30.0) -> dict:
        limit = min(max(int(limit or 100), 1), 200)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        users: list[dict] = []
        cursor = ""
        for _ in range(max_pages):
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            response = await self.request_slack(
                creds, "GET", "/users.list", params=params,
                timeout=timeout, what="list users",
            )
            data = response.json()
            users.extend([
                {
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "real_name": user.get("real_name"),
                    "email": ((user.get("profile") or {}).get("email")),
                    "is_bot": user.get("is_bot", False),
                    "deleted": user.get("deleted", False),
                }
                for user in data.get("members", [])
            ])
            cursor = ((data.get("response_metadata") or {}).get("next_cursor")) or ""
            if not cursor:
                break
        return {"users": users, "count": len(users)}

    async def get_channel_history(self, creds: dict, channel: str, limit: int = 50,
                                  oldest: str = "", latest: str = "",
                                  timeout: float = 30.0) -> dict:
        channel_id = str(channel or "").strip()
        if not channel_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=get_channel_history requires a channel.",
                retryable=False,
            )
        limit = min(max(int(limit or 50), 1), 200)
        params: dict[str, Any] = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        response = await self.request_slack(
            creds, "GET", "/conversations.history", params=params,
            timeout=timeout, what="get channel history",
        )
        data = response.json()
        messages = [
            {
                "ts": message.get("ts"),
                "user": message.get("user"),
                "text": message.get("text"),
                "thread_ts": message.get("thread_ts"),
                "reply_count": message.get("reply_count", 0),
                "type": message.get("type"),
            }
            for message in data.get("messages", [])
        ]
        return {
            "messages": messages,
            "count": len(messages),
            "has_more": bool(data.get("has_more", False)),
        }

    async def update_message(self, creds: dict, channel: str, timestamp: str,
                             text: str, timeout: float = 30.0) -> dict:
        channel_id = str(channel or "").strip()
        ts = str(timestamp or "").strip()
        message = str(text or "")
        if not channel_id or not ts or not message:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=update_message requires channel, timestamp, and text.",
                retryable=False,
            )
        response = await self.request_slack(
            creds, "POST", "/chat.update",
            json_body={"channel": channel_id, "ts": ts, "text": message},
            timeout=timeout, what="update message",
        )
        data = response.json()
        return {"ts": data.get("ts", ts), "channel": data.get("channel", channel_id), "updated": True}

    async def delete_message(self, creds: dict, channel: str, timestamp: str,
                             timeout: float = 30.0) -> dict:
        channel_id = str(channel or "").strip()
        ts = str(timestamp or "").strip()
        if not channel_id or not ts:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=delete_message requires channel and timestamp.",
                retryable=False,
            )
        await self.request_slack(
            creds, "POST", "/chat.delete",
            json_body={"channel": channel_id, "ts": ts},
            timeout=timeout, what="delete message",
        )
        return {"channel": channel_id, "timestamp": ts, "deleted": True}

    async def get_user_by_email(self, creds: dict, email: str, timeout: float = 30.0) -> dict:
        user_email = str(email or "").strip()
        if not user_email:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=get_user_by_email requires an email address.", retryable=False)
        response = await self.request_slack(
            creds, "GET", "/users.lookupByEmail", params={"email": user_email},
            timeout=timeout, what="lookup user by email",
        )
        user_data = response.json().get("user", {})
        return {
            "id": user_data.get("id"),
            "name": user_data.get("name"),
            "real_name": user_data.get("real_name"),
            "email": ((user_data.get("profile") or {}).get("email")),
            "tz": user_data.get("tz"),
            "is_admin": user_data.get("is_admin", False),
        }

