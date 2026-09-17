"""Google Docs connector implementing the ConnectorSDK interface."""

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
from app.providers.google_docs import GoogleDocsProviderClient


class GoogleDocsConnectorParams(BaseModel):
    operation: str = Field(default="get_document")
    document_id: str = ""
    title: str = ""
    text: str = ""
    requests: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class GoogleDocsConnector(ConnectorSDK):
    connector_id = "google_docs"
    display_name = "Google Docs"
    description = "Read, create, and edit Google Docs documents."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GoogleDocsProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["google_docs"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("refresh_token") or config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GoogleDocsConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Google Docs payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("google_docs") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "get_document":
                return await self._provider.get_document(
                    creds, str(raw.get("document_id") or params.document_id), timeout=timeout)
            if op == "create_document":
                return await self._provider.create_document(
                    creds, str(raw.get("title") or params.title), timeout=timeout)
            if op == "append_text":
                return await self._provider.append_text(
                    creds, str(raw.get("document_id") or params.document_id),
                    str(raw.get("text") if raw.get("text") is not None else params.text), timeout=timeout)
            if op == "batch_update":
                raw_requests = raw.get("requests", params.requests)
                requests = json.loads(raw_requests) if isinstance(raw_requests, str) else raw_requests
                if not isinstance(requests, list):
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "batch_update requests must be a JSON array.", retryable=False)
                return await self._provider.batch_update(
                    creds, str(raw.get("document_id") or params.document_id), requests, timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Google Docs operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (tokeninfo); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["get_document", "create_document", "append_text", "batch_update"]}}
