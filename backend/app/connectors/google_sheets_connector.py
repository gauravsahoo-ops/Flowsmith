"""Google Sheets connector (Phase 39): read/append/update via Sheets v4."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations
from app.providers.google_sheets import GoogleSheetsProviderClient

logger = logging.getLogger(__name__)


class GoogleSheetsConnectorParams(BaseModel):
    operation: str = Field(default="read")
    spreadsheet_id: str = Field(default="", description="Spreadsheet id (from its URL).")
    range: str = Field(default="Sheet1!A1:Z100", description="A1-notation range.")
    values: list[Any] = Field(default_factory=list, description="Row values (append/update).")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class GoogleSheetsConnector(ConnectorSDK, ConnectorOperations):
    connector_id = "google_sheets"
    display_name = "Google Sheets"
    description = "Read, append and update rows in Google Sheets."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GoogleSheetsProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["google_sheets"]

    async def connect(self, config: dict[str, Any]) -> bool:
        if not config.get("refresh_token"):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._provider.reset()
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GoogleSheetsConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid Google Sheets payload: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("google_sheets") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        try:
            if op == "read":
                sid, rng = self._require_ids(payload, params)
                return await self._provider.read_values(creds, sid, rng, timeout=params.timeout_seconds)
            if op == "append":
                sid, rng = self._require_ids(payload, params)
                values = payload.get("values") or params.values
                if not isinstance(values, list) or not values:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=append requires a values row.", retryable=False)
                return await self._provider.append_row(creds, sid, rng, values, timeout=params.timeout_seconds)
            if op == "update":
                sid, rng = self._require_ids(payload, params)
                values = payload.get("values") or params.values
                if not isinstance(values, list) or not values or not isinstance(values[0], list):
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=update requires values as rows ([[...], [...]]).", retryable=False)
                return await self._provider.update_values(creds, sid, rng, values, timeout=params.timeout_seconds)
        except ConnectorError:
            raise

        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Unsupported Google Sheets operation '{operation}'.",
            retryable=False,
        )

    def _require_ids(self, payload: dict[str, Any], params: GoogleSheetsConnectorParams) -> tuple[str, str]:
        sid = str(payload.get("spreadsheet_id") or params.spreadsheet_id or "").strip()
        rng = str(payload.get("range") or params.range or "").strip() or "Sheet1!A1:Z100"
        if not sid:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A spreadsheet_id is required.", retryable=False)
        return sid, rng
