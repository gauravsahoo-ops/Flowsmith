"""Stripe connector implementing the ConnectorSDK interface.

Thin mapper over StripeProviderClient. Write operations derive a stable
Idempotency-Key from (execution_id, operation, payload) so engine
retries of the same logical write are safe; credentials arrive via
context["credentials"]["stripe"].
"""

from __future__ import annotations

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
from app.providers.stripe import StripeProviderClient, idempotency_key


class StripeConnectorParams(BaseModel):
    operation: str = Field(
        default="list_customers",
        description="create_customer | get_customer | list_customers | create_payment_intent.",
    )
    email: str = ""
    name: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    customer_id: str = ""
    amount: int = 0
    currency: str = "usd"
    description: str = ""
    limit: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=3, ge=1, le=10)
    email_filter: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class StripeConnector(ConnectorSDK):
    connector_id = "stripe"
    display_name = "Stripe"
    description = "Manage Stripe customers and payment intents."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = StripeProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["stripe"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("secret_key") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = StripeConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Stripe payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("stripe") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        try:
            if op == "create_customer":
                metadata_raw = raw.get("metadata")
                metadata = {
                    str(k): str(v) for k, v in metadata_raw.items()
                } if isinstance(metadata_raw, dict) else params.metadata
                return await self._provider.create_customer(
                    creds, str(raw.get("email") or params.email),
                    name=str(raw.get("name") or params.name),
                    metadata=metadata or None,
                    idem_key=idempotency_key(context, "create_customer", payload),
                    timeout=timeout,
                )
            if op == "get_customer":
                return await self._provider.get_customer(
                    creds, str(raw.get("customer_id") or params.customer_id), timeout=timeout,
                )
            if op == "list_customers":
                return await self._provider.list_customers(
                    creds, limit=params.limit, max_pages=params.max_pages,
                    email_filter=str(raw.get("email_filter") or params.email_filter),
                    timeout=timeout,
                )
            if op == "create_payment_intent":
                return await self._provider.create_payment_intent(
                    creds, amount_cents=int(raw.get("amount", params.amount)),
                    currency=str(raw.get("currency") or params.currency),
                    customer_id=str(raw.get("customer_id") or params.customer_id),
                    description=str(raw.get("description") or params.description),
                    idem_key=idempotency_key(context, "create_payment_intent", payload),
                    timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Stripe operation '{operation}'.", retryable=False,
        )

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}
