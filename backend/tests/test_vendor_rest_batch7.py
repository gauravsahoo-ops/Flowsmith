"""Contract tests for native catalog-conversion batch 7.

Every request is mocked; no test reaches the network. Batch 7 has no runnable
connectors because all ten catalog keys require request-signing auth that
VendorRESTConnector does not implement. The per-operation contract tests below
are kept parameterised over VENDOR_SPECS so they activate automatically if a
signing-capable spec is added later.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.registry import ConnectorRegistry
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch7 import (
    BATCH7_CATALOG_KEYS,
    UNSUPPORTED_BATCH7_KEYS,
    VENDOR_SPECS,
    build_batch7_connectors,
)

EXPECTED_BATCH7_KEYS = {
    "aws_iam",
    "aws_lambda",
    "aws_rekognition",
    "aws_s3",
    "aws_ses",
    "aws_sns",
    "aws_sqs",
    "aws_textract",
    "aws_transcribe",
    "azure_cosmos_db",
}

AWS_KEYS = {key for key in EXPECTED_BATCH7_KEYS if key.startswith("aws_")}
QUERY_PROTOCOL_KEYS = {"aws_iam", "aws_ses", "aws_sns", "aws_sqs"}
TARGET_HEADER_KEYS = {"aws_rekognition", "aws_textract", "aws_transcribe"}

# Populated only when a supported VendorSpec is added in a future revision.
FIXED_URL_PREFIX: dict[str, str] = {}
AUTH_HEADERS: dict[str, str] = {}
PARAM_VALUES: dict[str, str] = {}


def _pairs() -> dict[str, tuple[VendorRESTConnector, Any]]:
    return {
        definition.connector_key: (connector, definition)
        for connector, definition in build_batch7_connectors()
    }


def _params(spec) -> dict[str, str]:
    needed = set(spec.extra_required)
    for operation in spec.operations.values():
        needed.update(operation.requires)
    return {
        name: PARAM_VALUES.get(name, f"{name}-value")
        for name in sorted(needed)
    }


def _creds(spec) -> dict[str, str]:
    return {field: "test-token" for field in spec.credential_fields}


def _response(payload: dict[str, Any] | None = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = '{"ok": true}'
    response.json.return_value = payload if payload is not None else {"ok": True}
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "operation_key"),
    sorted(
        (key, operation_key)
        for key, spec in VENDOR_SPECS.items()
        for operation_key in spec.operations
    ),
)
async def test_batch7_operation_uses_fixed_host_and_auth(key: str, operation_key: str) -> None:
    spec = VENDOR_SPECS[key]
    connector, _ = _pairs()[key]
    operation = spec.operations[operation_key]

    client = AsyncMock()
    client.request.return_value = _response()
    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            operation.key,
            {"params": _params(spec), "body": {"name": "test"}},
            {"credentials": {spec.key: _creds(spec)}},
        )

    assert result["success"] is True
    assert result["connector"] == key
    assert result["operation"] == operation.key

    args, kwargs = client.request.await_args
    assert args[0] == operation.method
    assert args[1].startswith(FIXED_URL_PREFIX[key])
    assert "endpoint_url" not in args[1]
    assert kwargs["headers"][AUTH_HEADERS[key]] == "test-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
async def test_batch7_connector_requires_credentials(key: str) -> None:
    spec = VENDOR_SPECS[key]
    connector, _ = _pairs()[key]
    operation = next(iter(spec.operations.values()))

    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            operation.key,
            {"params": _params(spec)},
            {"credentials": {key: {}}},
        )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value


def test_batch7_definitions_are_native_and_registerable() -> None:
    registry = ConnectorRegistry()
    pairs = build_batch7_connectors()

    assert {definition.connector_key for _, definition in pairs} == set(VENDOR_SPECS)
    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert connector.implementation_kind == "native"
        assert definition.connector_key == connector.connector_id == connector.spec.key
        assert definition.lifecycle_status == "beta"
        assert definition.metadata == {
            "implementation": "native",
            "batch": "catalog_conversion_7",
        }
        assert definition.operations
        registry.register(connector, definition)
        assert registry.get(definition.connector_key) is connector


def test_batch7_definitions_declare_credential_schemas() -> None:
    for connector, definition in build_batch7_connectors():
        spec = connector.spec
        assert set(definition.credential_types) == {spec.key}
        credential = definition.credential_types[spec.key]
        assert credential.secret_fields == list(spec.credential_fields)
        assert credential.encryption_required is True

        schema = credential.validation_schema
        assert schema["type"] == "object"
        for field in (*spec.credential_fields, *spec.extra_required):
            assert field in schema["properties"]
            assert field in schema["required"]

        for operation in definition.operations.values():
            assert operation.credential_require == spec.key


def test_batch7_operations_have_explicit_paths() -> None:
    for spec in VENDOR_SPECS.values():
        for operation_key, operation in spec.operations.items():
            assert operation.key == operation_key
            assert operation.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch7_reports_unimplemented_catalog_keys() -> None:
    assert BATCH7_CATALOG_KEYS == EXPECTED_BATCH7_KEYS
    assert set(BATCH7_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH7_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH7_KEYS)

    for key, reason in UNSUPPORTED_BATCH7_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch7_aws_keys_require_sigv4() -> None:
    assert AWS_KEYS == set(UNSUPPORTED_BATCH7_KEYS) - {"azure_cosmos_db"}

    for key in AWS_KEYS:
        reason = UNSUPPORTED_BATCH7_KEYS[key]
        assert "Signature Version 4" in reason

    for key in QUERY_PROTOCOL_KEYS:
        assert "query protocol" in UNSUPPORTED_BATCH7_KEYS[key]
    for key in TARGET_HEADER_KEYS:
        assert "X-Amz-Target" in UNSUPPORTED_BATCH7_KEYS[key]

    assert "X-Amz-Invocation-Type" in UNSUPPORTED_BATCH7_KEYS["aws_lambda"]
    assert "binary" in UNSUPPORTED_BATCH7_KEYS["aws_s3"]


def test_batch7_cosmos_requires_per_request_signature() -> None:
    reason = UNSUPPORTED_BATCH7_KEYS["azure_cosmos_db"]
    assert "HMAC-SHA256" in reason
    assert "x-ms-date" in reason
    assert "resource link" in reason
    assert "static Authorization header" in reason


def test_batch7_ships_no_unimplementable_specs() -> None:
    assert VENDOR_SPECS == {}
    assert build_batch7_connectors() == []
    assert _pairs() == {}
