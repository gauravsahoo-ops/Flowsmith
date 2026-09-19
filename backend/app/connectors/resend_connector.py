"""Resend transactional email connector implementing ConnectorSDK."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorStatus,
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
    node_types = ["resend"]

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    async def connect(self, credentials: Dict[str, Any]) -> bool:
        self.credentials = credentials or {}
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
                status=ConnectorStatus.UNHEALTHY,
                message="Missing Resend API Key",
            )
        headers = self._get_headers(self.credentials)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.resend.com/api_keys", headers=headers)
                if res.status_code in (200, 401):
                    status = ConnectorStatus.HEALTHY if res.status_code == 200 else ConnectorStatus.UNHEALTHY
                    msg = "Resend API connection active" if status == ConnectorStatus.HEALTHY else "Invalid API key"
                    return ConnectorHealthCheck(status=status, message=msg)
                return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=str(e))

    async def op_execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        creds = self.credentials or {}
        api_key = creds.get("api_key") or ""
        if not api_key:
            raise make_connector_error("Resend API Key is required.", code=ConnectorErrorCode.CONFIG_MISSING)

        headers = self._get_headers(creds)
        base_url = "https://api.resend.com"
        timeout = float(params.get("timeout_seconds", 30.0))

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if operation == "send_email":
                    payload = {
                        "from": params.get("from", ""),
                        "to": params.get("to") if isinstance(params.get("to"), list) else [params.get("to", "")],
                        "subject": params.get("subject", ""),
                    }
                    if params.get("html"):
                        payload["html"] = params["html"]
                    if params.get("text"):
                        payload["text"] = params["text"]
                    if params.get("cc"):
                        payload["cc"] = params["cc"] if isinstance(params["cc"], list) else [params["cc"]]
                    if params.get("bcc"):
                        payload["bcc"] = params["bcc"] if isinstance(params["bcc"], list) else [params["bcc"]]
                    if params.get("reply_to"):
                        payload["reply_to"] = params["reply_to"]

                    res = await client.post(f"{base_url}/emails", headers=headers, json=payload)
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
                    raise make_connector_error(f"Unsupported Resend operation: {operation}", code=ConnectorErrorCode.VALIDATION_FAILED)
            except httpx.HTTPStatusError as e:
                raise make_connector_error(f"Resend API error: {e.response.text}", code=ConnectorErrorCode.REMOTE_ERROR)
            except Exception as e:
                raise make_connector_error(str(e), code=ConnectorErrorCode.EXECUTION_FAILED)
