"""QuickBooks connector implementing the ConnectorSDK interface."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.quickbooks import QuickBooksProviderClient


class QuickBooksConnectorParams(BaseModel):
    operation: str = Field(default="query")
    query: str = ""
    customer_ref: str = ""
    customer_id: str = ""
    invoice_id: str = ""
    display_name: str = ""
    email: str = ""
    lines: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class QuickBooksConnector(ConnectorSDK):
    connector_id = "quickbooks"
    display_name = "QuickBooks"
    description = "QuickBooks Online company, customers, invoices, and queries."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = QuickBooksProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["quickbooks"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = QuickBooksConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid QuickBooks payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("quickbooks") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "query":
                return await self._provider.query(
                    creds, str(raw.get("query") or params.query), timeout=timeout)
            if op == "get_company":
                return await self._provider.get_company(creds, timeout=timeout)
            if op == "create_customer":
                return await self._provider.create_customer(
                    creds, str(raw.get("display_name") or params.display_name),
                    str(raw.get("email") or params.email), timeout=timeout)
            if op == "get_customer":
                return await self._provider.get_customer(
                    creds, str(raw.get("customer_id") or params.customer_id), timeout=timeout)
            if op == "create_invoice":
                raw_lines = raw.get("lines", params.lines)
                lines = json.loads(raw_lines) if isinstance(raw_lines, str) else raw_lines
                if not isinstance(lines, list):
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "create_invoice lines must be a JSON array.", retryable=False)
                return await self._provider.create_invoice(
                    creds, str(raw.get("customer_ref") or params.customer_ref),
                    lines, timeout=timeout)
            if op == "get_invoice":
                return await self._provider.get_invoice(
                    creds, str(raw.get("invoice_id") or params.invoice_id), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported QuickBooks operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (company info); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["query", "get_company", "create_customer", "get_customer", "create_invoice", "get_invoice"]}}
