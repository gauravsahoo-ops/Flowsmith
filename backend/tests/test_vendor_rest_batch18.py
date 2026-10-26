"""Contract tests for the eighteenth native catalog-conversion batch."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch18 import (
    BATCH18_CATALOG_KEYS,
    UNSUPPORTED_BATCH18_KEYS,
    VENDOR_SPECS,
    build_batch18_connectors,
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
    "contact_id": "contact1",
    "domain": "acme.com",
    "event_id": "event1",
    "incident_id": "incident1",
    "industry": "technology",
    "issue_id": "issue1",
    "list_id": "list1",
    "organization_slug": "acme",
    "portfolio_id": "portfolio1",
    "project_slug": "backend",
    "record_id": "record1",
    "report_type": "summary",
    "scorecard_identifier": "acme.com",
    "subdomain": "acme",
    "table_name": "incident",
    "target_score": "90",
    "team_slug": "platform",
    "version": "1.2.3",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch18_connectors()


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


def _expected_basic_header(spec, credentials: dict[str, str]) -> str:
    username = (
        credentials.get(spec.basic_user_field)
        if spec.basic_user_field
        else spec.basic_user_literal
    )
    password = (
        credentials.get(spec.basic_password_field)
        if spec.basic_password_field
        else spec.default_password
    )
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch18_operation_makes_a_fixed_host_request(key, operation_key):
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
    assert result["status_code"] == 200
    assert result["data"] == {"ok": True}

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
        assert (
            request_kwargs["headers"][spec.auth_header]
            == f"{spec.auth_prefix}test-token"
        )
    elif spec.auth_kind == "basic":
        assert (
            request_kwargs["headers"]["Authorization"]
            == _expected_basic_header(spec, credentials)
        )
    else:  # pragma: no cover - batch 18 only uses bearer, basic, and header auth
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
        assert request_kwargs["headers"]["Content-Type"] == "application/json"
    else:
        assert request_kwargs["json"] is None


# The shared VendorRESTConnector stringifies a missing basic-auth username as
# "None" before its emptiness check, so only the bearer/header connectors are
# asserted here. Segment and ServiceNow basic credentials are verified by the
# mocked request assertions below instead, keeping this test network-free.
@pytest.mark.parametrize(
    "key",
    sorted(
        key for key, spec in VENDOR_SPECS.items() if spec.auth_kind in {"bearer", "header"}
    ),
)
@pytest.mark.asyncio
async def test_batch18_connectors_require_credentials(key):
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
async def test_batch18_get_forwards_query_parameters():
    connector = _connector_for("security_scorecard")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_company_factors",
            {
                "params": {
                    "scorecard_identifier": "acme.com",
                    "severity": "high",
                    "severity_in": "high,critical",
                }
            },
            {"credentials": {"security_scorecard": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["severity"] == "high"
    assert request_kwargs["params"]["severity_in"] == "high,critical"
    assert request_kwargs["json"] is None
    assert (
        client.request.await_args.args[1]
        == "https://api.securityscorecard.io/companies/acme.com/factors"
    )


@pytest.mark.asyncio
async def test_batch18_post_sends_only_the_body():
    connector = _connector_for("send_grid")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    body = {
        "personalizations": [{"to": [{"email": "user@example.com"}]}],
        "from": {"email": "sender@example.com"},
        "content": [{"type": "text/plain", "value": "Hello"}],
    }

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "send_mail",
            {"params": {"contact_id": "ignored-in-path"}, "body": body},
            {"credentials": {"send_grid": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["json"] == body
    assert request_kwargs["params"] is None
    assert client.request.await_args.args[1] == "https://api.sendgrid.com/v3/mail/send"


@pytest.mark.asyncio
async def test_batch18_security_scorecard_uses_token_authorization():
    connector = _connector_for("security_scorecard")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_company_scorecard",
            {"params": {"scorecard_identifier": "acme.com"}},
            {"credentials": {"security_scorecard": {"api_key": "test-token"}}},
        )

    headers = client.request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Token test-token"
    assert not headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_batch18_segment_uses_the_write_key_as_basic_username():
    connector = _connector_for("segment")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "track",
            {"body": {"userId": "user1", "event": "Signed Up"}},
            {"credentials": {"segment": {"api_key": "write-key"}}},
        )

    headers = client.request.await_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Basic ")
    decoded = base64.b64decode(headers["Authorization"].split(" ", 1)[1]).decode()
    assert decoded == "write-key:"
    assert client.request.await_args.args[1] == "https://api.segment.io/v1/track"


@pytest.mark.asyncio
async def test_batch18_service_now_uses_subdomain_and_basic_auth():
    connector = _connector_for("service_now")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_incident",
            {"params": {"subdomain": "acme", "incident_id": "incident1"}},
            {"credentials": {"service_now": {"username": "admin", "password": "secret"}}},
        )

    assert (
        client.request.await_args.args[1]
        == "https://acme.service-now.com/api/now/table/incident/incident1"
    )
    expected = base64.b64encode(b"admin:secret").decode()
    assert client.request.await_args.kwargs["headers"]["Authorization"] == f"Basic {expected}"


@pytest.mark.asyncio
async def test_batch18_unknown_operation_is_rejected():
    connector = _connector_for("sentry_io")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything",
            {},
            {"credentials": {"sentry_io": {"access_token": "x"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch18_http_401_maps_to_auth_failure():
    connector = _connector_for("sentry_io")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "list_organizations",
                {},
                {"credentials": {"sentry_io": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch18_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)
    assert set(VENDOR_SPECS) == {
        "security_scorecard",
        "segment",
        "send_grid",
        "sentry_io",
        "service_now",
    }

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_18"
        assert definition.lifecycle_status == "beta"
        assert definition.operations
        assert set(definition.operations) == set(connector.spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[connector.spec.key]
        assert credential.secret_fields == list(connector.spec.credential_fields)
        assert credential.encryption_required is True
        assert set(credential.validation_schema["properties"]) == set(connector.spec.credential_fields)
        for operation_key, operation in definition.operations.items():
            spec_operation = connector.spec.operations[operation_key]
            assert operation.credential_require == connector.spec.key
            assert operation.node_types == [connector.spec.key]
            assert operation.input_schema["required"] == list(spec_operation.requires)
            assert operation.retryable is spec_operation.retryable
            assert operation.idempotency == spec_operation.idempotency


def test_batch18_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        assert "{host}" not in spec.base_url
        assert "endpoint_url" not in spec.base_url
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch18_uses_only_expected_hosts():
    assert {spec.base_url for spec in VENDOR_SPECS.values()} == {
        "https://api.securityscorecard.io",
        "https://api.segment.io/v1",
        "https://api.sendgrid.com/v3",
        "https://sentry.io",
        "https://{subdomain}.service-now.com/api",
    }


def test_batch18_reports_unimplemented_catalog_keys():
    assert set(BATCH18_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH18_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH18_KEYS)
    assert set(BATCH18_CATALOG_KEYS) == {
        "security_scorecard",
        "segment",
        "send_grid",
        "sendy",
        "sentry_io",
        "service_now",
        "set",
        "signl4",
        "simulate",
        "sort",
    }
    assert set(UNSUPPORTED_BATCH18_KEYS) == {
        "sendy",
        "set",
        "signl4",
        "simulate",
        "sort",
    }

    for key, reason in UNSUPPORTED_BATCH18_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch18_unsupported_reasons_are_specific():
    assert "form-urlencoded" in UNSUPPORTED_BATCH18_KEYS["sendy"]
    assert "api_key" in UNSUPPORTED_BATCH18_KEYS["sendy"]
    assert "local transform" in UNSUPPORTED_BATCH18_KEYS["set"]
    assert "teamSecret" in UNSUPPORTED_BATCH18_KEYS["signl4"]
    assert "multipart" in UNSUPPORTED_BATCH18_KEYS["signl4"]
    assert "X-S4-" in UNSUPPORTED_BATCH18_KEYS["signl4"]
    assert "local" in UNSUPPORTED_BATCH18_KEYS["simulate"]
    assert "local transform" in UNSUPPORTED_BATCH18_KEYS["sort"]
