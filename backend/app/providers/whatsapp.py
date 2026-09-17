"""WhatsApp Cloud API provider client.

Meta WhatsApp Business Cloud API (v21.0) with permanent-token Bearer auth.
Ops: send text message, send template message, fetch a message.
429/5xx retryable; error.message from Graph API mapped to typed errors.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

WHATSAPP_API_VERSION = "v21.0"
WHATSAPP_API_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


def _auth(creds: dict) -> tuple[str, str]:
    token = str((creds or {}).get("access_token") or "").strip()
    phone_number_id = str((creds or {}).get("phone_number_id") or "").strip()
    if not token or not phone_number_id:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "WhatsApp connector needs a 'whatsapp' credential with access_token and phone_number_id.",
            retryable=False,
        )
    return token, phone_number_id


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            detail = f": {str(err['message'])[:200]}"
        elif isinstance(err, str):
            detail = f": {err[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"WhatsApp auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"WhatsApp forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"WhatsApp resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"WhatsApp rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"WhatsApp unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"WhatsApp rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class WhatsAppProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe: fetch the phone number's verified name."""
        token, phone_number_id = _auth(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "GET",
                    f"{WHATSAPP_API_BASE}/{phone_number_id}?fields=verified_name",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15.0,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"WhatsApp unreachable during test connection: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "test connection", payload)
        name = payload.get("verified_name", "") if isinstance(payload, dict) else ""
        return {"ok": True, "message": f"Connected as {name}." if name else "Connected."}

    async def _post_message(self, creds: dict, body: dict[str, Any], what: str, timeout: float = 30.0) -> dict:
        token, phone_number_id = _auth(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST",
                    f"{WHATSAPP_API_BASE}/{phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"messaging_product": "whatsapp", **body},
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"WhatsApp unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def send_text(
        self, creds: dict, to: str, body: str, preview_url: bool = False, timeout: float = 30.0,
    ) -> dict:
        if not str(to or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_text needs a 'to' phone number.", retryable=False)
        if not str(body or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_text needs a message body.", retryable=False)
        return await self._post_message(
            creds,
            {"to": to, "type": "text", "text": {"body": body, "preview_url": bool(preview_url)}},
            "send_text", timeout,
        )

    async def send_template(
        self, creds: dict, to: str, template: str, language: str = "en_US",
        components: list[dict[str, Any]] | None = None, timeout: float = 30.0,
    ) -> dict:
        if not str(to or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_template needs a 'to' phone number.", retryable=False)
        if not str(template or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "send_template needs a template name.", retryable=False)
        tpl: dict[str, Any] = {"name": template, "language": {"code": language or "en_US"}}
        if components:
            tpl["components"] = components
        return await self._post_message(
            creds, {"to": to, "type": "template", "template": tpl}, "send_template", timeout,
        )

    async def get_message(self, creds: dict, message_id: str, timeout: float = 30.0) -> dict:
        token, _ = _auth(creds)
        if not str(message_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_message needs a message_id.", retryable=False)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "GET",
                    f"{WHATSAPP_API_BASE}/{message_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"WhatsApp unreachable during get_message: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "get_message", payload)
        return payload if isinstance(payload, dict) else {}
