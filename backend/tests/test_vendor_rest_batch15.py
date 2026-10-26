"""Contract tests for the fifteenth native catalog-conversion batch."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch15 import (
    BATCH15_CATALOG_KEYS,
    BATCH15_KEYS,
    UNSUPPORTED_BATCH15_KEYS,
    VENDOR_SPECS,
    build_batch15_connectors,
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
    "auth_id": "test-auth-id",
    "bin_id": "1700000000000-1700000000000",
    "incident_id": "P123",
    "log_entry_id": "LE123",
    "request_id": "request1",
    "user_id": "U123",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch15_connectors()


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
        "access_token": "test-token",
        "api_key": "test-token",
        "auth_id": "test-auth-id",
        "auth_token": "test-token",
    }
    return {field: values[field] for field in spec.credential_fields}


def _expected_basic_header(spec, credentials: dict[str, str]) -> str:
    username = spec.basic_user_literal or credentials.get(spec.basic_user_field, "")
    password = credentials.get(spec.basic_password_field) or spec.default_password
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


def _expected_url(spec, operation, params: dict[str, str], credentials: dict[str, str]) -> str:
    values = {**credentials, **params}
    base = spec.base_url.format(**values).rstrip("/")
    return base + operation.path.format(**values)


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch15_operation_uses_its_fixed_host_and_path(key, operation_key):
    spec = VENDOR_SPECS[key]
    connector = _connector_for(key)
    assert isinstance(connector, VendorRESTConnector)

    operation = spec.operations[operation_key]
    params = _params(spec)
    credentials = _creds(spec)
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    payload: dict[str, Any] = {"params": params}
    if operation.method in {"POST", "PUT", "PATCH"}:
        payload["body"] = {"name": "test"}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            operation_key,
            payload,
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
    if spec.auth_kind == "bearer":
        assert request_kwargs["headers"]["Authorization"] == "Bearer test-token"
    elif spec.auth_kind == "header":
        assert request_kwargs["headers"][spec.auth_header] == f"{spec.auth_prefix}test-token"
    elif spec.auth_kind == "basic":
        assert request_kwargs["headers"]["Authorization"] == _expected_basic_header(
            spec, credentials
        )
    elif spec.auth_kind == "none":
        assert "Authorization" not in request_kwargs["headers"]
    else:  # pragma: no cover - batch 15 only uses supported auth kinds
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
async def test_batch15_connectors_require_credentials(key):
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
async def test_batch15_pager_duty_reads_use_api_token_header():
    connector = _connector_for("pager_duty")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_incident",
            {"params": {"incident_id": "P123"}},
            {"credentials": {"pager_duty": {"api_key": "pd-token"}}},
        )

    assert client.request.await_args.args == ("GET", "https://api.pagerduty.com/incidents/P123")
    assert client.request.await_args.kwargs["headers"]["Authorization"] == "Token token=pd-token"
    assert client.request.await_args.kwargs["json"] is None


def test_batch15_pager_duty_exposes_only_read_operations():
    spec = VENDOR_SPECS["pager_duty"]
    assert set(spec.operations) == {
        "get_incident",
        "list_incidents",
        "list_incident_notes",
        "get_log_entry",
        "list_log_entries",
        "get_user",
    }
    assert all(operation.method == "GET" for operation in spec.operations.values())
    assert "From header" in spec.description
    assert "Read operations only" in spec.description


@pytest.mark.asyncio
async def test_batch15_pager_duty_forwards_list_query_parameters():
    connector = _connector_for("pager_duty")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_incidents",
            {"params": {"statuses": ["triggered"], "limit": 10, "offset": 0}},
            {"credentials": {"pager_duty": {"api_key": "pd-token"}}},
        )

    assert client.request.await_args.args[1] == "https://api.pagerduty.com/incidents"
    request_params = client.request.await_args.kwargs["params"]
    assert request_params["statuses"] == ["triggered"]
    assert request_params["limit"] == 10
    assert request_params["offset"] == 0


@pytest.mark.asyncio
async def test_batch15_peekalink_posts_the_link_to_the_root_and_availability_paths():
    connector = _connector_for("peekalink")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    credentials = {"peekalink": {"access_token": "peek-token"}}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "preview",
            {"body": {"link": "https://example.com/article"}},
            {"credentials": credentials},
        )
        preview_call = client.request.await_args

        await connector.op_execute(
            "is_available",
            {"body": {"link": "https://example.com/article"}},
            {"credentials": credentials},
        )
        availability_call = client.request.await_args

    assert preview_call.args == ("POST", "https://api.peekalink.io/")
    assert preview_call.kwargs["json"] == {"link": "https://example.com/article"}
    assert preview_call.kwargs["headers"]["Authorization"] == "Bearer peek-token"
    assert availability_call.args == ("POST", "https://api.peekalink.io/is-available/")
    assert availability_call.kwargs["json"] == {"link": "https://example.com/article"}


@pytest.mark.asyncio
async def test_batch15_perplexity_uses_the_documented_resource_paths():
    connector = _connector_for("perplexity")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    credentials = {"perplexity": {"access_token": "pplx-token"}}
    expected_paths = {
        "create_response": "https://api.perplexity.ai/v1/agent",
        "create_embedding": "https://api.perplexity.ai/v1/embeddings",
        "create_contextualized_embedding": (
            "https://api.perplexity.ai/v1/contextualizedembeddings"
        ),
        "search": "https://api.perplexity.ai/search",
    }

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        for operation_key, expected_url in expected_paths.items():
            await connector.op_execute(
                operation_key,
                {"body": {"input": "test", "query": "test"}},
                {"credentials": credentials},
            )
            assert client.request.await_args.args == ("POST", expected_url)
            assert client.request.await_args.kwargs["headers"]["Authorization"] == (
                "Bearer pplx-token"
            )


@pytest.mark.asyncio
async def test_batch15_phantombuster_uses_api_key_header_and_query_ids():
    connector = _connector_for("phantombuster")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    credentials = {"phantombuster": {"api_key": "pb-token"}}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_agent",
            {"params": {"id": "agent1"}},
            {"credentials": credentials},
        )
        get_call = client.request.await_args

        await connector.op_execute(
            "launch_agent",
            {"body": {"id": "agent1", "arguments": {"query": "test"}}},
            {"credentials": credentials},
        )
        launch_call = client.request.await_args

    assert get_call.args == ("GET", "https://api.phantombuster.com/api/v2/agents/fetch")
    assert get_call.kwargs["params"]["id"] == "agent1"
    assert get_call.kwargs["headers"]["X-Phantombuster-Key"] == "pb-token"
    assert launch_call.args == (
        "POST",
        "https://api.phantombuster.com/api/v2/agents/launch",
    )
    assert launch_call.kwargs["json"] == {
        "id": "agent1",
        "arguments": {"query": "test"},
    }
    assert "launch_sync" not in VENDOR_SPECS["phantombuster"].operations


@pytest.mark.asyncio
async def test_batch15_plivo_uses_basic_auth_and_account_scoped_paths():
    connector = _connector_for("plivo")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    credentials = {
        "plivo": {"auth_id": "MA1234567890", "auth_token": "plivo-secret"},
    }
    body = {"src": "+14156667777", "dst": "+14156667778", "text": "Hello"}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "send_sms",
            {"params": {"auth_id": "MA1234567890"}, "body": body},
            {"credentials": credentials},
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args == (
        "POST",
        "https://api.plivo.com/v1/Account/MA1234567890/Message/",
    )
    assert request_kwargs["headers"]["Authorization"] == "Basic " + base64.b64encode(
        b"MA1234567890:plivo-secret"
    ).decode()
    assert request_kwargs["json"] == body
    assert request_kwargs["params"] is None


@pytest.mark.asyncio
async def test_batch15_plivo_make_call_uses_voice_path():
    connector = _connector_for("plivo")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "make_call",
            {
                "params": {"auth_id": "MA1234567890"},
                "body": {
                    "from": "+14156667777",
                    "to": "+14156667778",
                    "answer_url": "https://example.com/answer",
                    "answer_method": "POST",
                },
            },
            {"credentials": {"plivo": {"auth_id": "MA1234567890", "auth_token": "secret"}}},
        )

    assert client.request.await_args.args == (
        "POST",
        "https://api.plivo.com/v1/Account/MA1234567890/Call/",
    )
    assert client.request.await_args.kwargs["json"]["answer_method"] == "POST"


@pytest.mark.asyncio
async def test_batch15_post_bin_needs_no_credentials_and_uses_fixed_paths():
    connector = _connector_for("post_bin")
    assert VENDOR_SPECS["post_bin"].credential_fields == ()
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute("create_bin", {}, {"credentials": {"post_bin": {}}})
        create_call = client.request.await_args

        await connector.op_execute(
            "get_request",
            {"params": {"bin_id": "1700000000000-1700000000000", "request_id": "request1"}},
            {"credentials": {"post_bin": {}}},
        )
        request_call = client.request.await_args

    assert create_call.args == ("POST", "https://www.postb.in/api/bin")
    assert "Authorization" not in create_call.kwargs["headers"]
    assert request_call.args == (
        "GET",
        "https://www.postb.in/api/bin/1700000000000-1700000000000/req/request1",
    )
    assert "Authorization" not in request_call.kwargs["headers"]


@pytest.mark.asyncio
async def test_batch15_oura_forwards_date_filters():
    connector = _connector_for("oura")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_activity_summary",
            {"params": {"start_date": "2026-01-01", "end_date": "2026-01-07"}},
            {"credentials": {"oura": {"access_token": "oura-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args == (
        "GET",
        "https://api.ouraring.com/v2/usercollection/daily_activity",
    )
    assert request_kwargs["params"]["start_date"] == "2026-01-01"
    assert request_kwargs["params"]["end_date"] == "2026-01-07"
    assert request_kwargs["headers"]["Authorization"] == "Bearer oura-token"
    assert request_kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch15_unknown_operation_is_rejected():
    connector = _connector_for("oura")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything",
            {},
            {"credentials": {"oura": {"access_token": "x"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch15_http_401_maps_to_auth_failure():
    connector = _connector_for("perplexity")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "create_embedding",
                {"body": {"input": ["test"]}},
                {"credentials": {"perplexity": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch15_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        spec = connector.spec
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_15"
        assert definition.lifecycle_status == "beta"
        assert set(definition.operations) == set(spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[spec.key]
        assert credential.secret_fields == list(spec.credential_fields)
        assert credential.encryption_required is True
        assert set(credential.validation_schema["properties"]) == set(spec.credential_fields)
        for operation_key, operation in definition.operations.items():
            expected = spec.operations[operation_key]
            assert operation.credential_require == spec.key
            assert operation.node_types == [spec.key]
            assert operation.retryable == expected.retryable
            assert operation.idempotency == expected.idempotency
            assert operation.input_schema["required"] == list(expected.requires)


def test_batch15_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch15_post_operations_are_non_idempotent():
    for spec in VENDOR_SPECS.values():
        for operation in spec.operations.values():
            if operation.method == "POST":
                assert operation.retryable is False
                assert operation.idempotency == "non_idempotent"
            else:
                assert operation.retryable is True
                assert operation.idempotency == "idempotent"


def test_batch15_reports_unimplemented_catalog_keys():
    assert BATCH15_KEYS == BATCH15_CATALOG_KEYS
    assert set(BATCH15_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH15_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH15_KEYS)
    assert set(UNSUPPORTED_BATCH15_KEYS) == {"pay_pal", "philips_hue", "post_hog"}

    built_keys = {connector.spec.key for connector, _definition in _pairs()}
    assert not built_keys & set(UNSUPPORTED_BATCH15_KEYS)
    for key, reason in UNSUPPORTED_BATCH15_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch15_unsupported_reasons_are_specific():
    assert "grant_type=client_credentials" in UNSUPPORTED_BATCH15_KEYS["pay_pal"]
    assert "/v1/oauth2/token" in UNSUPPORTED_BATCH15_KEYS["pay_pal"]
    assert "philipsHueOAuth2Api" in UNSUPPORTED_BATCH15_KEYS["philips_hue"]
    assert "api.meethue.com/route" in UNSUPPORTED_BATCH15_KEYS["philips_hue"]
    assert "request body" in UNSUPPORTED_BATCH15_KEYS["post_hog"]
    assert "api_key" in UNSUPPORTED_BATCH15_KEYS["post_hog"]
