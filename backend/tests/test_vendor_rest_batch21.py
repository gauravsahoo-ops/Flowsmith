"""Contract tests for the twenty-first native catalog-conversion batch."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch21 import (
    BATCH21_CATALOG_KEYS,
    UNSUPPORTED_BATCH21_KEYS,
    VENDOR_SPECS,
    build_batch21_connectors,
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
    "certificate_id": "cert1",
    "certificate_request_id": "request1",
    "region": "cloud",
    "scan_id": "scan1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch21_connectors()


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
    return {
        field: "user@example.com" if field == "email" else "test-token"
        for field in spec.credential_fields
    }


def _expected_auth_header(spec, credentials: dict[str, str]) -> tuple[str, str]:
    if spec.auth_kind == "basic":
        token = base64.b64encode(
            f"{credentials[spec.basic_user_field]}:{credentials[spec.basic_password_field]}".encode()
        ).decode()
        return "Authorization", f"Basic {token}"
    if spec.auth_kind == "header":
        return spec.auth_header, f"{spec.auth_prefix}{credentials['api_key']}"
    raise AssertionError(f"Unexpected auth kind for {spec.key}: {spec.auth_kind}")


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch21_operation_makes_a_fixed_host_request(key, operation_key):
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
    header_name, header_value = _expected_auth_header(spec, credentials)
    assert request_kwargs["headers"][header_name] == header_value

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
        assert request_kwargs["params"] is None
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch21_connectors_require_credentials(key):
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
async def test_batch21_get_forwards_query_parameters():
    connector = _connector_for("url_scan_io")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "search_scans",
            {"params": {"q": "domain:example.com", "size": 10}},
            {"credentials": {"url_scan_io": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.kwargs["params"]["q"] == "domain:example.com"
    assert client.request.await_args.kwargs["params"]["size"] == 10
    assert client.request.await_args.kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch21_post_sends_only_the_body():
    connector = _connector_for("venafi_tls_protect_cloud")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "create_certificate_request",
            {
                "params": {"region": "eu"},
                "body": {"applicationId": "app1", "certificateIssuingTemplateId": "tmpl1"},
            },
            {"credentials": {"venafi_tls_protect_cloud": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.kwargs["json"] == {
        "applicationId": "app1",
        "certificateIssuingTemplateId": "tmpl1",
    }
    assert client.request.await_args.kwargs["params"] is None
    assert client.request.await_args.args[1].startswith("https://api.venafi.eu/")


@pytest.mark.asyncio
async def test_batch21_uproc_uses_basic_auth():
    connector = _connector_for("u_proc")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "process",
            {"body": {"processor": "domain-validity", "params": {"domain": "example.com"}}},
            {"credentials": {"u_proc": {"email": "user@example.com", "api_key": "secret"}}},
        )

    expected = base64.b64encode(b"user@example.com:secret").decode()
    assert client.request.await_args.kwargs["headers"]["Authorization"] == f"Basic {expected}"
    assert client.request.await_args.args[1] == "https://api.uproc.io/api/v2/process"


@pytest.mark.asyncio
async def test_batch21_unknown_operation_is_rejected():
    connector = _connector_for("uplead")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("delete_everything", {}, {"credentials": {"uplead": {"api_key": "x"}}})
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch21_http_401_maps_to_auth_failure():
    connector = _connector_for("url_scan_io")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_scan",
                {"params": {"scan_id": "scan1"}},
                {"credentials": {"url_scan_io": {"api_key": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch21_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_21"
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


def test_batch21_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch21_reports_unimplemented_catalog_keys():
    assert set(BATCH21_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH21_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH21_KEYS)
    assert set(UNSUPPORTED_BATCH21_KEYS) == {
        "unleashed_software",
        "uptime_robot",
        "venafi_tls_protect_datacenter",
        "vero",
        "vonage",
        "wekan",
    }

    for key, reason in UNSUPPORTED_BATCH21_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch21_unsupported_reasons_are_specific():
    assert "HMAC-SHA256" in UNSUPPORTED_BATCH21_KEYS["unleashed_software"]
    assert "api-auth-signature" in UNSUPPORTED_BATCH21_KEYS["unleashed_software"]
    assert "api_key" in UNSUPPORTED_BATCH21_KEYS["uptime_robot"]
    assert "application/x-www-form-urlencoded" in UNSUPPORTED_BATCH21_KEYS["uptime_robot"]
    assert "/vedauth/authorize/oauth" in UNSUPPORTED_BATCH21_KEYS["venafi_tls_protect_datacenter"]
    assert "auth_token" in UNSUPPORTED_BATCH21_KEYS["vero"]
    assert "api_secret" in UNSUPPORTED_BATCH21_KEYS["vonage"]
    assert "/users/login" in UNSUPPORTED_BATCH21_KEYS["wekan"]
    assert "session token" in UNSUPPORTED_BATCH21_KEYS["wekan"]
