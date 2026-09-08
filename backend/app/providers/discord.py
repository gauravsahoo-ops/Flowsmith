"""Discord provider client (Phase 11 business connectors).

Two delivery paths:

- bot token (``Bot`` auth scheme) -> ``/channels/{id}/messages``
- incoming webhook URL passed per call (no stored secret; the URL
  itself is the credential) -> executed message

Discord rate limits answer 429 with ``Retry-After`` (seconds, float) —
surfaced on the connector error so the engine honors it.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

DISCORD_API_BASE = "https://discord.com/api/v10"
_extract_discord_error = json_error_message("message")


def _require_content(content: str) -> str:
    text = str(content or "")
    if not text.strip():
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A message content string is required.", retryable=False)
    if len(text) > 2000:
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Discord messages are capped at 2000 characters.", retryable=False)
    return text


class DiscordProviderClient(BaseProviderClient):
    api_base = DISCORD_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:  # pragma: no cover
        raise NotImplementedError("Discord uses static bot tokens.")

    @staticmethod
    def _creds(creds: dict) -> dict:
        if not str((creds or {}).get("bot_token") or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Discord connector needs a 'discord' credential with a bot token.",
                retryable=False,
            )
        return creds

    async def send_message(self, creds: dict, channel_id: str, content: str,
                           timeout: float = 30.0) -> dict:
        cid = str(channel_id or "").strip()
        if not cid or not cid.isdigit():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=send requires a numeric channel id.", retryable=False)
        response = await self.authorized_request(
            creds=self._creds(creds), method="POST",
            url=f"{DISCORD_API_BASE}/channels/{cid}/messages",
            json_body={"content": _require_content(content)},
            private_token_field="bot_token", auth_scheme="Bot",
            timeout=timeout, what="send message",
            extract_error_message=_extract_discord_error,
        )
        data = response.json()
        return {"message_id": data.get("id", ""), "channel_id": cid, "sent": True}

    async def send_webhook(self, webhook_url: str, content: str,
                           username: str = "", timeout: float = 30.0) -> dict:
        url = str(webhook_url or "").strip()
        if not url.startswith("https://"):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A https Discord webhook URL is required.", retryable=False)
        body: dict[str, Any] = {"content": _require_content(content)}
        if username:
            body["username"] = username
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", url, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Webhook unreachable: {exc}", retryable=True,
            ) from exc
        if response.status_code == 429:
            delay = response.headers.get("Retry-After")
            raise make_connector_error(
                ConnectorErrorCode.RATE_LIMITED, "Discord webhook rate limited.",
                retryable=True, retry_after=float(delay) if delay else None,
            )
        if response.status_code >= 400:
            code, retryable = self._map_status_error(response.status_code, "webhook")
            raise make_connector_error(
                code,
                f"Webhook failed ({response.status_code}). {_extract_discord_error(response)}".strip(),
                retryable=retryable,
            )
        # 204 No Content on success — synthesize an id.
        message_id = ""
        if response.status_code == 200:
            try:
                message_id = response.json().get("id", "")
            except ValueError:
                message_id = ""
        return {"message_id": message_id, "sent": True, "status": response.status_code}
