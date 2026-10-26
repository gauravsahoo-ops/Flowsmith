"""Contract tests for the twentieth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch20 import (
    BATCH20_CATALOG_KEYS,
    UNSUPPORTED_BATCH20_KEYS,
    VENDOR_SPECS,
    build_batch20_connectors,
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
    "subdomain": "acme",
    "host": "thehive.example.com",
    "alert_id": "alert1",
    "case_id": "case1",
    "task_id": "task1",
    "contact_id": "contact1",
    "customer_id": "customer1",
    "ticket_id": "ticket1",
    "rmm_alert_id": "rmm1",
    "affiliate_id": "affiliate1",
    "program_id": "program1",
    "key": "tier",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch20_connectors()


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


def _assert_auth(spec, credentials, request_kwargs) -> None:
    if spec.auth_kind == "bearer":
        assert request_kwargs["headers"]["Authorization"] == (
            f"Bearer {credentials['api_key']}"
        )
    elif spec.auth_kind == "header":
        assert request_kwargs["headers"][spec.auth_header] == credentials["api_key"]
    elif spec.auth_kind == "query":
        assert request_kwargs["params"][spec.query_param] == credentials["api_key"]
    else:
        raise AssertionError(f"Unexpected auth kind for {spec.key}: {spec.auth_kind}")


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch20_operation_makes_a_fixed_host_request(key, operation_key):
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
    _assert_auth(spec, credentials, request_kwargs)

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
        if spec.auth_kind != "query":
            assert request_kwargs["params"] is None
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch20_connectors_require_credentials(key):
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
async def test_batch20_syncro_uses_query_auth_and_forwards_filters():
    connector = _connector_for("syncro_msp")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_contacts",
            {"params": {"subdomain": "acme", "page": 1, "per_page": 50}},
            {"credentials": {"syncro_msp": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args[1] == (
        "https://acme.syncromsp.com/api/v1/contacts"
    )
    assert request_kwargs["params"]["api_key"] == "test-token"
    assert request_kwargs["params"]["per_page"] == 50
    assert request_kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch20_syncro_post_keeps_the_api_key_in_the_query():
    connector = _connector_for("syncro_msp")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "mute_rmm_alert",
            {
                "params": {"subdomain": "acme", "rmm_alert_id": "rmm1"},
                "body": {"mute_for": "1-day"},
            },
            {"credentials": {"syncro_msp": {"api_key": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["json"] == {"mute_for": "1-day"}
    assert request_kwargs["params"] == {"api_key": "test-token"}
    assert client.request.await_args.args[1] == (
        "https://acme.syncromsp.com/api/v1/rmm_alerts/rmm1/mute"
    )


@pytest.mark.asyncio
async def test_batch20_tapfiliate_sends_its_api_key_header():
    connector = _connector_for("tapfiliate")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_affiliate",
            {"params": {"affiliate_id": "affiliate1"}},
            {"credentials": {"tapfiliate": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.args[1] == (
        "https://api.tapfiliate.com/1.6/affiliates/affiliate1/"
    )
    assert client.request.await_args.kwargs["headers"]["Api-Key"] == "test-token"


@pytest.mark.asyncio
async def test_batch20_the_hive_uses_bearer_auth_under_api():
    connector = _connector_for("the_hive")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "create_alert",
            {"params": {"host": "thehive.example.com"}, "body": {"title": "test"}},
            {"credentials": {"the_hive": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.args[1] == "https://thehive.example.com/api/alert"
    assert client.request.await_args.kwargs["headers"]["Authorization"] == (
        "Bearer test-token"
    )


@pytest.mark.asyncio
async def test_batch20_the_hive_project_uses_the_v1_query_api():
    connector = _connector_for("the_hive_project")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "execute_query",
            {
                "params": {"host": "thehive.example.com"},
                "body": {"query": [{"_name": "listCase"}]},
            },
            {"credentials": {"the_hive_project": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.args[1] == (
        "https://thehive.example.com/api/v1/query"
    )
    assert client.request.await_args.kwargs["json"] == {
        "query": [{"_name": "listCase"}]
    }
    assert client.request.await_args.kwargs["headers"]["Authorization"] == (
        "Bearer test-token"
    )


@pytest.mark.asyncio
async def test_batch20_twake_uses_the_plugin_host_and_bearer_auth():
    connector = _connector_for("twake")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "send_message",
            {
                "body": {
                    "object": {
                        "channel_id": "channel1",
                        "content": {"formatted": "hello"},
                    }
                }
            },
            {"credentials": {"twake": {"api_key": "workspace-key"}}},
        )

    assert client.request.await_args.args[1] == (
        "https://plugins.twake.app/plugins/n8n/actions/message/save"
    )
    assert client.request.await_args.kwargs["headers"]["Authorization"] == (
        "Bearer workspace-key"
    )


@pytest.mark.asyncio
async def test_batch20_delete_operation_sends_no_body():
    connector = _connector_for("syncro_msp")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "delete_ticket",
            {"params": {"subdomain": "acme", "ticket_id": "ticket1"}},
            {"credentials": {"syncro_msp": {"api_key": "test-token"}}},
        )

    assert client.request.await_args.args == (
        "DELETE",
        "https://acme.syncromsp.com/api/v1/tickets/ticket1",
    )
    assert client.request.await_args.kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch20_unknown_operation_is_rejected():
    connector = _connector_for("tapfiliate")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything", {}, {"credentials": {"tapfiliate": {"api_key": "x"}}}
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch20_http_401_maps_to_auth_failure():
    connector = _connector_for("syncro_msp")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "list_contacts",
                {"params": {"subdomain": "acme"}},
                {"credentials": {"syncro_msp": {"api_key": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_batch20_missing_host_is_rejected_before_any_request():
    connector = _connector_for("the_hive")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_alert",
                {"params": {"alert_id": "alert1"}},
                {"credentials": {"the_hive": {"api_key": "test-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value
    client.request.assert_not_awaited()


def test_batch20_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_20"
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


def test_batch20_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch20_connector_hosts_match_the_vendor_apis():
    assert VENDOR_SPECS["syncro_msp"].base_url == (
        "https://{subdomain}.syncromsp.com/api/v1"
    )
    assert VENDOR_SPECS["syncro_msp"].auth_kind == "query"
    assert VENDOR_SPECS["syncro_msp"].query_param == "api_key"
    assert VENDOR_SPECS["tapfiliate"].base_url == "https://api.tapfiliate.com/1.6"
    assert VENDOR_SPECS["tapfiliate"].auth_header == "Api-Key"
    assert VENDOR_SPECS["the_hive"].base_url == "https://{host}/api"
    assert VENDOR_SPECS["the_hive_project"].base_url == "https://{host}/api"
    assert VENDOR_SPECS["twake"].base_url == (
        "https://plugins.twake.app/plugins/n8n"
    )
    assert VENDOR_SPECS["twake"].auth_kind == "bearer"


def test_batch20_reports_unimplemented_catalog_keys():
    assert set(BATCH20_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH20_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH20_KEYS)
    assert set(UNSUPPORTED_BATCH20_KEYS) == {
        "time_saved",
        "timescale_db",
        "totp",
        "twist",
        "twitter",
    }

    for key, reason in UNSUPPORTED_BATCH20_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch20_unsupported_reasons_are_specific():
    assert "setMetadata" in UNSUPPORTED_BATCH20_KEYS["time_saved"]
    assert "local workflow action" in UNSUPPORTED_BATCH20_KEYS["time_saved"]
    assert "pg-promise" in UNSUPPORTED_BATCH20_KEYS["timescale_db"]
    assert "PostgreSQL wire-protocol" in UNSUPPORTED_BATCH20_KEYS["timescale_db"]
    assert "otpauth" in UNSUPPORTED_BATCH20_KEYS["totp"]
    assert "locally" in UNSUPPORTED_BATCH20_KEYS["totp"]
    assert "twistOAuth2Api" in UNSUPPORTED_BATCH20_KEYS["twist"]
    assert "OAuth2" in UNSUPPORTED_BATCH20_KEYS["twist"]
    assert "twitterOAuth2Api" in UNSUPPORTED_BATCH20_KEYS["twitter"]
    assert "PKCE" in UNSUPPORTED_BATCH20_KEYS["twitter"]
