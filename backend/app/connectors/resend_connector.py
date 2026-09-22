"""Resend transactional email connector implementing ConnectorSDK."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorError,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


class ResendConnector(ConnectorSDK, ConnectorOperations):
    """Resend connector for high-deliverability transactional emails and domain management."""

    connector_id = "resend"
    display_name = "Resend"
    description = "Send transactional emails, batch campaigns, and manage email domains via Resend."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> List[str]:
        return ["resend"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        self.credentials = config or {}
        return True

    async def disconnect(self) -> None:
        self.credentials = {}

    def _get_headers(self, creds: Dict[str, Any]) -> Dict[str, str]:
        key = creds.get("api_key") or ""
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    async def op_health_check(self) -> ConnectorHealthCheck:
        api_key = self.credentials.get("api_key") or ""
        if not api_key:
            return ConnectorHealthCheck(
                healthy=False,
                message="Missing Resend API Key",
            )
        headers = self._get_headers(self.credentials)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.resend.com/api_keys", headers=headers)
                if res.status_code == 200:
                    return ConnectorHealthCheck(healthy=True, message="Resend API connection active")
                if res.status_code == 401:
                    return ConnectorHealthCheck(healthy=False, message="Invalid API key")
                return ConnectorHealthCheck(healthy=False, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(healthy=False, message=str(e))

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        creds = (context or {}).get("credentials", {}).get("resend") or self.credentials or {}
        params = payload or {}
        api_key = creds.get("api_key") or ""
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Resend API Key is required.",
                retryable=False,
            )

        headers = self._get_headers(creds)
        base_url = "https://api.resend.com"
        timeout = float(params.get("timeout_seconds", 30.0))

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if operation == "send_email":
                    email_payload = {
                        "from": params.get("from", ""),
                        "to": params.get("to") if isinstance(params.get("to"), list) else [params.get("to", "")],
                        "subject": params.get("subject", ""),
                    }
                    if params.get("html"):
                        email_payload["html"] = params["html"]
                    if params.get("text"):
                        email_payload["text"] = params["text"]
                    if params.get("cc"):
                        email_payload["cc"] = params["cc"] if isinstance(params["cc"], list) else [params["cc"]]
                    if params.get("bcc"):
                        email_payload["bcc"] = params["bcc"] if isinstance(params["bcc"], list) else [params["bcc"]]
                    if params.get("reply_to"):
                        email_payload["reply_to"] = params["reply_to"]

                    res = await client.post(f"{base_url}/emails", headers=headers, json=email_payload)
                    res.raise_for_status()
                    return res.json()

                elif operation == "get_email":
                    email_id = params.get("email_id", "").strip()
                    res = await client.get(f"{base_url}/emails/{email_id}", headers=headers)
                    res.raise_for_status()
                    return res.json()

                elif operation == "create_batch_emails":
                    batch = params.get("batch") or []
                    res = await client.post(f"{base_url}/emails/batch", headers=headers, json=batch)
                    res.raise_for_status()
                    return res.json()

                elif operation == "list_domains":
                    res = await client.get(f"{base_url}/domains", headers=headers)
                    res.raise_for_status()
                    return res.json()

                elif operation == "health_check":
                    check = await self.op_health_check()
                    return check.model_dump()

                else:
                    raise make_connector_error(
                        ConnectorErrorCode.VALIDATION_FAILED,
                        f"Unsupported Resend operation: {operation}",
                        retryable=False,
                    )
            except ConnectorError:
                raise
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                code = (
                    ConnectorErrorCode.AUTH_FAILED
                    if status_code == 401
                    else ConnectorErrorCode.FORBIDDEN
                    if status_code == 403
                    else ConnectorErrorCode.NOT_FOUND
                    if status_code == 404
                    else ConnectorErrorCode.RATE_LIMITED
                    if status_code == 429
                    else ConnectorErrorCode.UNAVAILABLE
                    if status_code >= 500
                    else ConnectorErrorCode.BAD_REQUEST
                )
                raise make_connector_error(
                    code,
                    f"Resend API error: {e.response.text}",
                    retryable=status_code >= 500 or status_code == 429,
                ) from e
            except Exception as e:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    str(e),
                    retryable=False,
                ) from e
