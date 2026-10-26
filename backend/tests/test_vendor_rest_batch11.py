"""Contract tests for the eleventh native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch11 import (
    BATCH11_KEYS,
    UNSUPPORTED_BATCH11_KEYS,
    VENDOR_SPECS,
    build_batch11_connectors,
)


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict[str, Any]:
        return {"ok": True}


class UnauthorizedResponse(FakeResponse):
    status_code = 401
    text = '{"error": "unauthorized"}'


_PARAM_VALUES: dict[str, str] = {
    "customer_id": "customer1",
    "event_id": "event1",
    "host": "magento.example.com",
    "list_id": "list1",
    "order_id": "order1",
    "publication_id": "publication1",
    "room_id": "room1",
    "sku": "sku1",
    "transaction_id": "transaction1",
    "user_id": "user1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch11_connectors()


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


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch11_operation_makes_a_fixed_host_request(key, operation_key):
    spec = VENDOR_SPECS[key]
    connector = _connector_for(key)
    assert isinstance(connector, VendorRESTConnector)

    operation = spec.operations[operation_key]
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
    assert result["connector"] == key
    assert result["operation"] == operation_key

    method, url = client.request.await_args.args
    assert method == operation.method
    expected_base = spec.base_url.format(**params, **credentials).rstrip("/")
    expected_url = expected_base + operation.path.format(**params, **credentials)
    assert url == expected_url
    assert "endpoint_url" not in url

    request_kwargs = client.request.await_args.kwargs
    if spec.auth_kind == "bearer":
        assert request_kwargs["headers"]["Authorization"] == "Bearer test-token"
    elif spec.auth_kind == "header":
        assert request_kwargs["headers"][spec.auth_header] == f"{spec.auth_prefix}test-token"
    else:  # pragma: no cover - batch 11 only uses bearer and header auth
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch11_connectors_require_credentials(key):
    spec = VENDOR_SPECS[key]
    connector = _connector_for(key)
    operation = next(iter(spec.operations.values()))
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            operation.key,
            {"params": _params(spec)},
            {"credentials": {spec.key: {}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value


@pytest.mark.asyncio
async def test_batch11_get_forwards_query_parameters():
    connector = _connector_for("matrix")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_messages",
            {"params": {"host": "matrix.example.com", "room_id": "room1", "dir": "b", "limit": 10}},
            {"credentials": {"matrix": {"access_token": "test-token"}}},
        )

    assert client.request.await_args.kwargs["params"]["dir"] == "b"
    assert client.request.await_args.kwargs["params"]["limit"] == 10
    assert client.request.await_args.kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch11_post_sends_only_the_body():
    connector = _connector_for("lone_scale")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "create_list",
            {"params": {"name": "ignored-in-body"}, "body": {"name": "Leads", "entity": "PEOPLE"}},
            {"credentials": {"lone_scale": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.kwargs["json"] == {"name": "Leads", "entity": "PEOPLE"}
    assert client.request.await_args.kwargs["params"] is None


@pytest.mark.asyncio
async def test_batch11_unknown_operation_is_rejected():
    connector = _connector_for("lingva_nex")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("delete_everything", {}, {"credentials": {"lingva_nex": {"api_key": "x"}}})
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch11_http_401_maps_to_auth_failure():
    connector = _connector_for("medium")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_me",
                {},
                {"credentials": {"medium": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch11_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_11"
        assert definition.lifecycle_status == "beta"
        assert definition.operations
        assert set(definition.operations) == set(connector.spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[connector.spec.key]
        assert credential.secret_fields == list(connector.spec.credential_fields)
        assert credential.encryption_required is True
        assert set(credential.validation_schema["properties"]) == set(connector.spec.credential_fields)
        for operation in definition.operations.values():
            assert operation.credential_require == connector.spec.key
            assert operation.node_types == [connector.spec.key]


def test_batch11_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch11_reports_unimplemented_catalog_keys():
    assert set(BATCH11_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH11_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH11_KEYS)
    assert set(UNSUPPORTED_BATCH11_KEYS) == {
        "linked_in",
        "mandrill",
        "markdown",
        "message_an_agent",
        "metabase",
    }

    for key, reason in UNSUPPORTED_BATCH11_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch11_unsupported_reasons_are_specific():
    assert "LinkedIn-Version" in UNSUPPORTED_BATCH11_KEYS["linked_in"]
    assert "X-Restli-Protocol-Version" in UNSUPPORTED_BATCH11_KEYS["linked_in"]
    assert "JSON request body" in UNSUPPORTED_BATCH11_KEYS["mandrill"]
    assert "local transform" in UNSUPPORTED_BATCH11_KEYS["markdown"]
    assert "executeAgent" in UNSUPPORTED_BATCH11_KEYS["message_an_agent"]
    assert "/api/session" in UNSUPPORTED_BATCH11_KEYS["metabase"]
    assert "X-Metabase-Session" in UNSUPPORTED_BATCH11_KEYS["metabase"]
