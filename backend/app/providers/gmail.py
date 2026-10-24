"""Gmail provider client — send and read operations on BaseProviderClient.

Sends RFC2822 messages and reads message metadata/labels via the Gmail API.
Read operations require the gmail.readonly OAuth scope.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings as _get_settings
from app.providers.base import BaseProviderClient

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SEND_URL = f"{GMAIL_API_BASE}/messages/send"


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

    async def _get(
        self,
        creds: dict[str, Any],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
        what: str = "request",
    ) -> dict[str, Any]:
        response = await self.authorized_request(
            creds=self._creds(creds),
            method="GET",
            url=f"{GMAIL_API_BASE}{path}",
            params=params,
            timeout=timeout,
            what=what,
            private_token_field=None,
            extract_error_message=lambda r: (
                (r.json().get("error", {}).get("message", "")[:300])
                if isinstance(r.json().get("error"), dict) else ""
            ),
        )
        data = response.json()
        if not isinstance(data, dict):
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"Gmail returned a non-object response for {what}.",
                retryable=True,
            )
        return data

    async def list_messages(
        self,
        creds: dict[str, Any],
        *,
        query: str = "",
        max_results: int = 10,
        page_token: str = "",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """List message ids matching a Gmail search query (gmail.readonly)."""
        limit = min(max(int(max_results or 10), 1), 100)
        params: dict[str, Any] = {"maxResults": limit}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        data = await self._get(
            creds, "/messages", params=params, timeout=timeout, what="list messages",
        )
        messages = data.get("messages") or []
        return {
            "messages": messages,
            "count": len(messages),
            "next_page_token": str(data.get("nextPageToken") or ""),
            "result_size_estimate": data.get("resultSizeEstimate"),
        }

    async def get_message(
        self,
        creds: dict[str, Any],
        *,
        message_id: str,
        format: str = "metadata",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch one message. ``format`` is metadata, full, raw, or minimal."""
        normalized_id = str(message_id or "").strip()
        if not normalized_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=get_message requires a message_id.",
                retryable=False,
            )
        message_format = str(format or "metadata").lower()
        if message_format not in ("metadata", "full", "raw", "minimal"):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "format must be metadata, full, raw, or minimal.",
                retryable=False,
            )
        params: dict[str, Any] = {"format": message_format}
        if message_format == "metadata":
            params["metadataHeaders"] = ["From", "To", "Cc", "Subject", "Date"]
        data = await self._get(
            creds, f"/messages/{normalized_id}", params=params,
            timeout=timeout, what="get message",
        )
        return {
            "id": str(data.get("id") or normalized_id),
            "thread_id": str(data.get("threadId") or ""),
            "label_ids": data.get("labelIds") or [],
            "snippet": data.get("snippet") or "",
            "internal_date": data.get("internalDate"),
            "payload": data.get("payload") or {},
            "size_estimate": data.get("sizeEstimate"),
        }

    async def get_profile(self, creds: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """Return the connected mailbox profile (gmail.readonly)."""
        data = await self._get(creds, "/profile", timeout=timeout, what="get profile")
        return {
            "email_address": data.get("emailAddress") or "",
            "messages_total": data.get("messagesTotal"),
            "threads_total": data.get("threadsTotal"),
            "history_id": data.get("historyId"),
        }

    async def list_labels(self, creds: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """List mailbox labels (gmail.readonly)."""
        data = await self._get(creds, "/labels", timeout=timeout, what="list labels")
        labels = [
            {
                "id": label.get("id"),
                "name": label.get("name"),
                "type": label.get("type"),
                "messages_total": label.get("messagesTotal"),
                "threads_total": label.get("threadsTotal"),
            }
            for label in (data.get("labels") or [])
        ]
        return {"labels": labels, "count": len(labels)}
