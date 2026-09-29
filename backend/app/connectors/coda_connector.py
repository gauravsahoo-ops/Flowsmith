"""Coda connector implementing the ConnectorSDK interface."""

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
from app.providers.coda import CodaProviderClient


class CodaConnectorParams(BaseModel):
    operation: str = Field(default="list_docs")
    doc_id: str = ""
    table_id: str = ""
    query: str = ""
    limit: int = Field(default=50, ge=1, le=500)
    page_token: str = ""
    rows: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class CodaConnector(ConnectorSDK):
    connector_id = "coda"
    display_name = "Coda"
    description = "Read and write data in Coda documents, tables, and rows."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = CodaProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["coda"]

    async def connect(self, config: dict[str, Any]) -> bool:
        token = str(config.get("api_key") or config.get("token") or "").strip()
        return bool(token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = CodaConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Coda payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("coda") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        doc_id = str(raw.get("doc_id") or params.doc_id or "").strip()
        table_id = str(raw.get("table_id") or params.table_id or "").strip()
        query = str(raw.get("query") or params.query or "").strip() or None
        limit = int(raw.get("limit") or params.limit)
        page_token = str(raw.get("page_token") or params.page_token or "").strip() or None
        rows = raw.get("rows") or params.rows or []

        try:
            if op == "list_docs":
                return await self._provider.list_docs(creds, limit=limit, page_token=page_token, query=query, timeout=timeout)

            if op == "get_doc":
                if not doc_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "doc_id is required.", retryable=False)
                return await self._provider.get_doc(creds, doc_id, timeout=timeout)

            if op == "list_tables":
                if not doc_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "doc_id is required.", retryable=False)
                return await self._provider.list_tables(creds, doc_id, limit=limit, page_token=page_token, timeout=timeout)

            if op == "list_rows":
                if not doc_id or not table_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "doc_id and table_id are required.", retryable=False)
                return await self._provider.list_rows(creds, doc_id, table_id, limit=limit, page_token=page_token, query=query, timeout=timeout)

            if op == "insert_rows":
                if not doc_id or not table_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "doc_id and table_id are required.", retryable=False)
                if not rows:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "rows array is required.", retryable=False)
                return await self._provider.insert_rows(creds, doc_id, table_id, rows, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Coda {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Coda operation '{operation}'.", retryable=False)
