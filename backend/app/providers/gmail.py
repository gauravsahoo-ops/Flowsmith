"""Gmail provider client (Phase 41) — send-only, on BaseProviderClient.

Sends RFC2822 messages via
POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send
with {"raw": base64url(mime)}.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings as _get_settings
from app.providers.base import BaseProviderClient

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailProviderClient(BaseProviderClient):
    token_url = "https://oauth2.googleapis.com/token"

    def _client_id_secret(self) -> tuple[str, str]:
        s = _get_settings()
        return s.google_client_id, s.google_client_secret

    # ------------------------------------------------------------------

    @staticmethod
    def _creds(creds: dict[str, Any]) -> dict[str, Any]:
        if not str((creds or {}).get("refresh_token") or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Gmail connector needs a 'gmail' credential — connect it from the UI.",
                retryable=False,
            )
        return creds

    @staticmethod
    def build_mime(*, to: str, subject: str, body_text: str, cc: str = "", bcc: str = "", html: bool = False) -> str:
        from email.utils import parseaddr

        for label, addr in (("To", to), ("Cc", cc), ("Bcc", bcc)):
            for piece in [a.strip() for a in addr.split(",") if a.strip()]:
                if not parseaddr(piece)[1] or "@" not in parseaddr(piece)[1]:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        f"Invalid email address in {label}: '{piece[:60]}'",
                        retryable=False,
                    )
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc
        msg.set_content(body_text, subtype="html" if html else "plain")
        return msg.as_string()

    async def send(
        self,
        creds: dict[str, Any],
        *,
        to: str,
        subject: str,
        body_text: str,
        cc: str = "",
        bcc: str = "",
        html: bool = False,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        mime = self.build_mime(to=to, subject=subject, body_text=body_text, cc=cc, bcc=bcc, html=html)
        raw = base64.urlsafe_b64encode(mime.encode()).decode()
        response = await self.authorized_request(
            creds=self._creds(creds),
            method="POST",
            url=GMAIL_SEND_URL,
            json_body={"raw": raw},
            timeout=timeout,
            what="send",
            private_token_field=None,
            extract_error_message=lambda r: (
                (r.json().get("error", {}).get("message", "")[:300])
                if isinstance(r.json().get("error"), dict) else ""
            ),
        )
        data = response.json()
        return {"id": str(data.get("id", "")), "thread_id": str(data.get("threadId", "")), "sent": True}
