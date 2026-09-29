"""Xero connector implementing the ConnectorSDK interface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.xero import XeroProviderClient


class XeroConnectorParams(BaseModel):
    operation: str = Field(default="list_invoices")
    invoice_id: str = ""
    contact_id: str = ""
    where: str = ""
    type_str: str = "ACCREC"
    due_date: str = ""
    page: int = Field(default=1, ge=1)
    line_items: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class XeroConnector(ConnectorSDK):
    connector_id = "xero"
    display_name = "Xero"
    description = "Create and track invoices, contacts, and accounting records with Xero."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = XeroProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["xero"]

    async def connect(self, config: dict[str, Any]) -> bool:
        tenant_id = str(config.get("tenant_id") or "").strip()
        token = str(config.get("access_token") or config.get("token") or "").strip()
        return bool(tenant_id and token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = XeroConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Xero payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("xero") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        invoice_id = str(raw.get("invoice_id") or params.invoice_id or "").strip()
        contact_id = str(raw.get("contact_id") or params.contact_id or "").strip()
        where = str(raw.get("where") or params.where or "").strip() or None
        type_str = str(raw.get("type_str") or params.type_str or "ACCREC").strip()
        due_date = str(raw.get("due_date") or params.due_date or "").strip() or None
        page = int(raw.get("page") or params.page)
        line_items = raw.get("line_items") or params.line_items or []

        try:
            if op == "list_invoices":
                return await self._provider.list_invoices(creds, where=where, page=page, timeout=timeout)

            if op == "get_invoice":
                if not invoice_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "invoice_id is required.", retryable=False)
                return await self._provider.get_invoice(creds, invoice_id, timeout=timeout)

            if op == "create_invoice":
                if not contact_id or not line_items:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "contact_id and line_items are required.", retryable=False)
                return await self._provider.create_invoice(creds, contact_id, line_items, type_str=type_str, due_date=due_date, timeout=timeout)

            if op == "list_contacts":
                return await self._provider.list_contacts(creds, page=page, timeout=timeout)

            if op == "get_accounts":
                return await self._provider.get_accounts(creds, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Xero {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Xero operation '{operation}'.", retryable=False)
