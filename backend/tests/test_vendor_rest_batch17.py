"""Contract tests for the seventeenth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch17 import (
    BATCH17_CATALOG_KEYS,
    UNSUPPORTED_BATCH17_KEYS,
    VENDOR_SPECS,
    build_batch17_connectors,
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
    "host": "rundeck.example.com",
    "job_id": "job1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch17_connectors()


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
async def test_every_batch17_operation_makes_a_fixed_host_request(key, operation_key):
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
            {"params": params, "body": {"argString": "-env prod"}},
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
    assert url.startswith("https://rundeck.example.com")
    assert "endpoint_url" not in url

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["headers"]["X-Rundeck-Auth-Token"] == "test-token"

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"argString": "-env prod"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch17_connectors_require_credentials(key):
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
async def test_batch17_get_forwards_query_parameters():
    connector = _connector_for("rundeck")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_job_metadata",
            {"params": {"host": "rundeck.example.com", "job_id": "job1", "format": "json"}},
            {"credentials": {"rundeck": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["format"] == "json"
    assert request_kwargs["params"]["job_id"] == "job1"
    assert request_kwargs["json"] is None
    assert client.request.await_args.args[1] == (
        "https://rundeck.example.com/api/18/job/job1/info"
    )


@pytest.mark.asyncio
async def test_batch17_post_sends_only_the_body():
    connector = _connector_for("rundeck")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "execute_job",
            {
                "params": {"host": "rundeck.example.com", "job_id": "job1"},
                "body": {"argString": "-env prod"},
            },
            {"credentials": {"rundeck": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["json"] == {"argString": "-env prod"}
    assert request_kwargs["params"] is None
    assert client.request.await_args.args[1] == (
        "https://rundeck.example.com/api/14/job/job1/run"
    )


@pytest.mark.asyncio
async def test_batch17_unknown_operation_is_rejected():
    connector = _connector_for("rundeck")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything",
            {},
            {"credentials": {"rundeck": {"api_key": "x"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch17_http_401_maps_to_auth_failure():
    connector = _connector_for("rundeck")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_job_metadata",
                {"params": {"host": "rundeck.example.com", "job_id": "job1"}},
                {"credentials": {"rundeck": {"api_key": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_batch17_missing_host_is_rejected_before_any_request():
    connector = _connector_for("rundeck")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_job_metadata",
                {"params": {"job_id": "job1"}},
                {"credentials": {"rundeck": {"api_key": "test-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value
    client.request.assert_not_awaited()


def test_batch17_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_17"
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


def test_batch17_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch17_rundeck_operations_match_the_vendor_api():
    operations = VENDOR_SPECS["rundeck"].operations
    assert operations["execute_job"].method == "POST"
    assert operations["execute_job"].path == "/api/14/job/{job_id}/run"
    assert operations["get_job_metadata"].method == "GET"
    assert operations["get_job_metadata"].path == "/api/18/job/{job_id}/info"
    assert VENDOR_SPECS["rundeck"].auth_header == "X-Rundeck-Auth-Token"


def test_batch17_reports_unimplemented_catalog_keys():
    assert set(BATCH17_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH17_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH17_KEYS)
    assert set(UNSUPPORTED_BATCH17_KEYS) == {
        "read_binary_files",
        "read_p_d_f",
        "read_write_file",
        "reddit",
        "remove_duplicates",
        "rocketchat",
        "rss_feed_read",
        "salesmate",
        "sea_table",
    }

    for key, reason in UNSUPPORTED_BATCH17_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch17_unsupported_reasons_are_specific():
    assert "globWithDeadline" in UNSUPPORTED_BATCH17_KEYS["read_binary_files"]
    assert "local file read" in UNSUPPORTED_BATCH17_KEYS["read_binary_files"]
    assert "extractDataFromPDF" in UNSUPPORTED_BATCH17_KEYS["read_p_d_f"]
    assert "local filesystem" in UNSUPPORTED_BATCH17_KEYS["read_write_file"]
    assert "redditOAuth2Api" in UNSUPPORTED_BATCH17_KEYS["reddit"]
    assert "OAuth2" in UNSUPPORTED_BATCH17_KEYS["reddit"]
    assert "local transform" in UNSUPPORTED_BATCH17_KEYS["remove_duplicates"]
    assert "X-Auth-Token" in UNSUPPORTED_BATCH17_KEYS["rocketchat"]
    assert "X-User-Id" in UNSUPPORTED_BATCH17_KEYS["rocketchat"]
    assert "rss-parser" in UNSUPPORTED_BATCH17_KEYS["rss_feed_read"]
    assert "fixed vendor host" in UNSUPPORTED_BATCH17_KEYS["rss_feed_read"]
    assert "sessionToken" in UNSUPPORTED_BATCH17_KEYS["salesmate"]
    assert "x-linkname" in UNSUPPORTED_BATCH17_KEYS["salesmate"]
    assert "app-access-token" in UNSUPPORTED_BATCH17_KEYS["sea_table"]
    assert "dtable_uuid" in UNSUPPORTED_BATCH17_KEYS["sea_table"]
