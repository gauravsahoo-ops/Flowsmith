"""Contract tests for the fourteenth native catalog-conversion batch."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch14 import (
    BATCH14_CATALOG_KEYS,
    UNSUPPORTED_BATCH14_KEYS,
    VENDOR_SPECS,
    build_batch14_connectors,
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
    "credential_id": "credential1",
    "credential_type_name": "httpHeaderAuth",
    "execution_id": "execution1",
    "file_location": "nsconfig/ssl",
    "file_name": "server.cer",
    "host": "vendor.example.com",
    "member_id": "member1",
    "note_id": "note1",
    "post_id": "post1",
    "project_id": "project1",
    "version_id": "version1",
    "workflow_id": "workflow1",
    "workspace_id": "workspace1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch14_connectors()


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
    values = {
        "api_key": "test-token",
        "access_token": "test-token",
        "username": "test-user",
        "password": "test-password",
    }
    return {field: values.get(field, "test-token") for field in spec.credential_fields}


def _expected_basic_header(spec, credentials: dict[str, str]) -> str:
    username = spec.basic_user_literal or credentials.get(spec.basic_user_field, "")
    password = credentials.get(spec.basic_password_field) or spec.default_password
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch14_operation_makes_a_fixed_host_request(key, operation_key):
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
    elif spec.auth_kind == "basic":
        assert request_kwargs["headers"]["Authorization"] == _expected_basic_header(spec, credentials)
    elif spec.auth_kind == "query":
        assert request_kwargs["params"][spec.query_param] == "test-token"
        assert "Authorization" not in request_kwargs["headers"]
    elif spec.auth_kind == "none":
        assert "Authorization" not in request_kwargs["headers"]
    else:  # pragma: no cover - batch 14 only uses the supported auth kinds
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize(
    "key",
    sorted(key for key, spec in VENDOR_SPECS.items() if spec.credential_fields),
)
@pytest.mark.asyncio
async def test_batch14_connectors_require_credentials(key):
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


@pytest.mark.asyncio
async def test_batch14_get_forwards_query_parameters():
    connector = _connector_for("n8n")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_executions",
            {"params": {"host": "n8n.example.com", "status": "success", "limit": 10}},
            {"credentials": {"n8n": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["status"] == "success"
    assert request_kwargs["params"]["limit"] == 10
    assert request_kwargs["params"]["host"] == "n8n.example.com"
    assert request_kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch14_post_sends_only_the_body():
    connector = _connector_for("n8n")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "create_workflow",
            {
                "params": {"host": "n8n.example.com", "name": "ignored-in-body"},
                "body": {"name": "Workflow", "nodes": [], "connections": {}},
            },
            {"credentials": {"n8n": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["json"] == {"name": "Workflow", "nodes": [], "connections": {}}
    assert request_kwargs["params"] is None


@pytest.mark.asyncio
async def test_batch14_query_auth_adds_the_vendor_parameter():
    connector = _connector_for("open_weather_map")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_current_weather",
            {"params": {"q": "berlin,de", "units": "metric"}},
            {"credentials": {"open_weather_map": {"api_key": "weather-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["APPID"] == "weather-token"
    assert request_kwargs["params"]["q"] == "berlin,de"
    assert request_kwargs["params"]["units"] == "metric"


@pytest.mark.asyncio
async def test_batch14_one_simple_api_forwards_inputs_and_token():
    connector = _connector_for("one_simple_api")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "validate_email",
            {"params": {"email": "user@example.com"}},
            {"credentials": {"one_simple_api": {"api_key": "simple-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["token"] == "simple-token"
    assert request_kwargs["params"]["email"] == "user@example.com"
    assert client.request.await_args.args[1] == "https://onesimpleapi.com/api/email?output=json"


@pytest.mark.asyncio
async def test_batch14_netscaler_uses_basic_auth_and_fixed_nitro_path():
    connector = _connector_for("netscaler_adc")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "download_file",
            {"params": {"host": "adc.example.com", "file_name": "server.cer", "file_location": "nsconfig/ssl"}},
            {"credentials": {"netscaler_adc": {"username": "admin", "password": "secret"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["headers"]["Authorization"] == "Basic " + base64.b64encode(
        b"admin:secret"
    ).decode()
    assert client.request.await_args.args[1] == (
        "https://adc.example.com/nitro/v1/config/systemfile"
        "?args=filename:server.cer,filelocation:nsconfig/ssl"
    )


@pytest.mark.asyncio
async def test_batch14_open_thesaurus_needs_no_credentials():
    connector = _connector_for("open_thesaurus")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            "get_synonyms",
            {"params": {"q": "Haus"}},
            {"credentials": {"open_thesaurus": {}}},
        )

    assert result["success"] is True
    assert client.request.await_args.args[1] == (
        "https://www.openthesaurus.de/synonyme/search?format=application/json"
    )
    assert client.request.await_args.kwargs["params"] == {"q": "Haus"}
    assert "Authorization" not in client.request.await_args.kwargs["headers"]


@pytest.mark.asyncio
async def test_batch14_unknown_operation_is_rejected():
    connector = _connector_for("orbit")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything",
            {},
            {"credentials": {"orbit": {"access_token": "x"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch14_http_401_maps_to_auth_failure():
    connector = _connector_for("orbit")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "list_members",
                {"params": {"workspace_id": "workspace1"}},
                {"credentials": {"orbit": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch14_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_14"
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


def test_batch14_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch14_reports_unimplemented_catalog_keys():
    assert set(BATCH14_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH14_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH14_KEYS)
    assert set(UNSUPPORTED_BATCH14_KEYS) == {
        "my_sql",
        "next_cloud",
        "no_op",
        "odoo",
    }

    for key, reason in UNSUPPORTED_BATCH14_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch14_unsupported_reasons_are_specific():
    assert "mysql2" in UNSUPPORTED_BATCH14_KEYS["my_sql"]
    assert "MySQL wire protocol" in UNSUPPORTED_BATCH14_KEYS["my_sql"]
    assert "WebDAV" in UNSUPPORTED_BATCH14_KEYS["next_cloud"]
    assert "PROPFIND" in UNSUPPORTED_BATCH14_KEYS["next_cloud"]
    assert "OCS-APIRequest" in UNSUPPORTED_BATCH14_KEYS["next_cloud"]
    assert "local pass-through" in UNSUPPORTED_BATCH14_KEYS["no_op"]
    assert "X-Odoo-Database" in UNSUPPORTED_BATCH14_KEYS["odoo"]
    assert "/jsonrpc" in UNSUPPORTED_BATCH14_KEYS["odoo"]


def test_batch14_orbit_paths_match_the_vendor_api():
    operations = VENDOR_SPECS["orbit"].operations
    assert operations["create_activity"].path == "/{workspace_id}/members/{member_id}/activities"
    assert operations["lookup_member"].path == "/{workspace_id}/members/find"
    assert operations["list_posts"].path == "/{workspace_id}/activities?type=content"
    assert operations["create_post"].path == "/{workspace_id}/members/{member_id}/activities/"
    assert operations["delete_post"].path == (
        "/{workspace_id}/members/{member_id}/activities/{post_id}"
    )
