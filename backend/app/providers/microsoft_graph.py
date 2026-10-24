"""Microsoft Graph provider client (Phase 11 business connectors).

One client-credentials app (tenant id + client id + secret live in the
encrypted ``microsoft_graph`` credential) powers both Microsoft Teams
and Outlook connectors:

    Teams/Outlook connector (op_execute)
        -> MicrosoftGraphProviderClient (this module)
            -> BaseProviderClient machinery (token cache + taxonomy)
                -> SafeHTTPClient (SSRF-protected) -> Graph API

The v2.0 endpoint token is minted per credential blob and cached in
memory until ~60s before expiry; a 401 forces one re-mint.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlencode

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

_extract_graph_error = json_error_message("message", "error")


def _require_app_creds(creds: dict) -> tuple[str, str, str]:
    tenant = str((creds or {}).get("tenant_id") or "").strip()
    client_id = str(creds.get("client_id") or "").strip()
    client_secret = str(creds.get("client_secret") or "").strip()
    if not (tenant and client_id and client_secret):
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "This operation needs a 'microsoft_graph' credential with tenant_id, "
            "client_id and client_secret.",
            retryable=False,
        )
    return tenant, client_id, client_secret


class MicrosoftGraphProviderClient(BaseProviderClient):
    """Client-credentials flow against the Graph v2.0 token endpoint.

    Overrides the shared token machinery entirely: unlike the refresh-token
    providers, every piece of auth material (tenant/client id/secret) lives
    inside the encrypted credential blob, and tokens are cached per blob.
    ``_map_status_error`` / ``_get_access_token`` shape are reused.
    """

    api_base = GRAPH_API_BASE

    def _cache_key(self, creds: dict) -> str:
        return f"{creds.get('tenant_id', '')}:{creds.get('client_id', '')}"

    async def _get_access_token(self, creds: dict, *, private_token_field: str | None = None) -> str:
        tenant, client_id, client_secret = _require_app_creds(creds)
        key = self._cache_key(creds)
        async with self._lock:
            cached = self._access_tokens.get(key)
            if cached and cached[1] > time.monotonic():
                return cached[0]
            body = urlencode({
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            })
            token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
            try:
                async with get_safe_http_client() as client:
                    response = await client.request(
                        "POST", token_url, data=body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        timeout=30.0,
                    )
            except Exception as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE, f"Token endpoint unreachable: {exc}", retryable=True,
                ) from exc
            if response.status_code >= 400:
                detail = _extract_graph_error(response)
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"Microsoft rejected the app credentials ({response.status_code}). {detail}".strip(),
                    retryable=False,
                )
            try:
                data = response.json()
                token = data["access_token"]
                expires_in = float(data.get("expires_in", 3600))
            except (ValueError, KeyError) as exc:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED, "Microsoft token response malformed.", retryable=False,
                ) from exc
            self._access_tokens[key] = (token, time.monotonic() + max(expires_in - 60.0, 30.0))
            return token

    def _invalidate(self, creds: dict) -> None:
        self._access_tokens.pop(self._cache_key(creds), None)

    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for credential Test button."""
        try:
            await self._get_access_token(creds)
            return {"ok": True, "message": "Connected to Microsoft Graph successfully."}
        except Exception as exc:
            msg = getattr(exc, "message", str(exc))
            return {"ok": False, "message": str(msg)}

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------

    async def request_graph(
        self,
        creds: dict,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict | None = None,
        timeout: float = 30.0,
        what: str = "request",
    ):
        url = f"{GRAPH_API_BASE}{path}"
        token = await self._get_access_token(creds)
        force = False
        while True:
            try:
                async with get_safe_http_client() as client:
                    response = await client.request(
                        method, url, json=json_body or None, params=params or None,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept-Encoding": "identity",
                        },
                        timeout=timeout,
                    )
            except Exception as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE, f"Graph unreachable: {exc}", retryable=True,
                ) from exc
            if response.status_code == 401 and not force:
                self._invalidate(creds)
                token = await self._get_access_token(creds)
                force = True
                continue
            if response.status_code >= 400:
                code, retryable = self._map_status_error(response.status_code, what)
                raise make_connector_error(
                    code,
                    f"Graph {what} failed ({response.status_code}). {_extract_graph_error(response)}".strip(),
                    retryable=retryable,
                )
            return response

    # -- Teams ----------------------------------------------------------

    async def list_teams(self, creds: dict, timeout: float = 30.0) -> dict:
        response = await self.request_graph(
            creds, "GET", "/me/joinedTeams", timeout=timeout, what="list teams",
        )
        teams = [
            {"id": t.get("id"), "display_name": t.get("displayName")}
            for t in response.json().get("value", [])
        ]
        return {"teams": teams, "count": len(teams)}

    async def list_channels(self, creds: dict, team_id: str, timeout: float = 30.0) -> dict:
        response = await self.request_graph(
            creds, "GET", f"/teams/{team_id}/channels", timeout=timeout, what="list channels",
        )
        channels = [
            {"id": c.get("id"), "display_name": c.get("displayName")}
            for c in response.json().get("value", [])
        ]
        return {"channels": channels, "count": len(channels)}

    async def send_channel_message(
        self, creds: dict, team_id: str, channel_id: str,
        content: str, subject: str = "", timeout: float = 30.0,
    ) -> dict:
        if not str(content or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A message body is required.", retryable=False)
        html = ("<p>" + content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br>") + "</p>")
        body: dict = {
            "body": {"contentType": "html", "content": html},
        }
        if subject:
            body["subject"] = subject
        response = await self.request_graph(
            creds, "POST", f"/teams/{team_id}/channels/{channel_id}/messages",
            json_body=body, timeout=timeout, what="send channel message",
        )
        data = response.json()
        return {"message_id": data.get("id", ""), "success": True}

    async def list_channel_messages(
        self, creds: dict, team_id: str, channel_id: str,
        top: int = 20, timeout: float = 30.0,
    ) -> dict:
        top = min(max(int(top or 20), 1), 50)
        response = await self.request_graph(
            creds, "GET",
            f"/teams/{quote(team_id)}/channels/{quote(channel_id)}/messages",
            params={"$top": top}, timeout=timeout, what="list channel messages",
        )
        messages = [
            {
                "id": m.get("id"),
                "reply_to_id": m.get("replyToId"),
                "message_type": m.get("messageType"),
                "subject": m.get("subject"),
                "from": ((m.get("from") or {}).get("user") or {}).get("displayName"),
                "created": m.get("createdDateTime"),
                "body": ((m.get("body") or {}).get("content")),
            }
            for m in response.json().get("value", [])
        ]
        return {"messages": messages, "count": len(messages)}

    async def reply_to_channel_message(
        self, creds: dict, team_id: str, channel_id: str, message_id: str,
        content: str, timeout: float = 30.0,
    ) -> dict:
        if not str(content or "").strip():
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "A reply body is required.",
                retryable=False,
            )
        html = ("<p>" + content.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>") + "</p>")
        response = await self.request_graph(
            creds, "POST",
            f"/teams/{quote(team_id)}/channels/{quote(channel_id)}/messages/{quote(message_id)}/replies",
            json_body={"body": {"contentType": "html", "content": html}},
            timeout=timeout, what="reply to channel message",
        )
        data = response.json()
        return {"message_id": data.get("id", ""), "success": True}

    async def list_team_members(
        self, creds: dict, team_id: str, timeout: float = 30.0,
    ) -> dict:
        response = await self.request_graph(
            creds, "GET", f"/teams/{quote(team_id)}/members",
            timeout=timeout, what="list team members",
        )
        members = [
            {
                "id": m.get("id"),
                "display_name": m.get("displayName"),
                "email": m.get("email"),
                "roles": m.get("roles") or [],
            }
            for m in response.json().get("value", [])
        ]
        return {"members": members, "count": len(members)}

    async def create_channel(
        self, creds: dict, team_id: str, display_name: str,
        description: str = "", timeout: float = 30.0,
    ) -> dict:
        name = str(display_name or "").strip()
        if not name:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "create_channel requires display_name.",
                retryable=False,
            )
        body: dict = {"displayName": name}
        if description:
            body["description"] = description
        response = await self.request_graph(
            creds, "POST", f"/teams/{quote(team_id)}/channels",
            json_body=body, timeout=timeout, what="create channel",
        )
        data = response.json()
        return {"channel_id": data.get("id", ""), "display_name": data.get("displayName", name)}

    # -- Mail ------------------------------------------------------------

    async def send_mail(
        self, creds: dict, to: list[str], subject: str, body: str,
        cc: list[str] | None = None, save_to_sent: bool = True, timeout: float = 30.0,
    ) -> dict:
        recipients = [a.strip() for a in (to or []) if str(a).strip()]
        if not recipients:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=send requires at least one 'to' address.", retryable=False)
        payload: dict = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML" if "<" in body else "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": a}} for a in recipients],
            },
            "saveToSentItems": bool(save_to_sent),
        }
        if cc:
            payload["message"]["ccRecipients"] = [
                {"emailAddress": {"address": a.strip()}} for a in cc if str(a).strip()
            ]
        response = await self.request_graph(
            creds, "POST", "/me/sendMail", json_body=payload,
            timeout=timeout, what="send mail",
        )
        return {"sent": True, "status": response.status_code}

    async def list_messages(self, creds: dict, folder: str = "Inbox", top: int = 10,
                            timeout: float = 30.0) -> dict:
        top = min(max(int(top or 10), 1), 50)
        response = await self.request_graph(
            creds, "GET", f"/mailFolders/{folder}/messages",
            params={"$top": top, "$select": "id,subject,from,receivedDateTime,isRead",
                    "$orderby": "receivedDateTime desc"},
            timeout=timeout, what="list messages",
        )
        messages = [
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": ((m.get("from") or {}).get("emailAddress") or {}).get("address"),
                "received": m.get("receivedDateTime"),
            }
            for m in response.json().get("value", [])
        ]
        return {"messages": messages, "count": len(messages)}

    async def get_message(self, creds: dict, message_id: str, timeout: float = 30.0) -> dict:
        mid = str(message_id or "").strip()
        if not mid:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "operation=get_message requires message_id.",
                retryable=False,
            )
        response = await self.request_graph(
            creds, "GET", f"/me/messages/{quote(mid)}",
            params={"$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,body,bodyPreview,webLink"},
            timeout=timeout, what="get message",
        )
        data = response.json()
        return {
            "id": data.get("id"),
            "subject": data.get("subject"),
            "from": ((data.get("from") or {}).get("emailAddress") or {}).get("address"),
            "to": [((r.get("emailAddress") or {}).get("address")) for r in (data.get("toRecipients") or [])],
            "cc": [((r.get("emailAddress") or {}).get("address")) for r in (data.get("ccRecipients") or [])],
            "received": data.get("receivedDateTime"),
            "is_read": data.get("isRead"),
            "body": ((data.get("body") or {}).get("content")),
            "preview": data.get("bodyPreview"),
            "web_link": data.get("webLink"),
        }

    async def list_folders(self, creds: dict, timeout: float = 30.0) -> dict:
        response = await self.request_graph(
            creds, "GET", "/me/mailFolders", params={"$top": 100},
            timeout=timeout, what="list mail folders",
        )
        folders = [
            {
                "id": f.get("id"),
                "display_name": f.get("displayName"),
                "total_item_count": f.get("totalItemCount"),
                "unread_item_count": f.get("unreadItemCount"),
            }
            for f in response.json().get("value", [])
        ]
        return {"folders": folders, "count": len(folders)}

    async def mark_read(self, creds: dict, message_id: str, is_read: bool = True,
                        timeout: float = 30.0) -> dict:
        mid = str(message_id or "").strip()
        if not mid:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "operation=mark_read requires message_id.",
                retryable=False,
            )
        response = await self.request_graph(
            creds, "PATCH", f"/me/messages/{quote(mid)}",
            json_body={"isRead": bool(is_read)}, timeout=timeout, what="mark message read",
        )
        data = response.json()
        return {"id": data.get("id", mid), "is_read": data.get("isRead"), "updated": True}

    async def move_message(self, creds: dict, message_id: str, destination_id: str,
                           timeout: float = 30.0) -> dict:
        mid = str(message_id or "").strip()
        dest = str(destination_id or "").strip()
        if not mid or not dest:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=move_message requires message_id and destination_id.",
                retryable=False,
            )
        response = await self.request_graph(
            creds, "POST", f"/me/messages/{quote(mid)}/move",
            json_body={"destinationId": dest}, timeout=timeout, what="move message",
        )
        data = response.json()
        return {
            "id": data.get("id", mid),
            "parent_folder_id": data.get("parentFolderId"),
            "moved": True,
        }

    async def delete_message(self, creds: dict, message_id: str,
                             timeout: float = 30.0) -> dict:
        mid = str(message_id or "").strip()
        if not mid:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "operation=delete_message requires message_id.",
                retryable=False,
            )
        response = await self.request_graph(
            creds, "DELETE", f"/me/messages/{quote(mid)}",
            timeout=timeout, what="delete message",
        )
        return {"id": mid, "deleted": True, "status": response.status_code}
