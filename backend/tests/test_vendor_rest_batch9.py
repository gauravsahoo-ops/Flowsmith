"""Contract tests for the ninth native catalog-conversion batch.

Every HTTP interaction is mocked; no test reaches the network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.registry import ConnectorRegistry
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch9 import (
    BATCH9_CATALOG_KEYS,
    BATCH9_IMPLEMENTED_KEYS,
    BATCH9_KEYS,
    UNSUPPORTED_BATCH9_KEYS,
    VENDOR_SPECS,
    build_batch9_connectors,
)

EXPECTED_BATCH9_KEYS = {
    "hacker_news",
    "halo_p_s_a",
    "help_scout",
    "high_level",
    "home_assistant",
    "html",
    "humantic_ai",
    "hunter",
    "i_calendar",
    "if",
}

EXPECTED_UNSUPPORTED_KEYS = {
    "halo_p_s_a",
    "help_scout",
    "high_level",
    "html",
    "i_calendar",
    "if",
}


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict[str, Any]:
        return {"ok": True}


class UnauthorizedResponse(FakeResponse):
    status_code = 401
    text = '{"error": "unauthorized"}'


_PARAM_VALUES: dict[str, str] = {
    "article_id": "12345",
    "domain": "stripe.com",
    "email": "ada@example.com",
    "entity_id": "light.kitchen",
    "event_type": "custom_event",
    "first_name": "Ada",
    "host": "ha.example.com",
    "last_name": "Lovelace",
    "service": "turn_on",
    "start_time": "2024-01-01T00:00:00+00:00",
    "userid": "user-1",
    "username": "pg",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch9_connectors()


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


def _expected_url(spec, operation, params: dict[str, str], credentials: dict[str, str]) -> str:
    base = spec.base_url.format(**params, **credentials).rstrip("/")
    return base + operation.path.format(**params, **credentials)


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch9_operation_makes_a_fixed_host_request(key, operation_key):
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

    method, url = client.request.await_args.args
    assert method == operation.method
    assert url == _expected_url(spec, operation, params, credentials)
    assert "endpoint_url" not in url

    request_kwargs = client.request.await_args.kwargs
    if spec.auth_kind == "none":
        assert "Authorization" not in request_kwargs["headers"]
    elif spec.auth_kind == "bearer":
        assert request_kwargs["headers"]["Authorization"] == "Bearer test-token"
    elif spec.auth_kind == "query":
        assert request_kwargs["params"][spec.query_param] == "test-token"
    else:  # pragma: no cover - no batch 9 spec uses another auth kind
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(key for key in VENDOR_SPECS if VENDOR_SPECS[key].credential_fields))
@pytest.mark.asyncio
async def test_batch9_credentialled_connectors_reject_blank_credentials(key):
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
async def test_hacker_news_needs_no_credentials_and_uses_the_algolia_host():
    spec = VENDOR_SPECS["hacker_news"]
    assert spec.credential_fields == ()
    connector = _connector_for("hacker_news")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            "search",
            {"params": {"query": "n8n", "tags": "story", "hitsPerPage": 5}},
            {"credentials": {spec.key: {}}},
        )

    assert result["success"] is True
    assert client.request.await_args.args[1] == "https://hn.algolia.com/api/v1/search"
    request_kwargs = client.request.await_args.kwargs
    assert "Authorization" not in request_kwargs["headers"]
    assert request_kwargs["params"] == {"query": "n8n", "tags": "story", "hitsPerPage": 5}


@pytest.mark.asyncio
async def test_home_assistant_uses_the_configured_host_and_bearer_token():
    connector = _connector_for("home_assistant")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "call_service",
            {
                "params": {"host": "ha.example.com", "domain": "light", "service": "turn_on"},
                "body": {"entity_id": "light.kitchen"},
            },
            {"credentials": {"home_assistant": {"access_token": "home-token"}}},
        )

    args, kwargs = client.request.await_args
    assert args == ("POST", "https://ha.example.com/api/services/light/turn_on")
    assert kwargs["headers"]["Authorization"] == "Bearer home-token"
    assert kwargs["json"] == {"entity_id": "light.kitchen"}
    assert kwargs["params"] is None


@pytest.mark.asyncio
async def test_home_assistant_requires_a_host():
    connector = _connector_for("home_assistant")

    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "get_config",
            {},
            {"credentials": {"home_assistant": {"access_token": "home-token"}}},
        )

    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value
    assert "host" in str(exc_info.value)


@pytest.mark.asyncio
async def test_humantic_update_keeps_the_user_id_in_the_path_and_key_in_the_query():
    connector = _connector_for("humantic_ai")
    client = AsyncMock()
    client.request.return_value = MagicMock(
        status_code=200,
        text='{"data": {"status": "success"}}',
    )
    client.request.return_value.json.return_value = {"data": {"status": "success"}}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            "update_profile",
            {"params": {"userid": "user-1"}, "body": {"text": "Additional context"}},
            {"credentials": {"humantic_ai": {"api_key": "humantic-token"}}},
        )

    assert result["data"] == {"data": {"status": "success"}}
    args, kwargs = client.request.await_args
    assert args == (
        "POST",
        "https://api.humantic.ai/v1/user-profile/create?userid=user-1",
    )
    assert kwargs["params"] == {"apikey": "humantic-token"}
    assert kwargs["json"] == {"text": "Additional context"}


@pytest.mark.asyncio
async def test_hunter_forwards_filters_and_the_api_key_as_query_parameters():
    connector = _connector_for("hunter")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "domain_search",
            {
                "params": {
                    "domain": "stripe.com",
                    "limit": 10,
                    "seniority": "senior",
                    "department": "sales",
                }
            },
            {"credentials": {"hunter": {"api_key": "hunter-token"}}},
        )

    args, kwargs = client.request.await_args
    assert args == ("GET", "https://api.hunter.io/v2/domain-search")
    assert kwargs["params"] == {
        "api_key": "hunter-token",
        "domain": "stripe.com",
        "limit": 10,
        "seniority": "senior",
        "department": "sales",
    }
    assert kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch9_unknown_operation_is_rejected():
    connector = _connector_for("hacker_news")

    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("drop_database", {}, {"credentials": {"hacker_news": {}}})

    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch9_http_401_maps_to_auth_failure():
    connector = _connector_for("home_assistant")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_config",
                {"params": {"host": "ha.example.com"}},
                {"credentials": {"home_assistant": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch9_connectors_are_native_beta_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        spec = connector.spec
        assert isinstance(connector, VendorRESTConnector)
        assert connector.implementation_kind == "native"
        assert definition.connector_key == connector.connector_id == spec.key
        assert definition.metadata == {
            "implementation": "native",
            "batch": "catalog_conversion_9",
        }
        assert definition.lifecycle_status == "beta"
        assert definition.operations
        assert set(definition.operations) == set(spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[spec.key]
        assert credential.secret_fields == list(spec.credential_fields)
        assert credential.encryption_required is True
        assert set(credential.validation_schema["properties"]) == set(spec.credential_fields)
        for operation in definition.operations.values():
            assert operation.credential_require == spec.key
            assert operation.node_types == [spec.key]


def test_batch9_definitions_register_cleanly():
    registry = ConnectorRegistry()
    for connector, definition in build_batch9_connectors():
        registry.register(connector, definition)
        assert registry.get(definition.connector_key) is connector
        assert registry.get_definition(definition.connector_key) is not None


def test_batch9_operation_definitions_require_their_path_parameters():
    for spec in VENDOR_SPECS.values():
        for operation_key, operation in spec.operations.items():
            definition = next(
                definition
                for connector, definition in _pairs()
                if connector.spec.key == spec.key
            ).operations[operation_key]
            required = set(definition.input_schema.get("required", []))
            if operation.requires or spec.extra_required:
                assert required == {"params"}
                assert set(definition.input_schema["properties"]["params"]["required"]) == {
                    *spec.extra_required,
                    *operation.requires,
                }
            else:
                assert "required" not in definition.input_schema


def test_batch9_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch9_catalog_keys_are_fully_accounted_for():
    assert BATCH9_CATALOG_KEYS == BATCH9_KEYS == EXPECTED_BATCH9_KEYS
    assert BATCH9_IMPLEMENTED_KEYS == frozenset(VENDOR_SPECS)
    assert set(VENDOR_SPECS).isdisjoint(UNSUPPORTED_BATCH9_KEYS)
    assert set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH9_KEYS) == EXPECTED_BATCH9_KEYS
    assert set(UNSUPPORTED_BATCH9_KEYS) == EXPECTED_UNSUPPORTED_KEYS

    for key, reason in UNSUPPORTED_BATCH9_KEYS.items():
        assert reason.strip(), f"Missing unsupported reason for {key}"
        assert "VendorRESTConnector" in reason, f"Reason for {key} is not specific"

    built_keys = {connector.spec.key for connector, _definition in _pairs()}
    assert built_keys == set(VENDOR_SPECS)
    assert not built_keys & set(UNSUPPORTED_BATCH9_KEYS)


def test_batch9_unsupported_reasons_name_the_blocking_mechanism():
    assert "client-credentials" in UNSUPPORTED_BATCH9_KEYS["halo_p_s_a"]
    assert "resourceApiUrl" in UNSUPPORTED_BATCH9_KEYS["halo_p_s_a"]
    assert "OAuth2" in UNSUPPORTED_BATCH9_KEYS["help_scout"]
    assert "OAuth2" in UNSUPPORTED_BATCH9_KEYS["high_level"]
    assert "Version" in UNSUPPORTED_BATCH9_KEYS["high_level"]

    assert "local transform" in UNSUPPORTED_BATCH9_KEYS["html"]
    assert "cheerio" in UNSUPPORTED_BATCH9_KEYS["html"]
    assert "local transform" in UNSUPPORTED_BATCH9_KEYS["i_calendar"]
    assert "ics" in UNSUPPORTED_BATCH9_KEYS["i_calendar"]
    assert "logic/routing" in UNSUPPORTED_BATCH9_KEYS["if"]
