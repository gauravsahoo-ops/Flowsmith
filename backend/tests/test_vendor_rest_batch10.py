"""Contract tests for the tenth native catalog-conversion batch."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch10 import (
    BATCH10_KEYS,
    UNSUPPORTED_BATCH10_KEYS,
    VENDOR_SPECS,
    build_batch10_connectors,
)


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict[str, Any]:
        return {"ok": True}


_PARAM_VALUES: dict[str, str] = {
    "bank_transaction_id": "banktx1",
    "client_id": "client1",
    "email": "user@example.com",
    "expense_id": "expense1",
    "file_id": "file1",
    "form_id": "form1",
    "hook_id": "hook1",
    "host": "tenant.example.com",
    "invoice_id": "invoice1",
    "job_name": "deploy",
    "log_id": "log1",
    "new_job": "deploy-copy",
    "payment_id": "payment1",
    "quote_id": "quote1",
    "submission_id": "submission1",
    "task_id": "task1",
    "url": "https://example.com/article",
    "user_id": "user1",
}


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch10_connectors()


def _connector_for(key: str) -> VendorRESTConnector:
    for connector, _definition in _pairs():
        if connector.spec.key == key:
            return connector
    raise AssertionError(f"Missing connector for {key}")


def _params(spec) -> dict[str, str]:
    required = set(spec.extra_required)
    for operation in spec.operations.values():
        required.update(operation.requires)
    missing = required - set(_PARAM_VALUES)
    assert not missing, f"Test parameter values missing for: {sorted(missing)}"
    return {name: _PARAM_VALUES[name] for name in required}


def _creds(spec) -> dict[str, str]:
    return {field: "test-token" for field in spec.credential_fields}


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_every_batch10_connector_makes_a_fixed_host_request(key):
    spec = VENDOR_SPECS[key]
    connector = _connector_for(key)
    assert isinstance(connector, VendorRESTConnector)

    operation = next(iter(spec.operations.values()))
    params = _params(spec)
    credentials = _creds(spec)
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            operation.key,
            {"params": params, "body": {"name": "test"}},
            {"credentials": {spec.key: credentials}},
        )

    assert result["success"] is True
    assert result["connector"] == key

    method, url = client.request.await_args.args
    assert method == operation.method
    expected_base = spec.base_url.format(**params, **credentials).rstrip("/")
    assert url == expected_base or url.startswith(f"{expected_base}/")
    assert "endpoint_url" not in url

    request_kwargs = client.request.await_args.kwargs
    if spec.auth_kind == "bearer":
        assert request_kwargs["headers"]["Authorization"] == "Bearer test-token"
    elif spec.auth_kind == "header":
        assert request_kwargs["headers"][spec.auth_header] == f"{spec.auth_prefix}test-token"
    elif spec.auth_kind == "basic":
        scheme, encoded = request_kwargs["headers"]["Authorization"].split(" ", 1)
        assert scheme == "Basic"
        assert base64.b64decode(encoded).decode() == "test-token:test-token"
    else:  # pragma: no cover - no batch 10 spec uses another auth kind
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")


def _all_operations() -> list[tuple[str, str]]:
    return [
        (key, operation_key)
        for key, spec in sorted(VENDOR_SPECS.items())
        for operation_key in spec.operations
    ]


@pytest.mark.parametrize(("key", "operation_key"), _all_operations())
@pytest.mark.asyncio
async def test_every_batch10_operation_uses_its_declared_method_and_path(key, operation_key):
    spec = VENDOR_SPECS[key]
    operation = spec.operations[operation_key]
    connector = _connector_for(key)
    params = _params(spec)
    credentials = _creds(spec)
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            operation_key,
            {"params": params, "body": {"name": "test"}},
            {"credentials": {spec.key: credentials}},
        )

    assert result["success"] is True
    assert result["operation"] == operation_key
    method, url = client.request.await_args.args
    assert method == operation.method
    expected_base = spec.base_url.format(**params, **credentials).rstrip("/")
    assert url.startswith(f"{expected_base}/")
    assert operation.path.startswith("/")
    assert "endpoint_url" not in url


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch10_connector_requires_credentials(key):
    spec = VENDOR_SPECS[key]
    connector = _connector_for(key)
    operation = next(iter(spec.operations.values()))
    blank_credentials = {field: "" for field in spec.credential_fields}
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            operation.key,
            {"params": _params(spec)},
            {"credentials": {spec.key: blank_credentials}},
        )
    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value


def test_batch10_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_10"
        assert definition.lifecycle_status == "beta"
        assert definition.operations
        assert set(definition.operations) == set(connector.spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[connector.spec.key]
        assert credential.secret_fields == list(connector.spec.credential_fields)
        assert credential.encryption_required is True
        for operation in definition.operations.values():
            assert operation.credential_require == connector.spec.key
            assert operation.node_types == [connector.spec.key]


def test_batch10_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "endpoint_url" not in operation.path


def test_unsupported_batch10_keys_are_documented_and_not_built():
    assert set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH10_KEYS) == set(BATCH10_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH10_KEYS)
    assert set(UNSUPPORTED_BATCH10_KEYS) == {
        "jwt", "keap", "ldap", "limit", "line",
    }
    for key, reason in UNSUPPORTED_BATCH10_KEYS.items():
        assert reason.strip(), f"Missing unsupported reason for {key}"
    built_keys = {connector.spec.key for connector, _definition in _pairs()}
    assert not built_keys & set(UNSUPPORTED_BATCH10_KEYS)
