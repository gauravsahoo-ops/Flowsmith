"""CSV Connector implementing the Flowsmith ConnectorSDK interface.

Provides streaming CSV ingestion, validation, deduplication, PostgreSQL database
persistence to staged_contacts, and reconciliation with Salesforce bulk ingestion results.
"""

from __future__ import annotations

import logging
import uuid
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
from app.services.csv_service import CsvService, CsvParseOptions
from app.db import get_session

logger = logging.getLogger(__name__)


class CsvConnectorParams(BaseModel):
    operation: str = Field(default="parse", description="parse | validate_and_map | stage_to_database | reconcile.")
    download_url: str = Field(default="", description="Remote HTTP/HTTPS download link for CSV, TSV, or ZIP/GZ.")
    file_path: str = Field(default="", description="CSV, TSV, or Archive file path.")
    file_id: str = Field(default="", description="ObjectStore file ID.")
    csv_content: str = Field(default="", description="Raw CSV/TSV string or base64 data URL.")
    archive_inner_file: str = Field(default="", description="Target inner file inside archive.")
    delimiter: str = Field(default="", description="Field delimiter.")
    has_header: bool = Field(default=True, description="Whether first line is header.")
    batch_size: int = Field(default=1000, description="Batch size.")
    rows: list[dict[str, Any]] = Field(default_factory=list, description="Rows for validation/mapping.")
    field_mapping: dict[str, str] = Field(default_factory=dict, description="Field mapping dictionary.")
    target_object: str = Field(default="Contact", description="Target Salesforce object.")
    duplicate_policy: str = Field(default="skip", description="Duplicate handling: skip | update | error.")
    dedup_key: str = Field(default="Email", description="Deduplication key field.")
    execution_id: str = Field(default="", description="Execution correlation ID.")
    valid_records: list[dict[str, Any]] = Field(default_factory=list, description="Valid records to stage.")
    duplicate_records: list[dict[str, Any]] = Field(default_factory=list, description="Duplicate records.")
    invalid_records: list[dict[str, Any]] = Field(default_factory=list, description="Invalid records.")
    successful_records: list[dict[str, Any]] = Field(default_factory=list, description="Salesforce successful records.")
    failed_records: list[dict[str, Any]] = Field(default_factory=list, description="Salesforce failed records.")


class CsvConnector(ConnectorSDK):
    connector_id = "csv"
    display_name = "Delimited & Archive Ingest Engine"
    description = "Streaming CSV, TSV, and ZIP/GZ archive parsing, validation, deduplication, and database staging connector."
    category = ConnectorCategory.TRANSFORM
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    @property
    def node_types(self) -> list[str]:
        return ["csv", "csv_parser"]

    async def connect(self, config: dict[str, Any]) -> bool:
        self.status = ConnectorStatus.CONNECTED
        return True

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
            params = CsvConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid CSV payload: {exc}", retryable=False,
            ) from exc

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        if op == "parse":
            return await self._op_parse(params)
        elif op == "validate_and_map":
            return await self._op_validate_and_map(params)
        elif op == "stage_to_database":
            return await self._op_stage_to_database(params)
        elif op == "reconcile":
            return await self._op_reconcile(params)

        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Unsupported CSV connector operation '{op}'. Supported: parse, validate_and_map, stage_to_database, reconcile.",
            retryable=False,
        )

    async def _op_parse(self, params: CsvConnectorParams) -> dict[str, Any]:
        source = params.file_path or params.csv_content
        file_id = params.file_id or None
        download_url = params.download_url or None

        if not source and not file_id and not download_url:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "CSV parse requires download_url, file_path, file_id, or csv_content.",
                retryable=False,
            )

        opts = CsvParseOptions(
            delimiter=params.delimiter or None,
            has_header=params.has_header,
            batch_size=params.batch_size,
        )

        all_rows: list[dict[str, Any]] = []
        meta_out: dict[str, Any] = {}
        for batch in CsvService.stream_parsed_rows(
            source or "",
            opts,
            file_id=file_id,
            download_url=download_url,
            archive_inner_file=params.archive_inner_file or None,
            source_meta_out=meta_out,
        ):
            all_rows.extend(batch)

        return {
            "output": {
                "rows": all_rows,
                "total_parsed": len(all_rows),
                "metadata": meta_out,
            },
            "success": True,
            "operation": "parse",
        }

    async def _op_validate_and_map(self, params: CsvConnectorParams) -> dict[str, Any]:
        if not params.rows:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "validate_and_map requires a non-empty rows array.",
                retryable=False,
            )

        mapping = params.field_mapping or {
            "FirstName": "FirstName",
            "LastName": "LastName",
            "Email": "Email",
            "Phone": "Phone",
            "Department": "Department",
            "Title": "Title",
            "MailingStreet": "MailingStreet",
            "MailingCity": "MailingCity",
            "MailingState": "MailingState",
            "MailingPostalCode": "MailingPostalCode",
            "MailingCountry": "MailingCountry",
            "Description": "Description",
        }

        res = CsvService.map_and_validate(
            rows=params.rows,
            field_mapping=mapping,
            target_object=params.target_object,
            duplicate_policy=params.duplicate_policy,
            dedup_key=params.dedup_key,
        )

        return {
            "output": {
                "valid_records": res.valid_records,
                "invalid_records": res.invalid_records,
                "duplicate_records": res.duplicate_records,
                "total_parsed": res.total_parsed,
                "unique_count": res.unique_count,
                "duplicate_count": res.duplicate_count,
                "invalid_count": res.invalid_count,
            },
            "success": True,
            "operation": "validate_and_map",
        }

    async def _op_stage_to_database(self, params: CsvConnectorParams) -> dict[str, Any]:
        exec_id = params.execution_id or f"exec_{uuid.uuid4().hex[:12]}"
        with get_session() as db:
            res = CsvService.persist_staged_records(
                db=db,
                execution_id=exec_id,
                valid_records=params.valid_records,
                duplicate_records=params.duplicate_records,
                invalid_records=params.invalid_records,
                batch_size=params.batch_size,
            )

        return {
            "output": {
                "execution_id": res.execution_id,
                "total_processed": res.total_processed,
                "inserted_count": res.inserted_count,
                "duplicate_count": res.duplicate_count,
                "skipped_count": res.skipped_count,
                "invalid_count": res.invalid_count,
                "duration_ms": res.duration_ms,
            },
            "success": True,
            "operation": "stage_to_database",
        }

    async def _op_reconcile(self, params: CsvConnectorParams) -> dict[str, Any]:
        if not params.execution_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "reconcile requires an execution_id.",
                retryable=False,
            )

        with get_session() as db:
            counts = CsvService.reconcile_salesforce_results(
                db=db,
                execution_id=params.execution_id,
                successful_records=params.successful_records,
                failed_records=params.failed_records,
            )

        return {
            "output": counts,
            "success": True,
            "operation": "reconcile",
        }

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
