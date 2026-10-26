"""Contract tests for native catalog-conversion batch 6.

Every request is mocked; no test reaches the network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.registry import ConnectorRegistry
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch6 import (
    BATCH6_CATALOG_KEYS,
    UNSUPPORTED_BATCH6_KEYS,
    VENDOR_SPECS,
    build_batch6_connectors,
)

FIXED_URL_PREFIX = {
    "active_campaign": "https://acme.api-us1.com/api/3",
    "api_template_io": "https://api.apitemplate.io/v1",
    "autopilot": "https://api2.autopilothq.com/v1",
}

AUTH_HEADERS = {
    "active_campaign": "Api-Token",
    "api_template_io": "X-API-KEY",
    "autopilot": "autopilotapikey",
}

PARAM_VALUES = {
    "account": "acme",
    "contact_id": "contact1",
    "template_id": "template1",
    "list_id": "list1",
    "trigger_id": "trigger1",
}


def _pairs() -> dict[str, tuple[VendorRESTConnector, Any]]:
    return {
        definition.connector_key: (connector, definition)
        for connector, definition in build_batch6_connectors()
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
async def test_batch6_operation_uses_fixed_host_and_auth(key: str, operation_key: str) -> None:
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
async def test_batch6_connector_requires_credentials(key: str) -> None:
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


def test_batch6_definitions_are_native_and_registerable() -> None:
    registry = ConnectorRegistry()
    pairs = build_batch6_connectors()

    assert {definition.connector_key for _, definition in pairs} == set(VENDOR_SPECS)
    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert connector.implementation_kind == "native"
        assert definition.connector_key == connector.connector_id == connector.spec.key
        assert definition.lifecycle_status == "beta"
        assert definition.metadata == {
            "implementation": "native",
            "batch": "catalog_conversion_6",
        }
        assert definition.operations
        registry.register(connector, definition)
        assert registry.get(definition.connector_key) is connector


def test_batch6_definitions_declare_credential_schemas() -> None:
    for connector, definition in build_batch6_connectors():
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


def test_batch6_operations_have_explicit_paths() -> None:
    for spec in VENDOR_SPECS.values():
        for operation_key, operation in spec.operations.items():
            assert operation.key == operation_key
            assert operation.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch6_reports_unimplemented_catalog_keys() -> None:
    assert set(BATCH6_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH6_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH6_KEYS)

    for reason in UNSUPPORTED_BATCH6_KEYS.values():
        assert reason.strip()

    for key in (
        "aws_certificate_manager",
        "aws_cognito",
        "aws_comprehend",
        "aws_dynamo_d_b",
        "aws_elb",
    ):
        assert "Signature Version 4" in UNSUPPORTED_BATCH6_KEYS[key]
    assert "AMQP" in UNSUPPORTED_BATCH6_KEYS["amqp"]
    assert "no vendor REST host" in UNSUPPORTED_BATCH6_KEYS["ai_transform"]


@pytest.mark.asyncio
async def test_active_campaign_accepts_account_from_credentials() -> None:
    spec = VENDOR_SPECS["active_campaign"]
    connector, _ = _pairs()["active_campaign"]

    client = AsyncMock()
    client.request.return_value = _response()
    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_contacts",
            {},
            {"credentials": {"active_campaign": {**_creds(spec), "account": "acme"}}},
        )

    args, _ = client.request.await_args
    assert args[1] == "https://acme.api-us1.com/api/3/contacts"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_key", ["create_image", "create_pdf"])
async def test_api_template_create_uses_documented_query_and_body(operation_key: str) -> None:
    spec = VENDOR_SPECS["api_template_io"]
    connector, _ = _pairs()["api_template_io"]

    client = AsyncMock()
    client.request.return_value = _response()
    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            operation_key,
            {"params": {"template_id": "template1"}, "body": {"message": "hello"}},
            {"credentials": {"api_template_io": _creds(spec)}},
        )

    args, kwargs = client.request.await_args
    assert args[0] == "POST"
    assert args[1] == "https://api.apitemplate.io/v1/create?template_id=template1"
    assert kwargs["json"] == {"message": "hello"}
