"""Twilio provider client (Batch B, original implementation).

Account-SID + auth-token Basic auth with x-www-form-urlencoded bodies.
Ops: send SMS, list messages, get message. 429/5xx retryable; sends
are never retried by the engine (non-idempotent).
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


def _auth(creds: dict) -> tuple[str, tuple[str, str]]:
    sid = str((creds or {}).get("account_sid") or "").strip()
    token = str((creds or {}).get("auth_token") or "").strip()
    if not sid or not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Twilio connector needs a 'twilio' credential with account_sid + auth_token.",
            retryable=False,
        )
    return sid, (sid, token)


def _raise(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Twilio auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Twilio forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Twilio resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Twilio rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Twilio unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Twilio rejected {what}: {body[:200]}", retryable=False)


class TwilioProviderClient:
    async def _request(
        self, method: str, path: str, creds: dict, *,
        form: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0, what: str,
    ) -> Any:
        sid, basic = _auth(creds)
        url = f"{TWILIO_API_BASE}/Accounts/{sid}{path}"
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, url, auth=basic, data=form or {}, params=params or {}, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Twilio unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise(response.status_code, response.text, what)
        try:
            return response.json()
        except Exception:
            return {}

    @staticmethod
    def _check_phones(from_number: str, to_number: str) -> tuple[str, str]:
        sender = str(from_number or "").strip()
        target = str(to_number or "").strip()
        if not sender or not target:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_sms needs from_number + to_number.", retryable=False)
        return sender, target

    async def send_sms(self, creds: dict, from_number: str, to_number: str, body: str, timeout: float = 30.0) -> dict:
        sender, target = self._check_phones(from_number, to_number)
        text = str(body or "").strip()
        if not text:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_sms needs a message body.", retryable=False)
        if len(text) > 1600:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SMS body capped at 1600 chars.", retryable=False)
        data = await self._request(
            "POST", "/Messages.json", creds,
            form={"From": sender, "To": target, "Body": text}, timeout=timeout, what="send sms",
        )
        return {"sid": data.get("sid", ""), "status": data.get("status", "queued")} if isinstance(data, dict) else {}

    async def list_messages(self, creds: dict, limit: int = 20, timeout: float = 30.0) -> list:
        data = await self._request(
            "GET", "/Messages.json", creds,
            params={"PageSize": max(1, min(limit, 100))}, timeout=timeout, what="list messages",
        )
        items = data.get("messages", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def get_message(self, creds: dict, message_sid: str, timeout: float = 30.0) -> dict:
        if not str(message_sid or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_message needs a message_sid.", retryable=False)
        data = await self._request("GET", f"/Messages/{str(message_sid).strip()}.json", creds, timeout=timeout, what="get message")
        return data if isinstance(data, dict) else {}
