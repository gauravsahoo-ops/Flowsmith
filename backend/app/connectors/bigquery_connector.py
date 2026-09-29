"""Google Cloud BigQuery connector implementing the ConnectorSDK interface."""

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
from app.providers.bigquery import BigQueryProviderClient


class BigQueryConnectorParams(BaseModel):
    operation: str = Field(default="query")
    query: str = ""
    job_id: str = ""
    dataset_id: str = ""
    table_id: str = ""
    page_token: str = ""
    max_results: int = Field(default=100, ge=1, le=1000)
    use_legacy_sql: bool = False
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class BigQueryConnector(ConnectorSDK):
    connector_id = "bigquery"
    display_name = "Google BigQuery"
    description = "Query massive datasets, list schemas, and introspect tables on Google Cloud BigQuery."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = BigQueryProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["bigquery"]

    async def connect(self, config: dict[str, Any]) -> bool:
        project_id = str(config.get("project_id") or config.get("projectId") or "").strip()
        token = str(config.get("access_token") or config.get("token") or "").strip()
        return bool(project_id and token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = BigQueryConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid BigQuery payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("bigquery") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        query_sql = str(raw.get("query") or params.query or "").strip()
        job_id = str(raw.get("job_id") or params.job_id or "").strip()
        dataset_id = str(raw.get("dataset_id") or params.dataset_id or "").strip()
        table_id = str(raw.get("table_id") or params.table_id or "").strip()
        page_token = str(raw.get("page_token") or params.page_token or "").strip() or None
        max_results = int(raw.get("max_results") or params.max_results)
        use_legacy_sql = bool(raw.get("use_legacy_sql", params.use_legacy_sql))

        try:
            if op == "query":
                if not query_sql:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SQL query is required.", retryable=False)
                return await self._provider.query(creds, query_sql, max_results=max_results, use_legacy_sql=use_legacy_sql, timeout=timeout)

            if op == "get_query_results":
                if not job_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "job_id is required.", retryable=False)
                return await self._provider.get_query_results(creds, job_id, page_token=page_token, max_results=max_results, timeout=timeout)

            if op == "list_datasets":
                return await self._provider.list_datasets(creds, max_results=max_results, page_token=page_token, timeout=timeout)

            if op == "list_tables":
                if not dataset_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "dataset_id is required.", retryable=False)
                return await self._provider.list_tables(creds, dataset_id, max_results=max_results, page_token=page_token, timeout=timeout)

            if op == "get_table":
                if not dataset_id or not table_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "dataset_id and table_id are required.", retryable=False)
                return await self._provider.get_table(creds, dataset_id, table_id, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"BigQuery {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported BigQuery operation '{operation}'.", retryable=False)
