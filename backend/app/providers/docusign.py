"""DocuSign eSignature provider client (Phase 40).

Integrates with DocuSign eSignature REST API v2.1:
https://{environment}.docusign.net/restapi/v2.1/accounts/{accountId}

Supports:
- create_envelope (POST /envelopes)
- get_envelope (GET /envelopes/{envelopeId})
- list_envelopes (GET /envelopes)
- list_templates (GET /templates)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.docusign")
_extract_docusign_error = json_error_message("message", "errorCode")


class DocuSignProviderClient(BaseProviderClient):
    """Client for DocuSign eSignature REST API v2.1."""

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("DocuSign uses OAuth2 access tokens or JWT Grant.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> tuple[str, str, str]:
        account_id = str(creds.get("account_id") or creds.get("accountId") or "").strip()
        if not account_id:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "DocuSign connector requires an 'account_id'.",
                retryable=False,
            )
        token = str(creds.get("access_token") or creds.get("token") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "DocuSign connector requires an 'access_token'.",
                retryable=False,
            )
        env = str(creds.get("environment") or "demo").strip().lower()
        base_host = "https://demo.docusign.net" if env == "demo" else f"https://{env}.docusign.net"
        return account_id, token, base_host

    async def request_docusign(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        account_id, token, base_host = self._validate_creds(creds)
        url = f"{base_host}/restapi/v2.1/accounts/{account_id}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    json=json_body if json_body is not None else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"DocuSign request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"DocuSign request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_docusign_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"DocuSign error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "DocuSign access token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"DocuSign forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"DocuSign resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "DocuSign rate limit reached.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"DocuSign service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def create_envelope(
        self,
        creds: dict[str, Any],
        email_subject: str,
        recipients: dict[str, Any],
        documents: List[Dict[str, Any]],
        *,
        status: str = "sent",
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        body = {
            "emailSubject": email_subject,
            "status": status,
            "documents": documents,
            "recipients": recipients,
        }
        return await self.request_docusign(creds, "POST", "envelopes", json_body=body, timeout=timeout)

    async def get_envelope(
        self,
        creds: dict[str, Any],
        envelope_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_docusign(creds, "GET", f"envelopes/{envelope_id}", timeout=timeout)

    async def list_envelopes(
        self,
        creds: dict[str, Any],
        from_date: str,
        *,
        count: int = 25,
        status: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"from_date": from_date, "count": count}
        if status:
            params["status"] = status
        return await self.request_docusign(creds, "GET", "envelopes", params=params, timeout=timeout)

    async def list_templates(
        self,
        creds: dict[str, Any],
        *,
        count: int = 50,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params = {"count": count}
        return await self.request_docusign(creds, "GET", "templates", params=params, timeout=timeout)
