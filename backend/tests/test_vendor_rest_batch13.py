"""Contract tests for the thirteenth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch13 import (
    BATCH13_CATALOG_KEYS,
    UNSUPPORTED_BATCH13_KEYS,
    VENDOR_SPECS,
    build_batch13_connectors,
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
    "attribute_id": "attribute1",
    "event_id": "event1",
    "feed_id": "feed1",
    "galaxy_id": "galaxy1",
    "host": "misp.example.com",
    "noticelist_id": "noticelist1",
    "organisation_id": "organisation1",
    "tag_id": "tag1",
    "user_id": "user1",
    "warninglist_id": "warninglist1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch13_connectors()


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


def _expected_auth_headers(spec) -> dict[str, str]:
    if spec.auth_kind == "bearer":
        return {"Authorization": "Bearer test-token"}
    if spec.auth_kind == "header":
        return {spec.auth_header: f"{spec.auth_prefix}test-token"}
    return {}


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch13_operation_makes_a_fixed_host_request(key, operation_key):
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
    for header, value in _expected_auth_headers(spec).items():
        assert request_kwargs["headers"][header] == value

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch13_connectors_require_credentials(key):
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
async def test_batch13_misp_sends_raw_api_key_in_authorization_header():
    connector = _connector_for("misp")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_events",
            {"params": {"host": "misp.example.com", "limit": 10}},
            {"credentials": {"misp": {"api_key": "raw-misp-key"}}},
        )

    headers = client.request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "raw-misp-key"


@pytest.mark.asyncio
async def test_batch13_msg91_appends_authkey_to_query_parameters():
    connector = _connector_for("msg91")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "send_sms",
            {
                "params": {
                    "sender": "ACME",
                    "mobiles": "+15551234567",
                    "message": "hello",
                    "route": "4",
                    "country": "0",
                }
            },
            {"credentials": {"msg91": {"authkey": "msg91-key"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["authkey"] == "msg91-key"
    assert request_kwargs["params"]["sender"] == "ACME"
    assert request_kwargs["params"]["mobiles"] == "+15551234567"
    assert request_kwargs["params"]["message"] == "hello"
    assert request_kwargs["json"] is None
    assert "Authorization" not in request_kwargs["headers"]


@pytest.mark.asyncio
async def test_batch13_mistral_ocr_posts_only_the_body():
    connector = _connector_for("mistral_ai")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    body = {
        "model": "mistral-ocr-latest",
        "document": {"type": "document_url", "document_url": "https://example.com/doc.pdf"},
    }
    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "extract_text",
            {"params": {"unused": "value"}, "body": body},
            {"credentials": {"mistral_ai": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args == ("POST", "https://api.mistral.ai/v1/ocr")
    assert request_kwargs["json"] == body
    assert request_kwargs["params"] is None


@pytest.mark.asyncio
async def test_batch13_get_forwards_query_parameters():
    connector = _connector_for("misp")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_attributes",
            {"params": {"host": "misp.example.com", "page": 2, "limit": 25}},
            {"credentials": {"misp": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["page"] == 2
    assert request_kwargs["params"]["limit"] == 25
    assert request_kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch13_missing_path_parameter_is_rejected():
    connector = _connector_for("misp")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "get_event",
            {"params": {"host": "misp.example.com"}},
            {"credentials": {"misp": {"api_key": "test-token"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch13_unknown_operation_is_rejected():
    connector = _connector_for("msg91")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything", {}, {"credentials": {"msg91": {"authkey": "x"}}}
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch13_http_401_maps_to_auth_failure():
    connector = _connector_for("mistral_ai")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "extract_text",
                {"body": {"model": "mistral-ocr-latest"}},
                {"credentials": {"mistral_ai": {"api_key": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch13_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_13"
        assert definition.lifecycle_status == "beta"
        assert definition.operations
        assert set(definition.operations) == set(connector.spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[connector.spec.key]
        assert credential.secret_fields == list(connector.spec.credential_fields)
        assert credential.encryption_required is True
        assert set(credential.validation_schema["properties"]) == set(
            connector.spec.credential_fields
        )
        for operation in definition.operations.values():
            assert operation.credential_require == connector.spec.key
            assert operation.node_types == [connector.spec.key]


def test_batch13_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        assert "endpoint_url" not in spec.base_url
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch13_sms_send_is_not_retryable():
    definition = next(
        definition for connector, definition in _pairs() if connector.spec.key == "msg91"
    )
    operation = definition.operations["send_sms"]
    assert operation.retryable is False
    assert operation.idempotency == "non_idempotent"


def test_batch13_reports_unimplemented_catalog_keys():
    assert set(BATCH13_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH13_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH13_KEYS)
    assert set(UNSUPPORTED_BATCH13_KEYS) == {
        "microsoft_teams",
        "microsoft_to_do",
        "mindee",
        "mocean",
        "monday_com",
        "mongo_db",
        "move_binary_data",
    }

    for key, reason in UNSUPPORTED_BATCH13_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch13_unsupported_reasons_are_specific():
    assert "microsoftTeamsOAuth2Api" in UNSUPPORTED_BATCH13_KEYS["microsoft_teams"]
    assert "microsoftEntraServicePrincipalApi" in UNSUPPORTED_BATCH13_KEYS["microsoft_teams"]
    assert "microsoftToDoOAuth2Api" in UNSUPPORTED_BATCH13_KEYS["microsoft_to_do"]
    assert "multipart/form-data" in UNSUPPORTED_BATCH13_KEYS["mindee"]
    assert "mocean-api-key" in UNSUPPORTED_BATCH13_KEYS["mocean"]
    assert "GraphQL" in UNSUPPORTED_BATCH13_KEYS["monday_com"]
    assert "wire protocol" in UNSUPPORTED_BATCH13_KEYS["mongo_db"]
    assert "local transform" in UNSUPPORTED_BATCH13_KEYS["move_binary_data"]
