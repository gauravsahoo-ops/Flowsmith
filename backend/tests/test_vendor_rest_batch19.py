"""Contract tests for the nineteenth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch19 import (
    BATCH19_CATALOG_KEYS,
    UNSUPPORTED_BATCH19_KEYS,
    VENDOR_SPECS,
    build_batch19_connectors,
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
    "content_type": "articles",
    "entry_id": "entry1",
    "host": "strapi.example.com",
    "row_id": "row1",
    "space_id": "space1",
    "stack_id": "stack1",
    "story_id": "story1",
    "table": "Stories",
}

_CREDENTIAL_VALUES: dict[str, str] = {
    "access_token": "test-access-token",
    "api_key": "test-api-key",
    "api_token": "test-api-token",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch19_connectors()


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
    return {field: _CREDENTIAL_VALUES[field] for field in spec.credential_fields}


def _auth_token(spec, credentials: dict[str, str]) -> str:
    if spec.auth_kind == "bearer":
        return (
            credentials.get("access_token")
            or credentials.get("api_key")
            or credentials.get("api_token")
            or ""
        )
    if spec.auth_kind == "header":
        return credentials.get("api_key") or credentials.get("access_token") or ""
    raise AssertionError(f"Unexpected auth kind for {spec.key}: {spec.auth_kind}")


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch19_operation_makes_a_fixed_host_request(key, operation_key):
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
        assert request_kwargs["headers"]["Authorization"] == f"Bearer {_auth_token(spec, credentials)}"
    elif spec.auth_kind == "header":
        assert (
            request_kwargs["headers"][spec.auth_header]
            == f"{spec.auth_prefix}{_auth_token(spec, credentials)}"
        )
    else:  # pragma: no cover - batch 19 only uses bearer and header auth
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
        assert request_kwargs["headers"]["Content-Type"] == "application/json"
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch19_connectors_require_credentials(key):
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
async def test_batch19_stackby_forwards_query_parameters():
    connector = _connector_for("stackby")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_rows",
            {
                "params": {
                    "stack_id": "stack1",
                    "table": "Stories",
                    "view": "All Stories",
                    "maxrecord": 25,
                    "offset": 50,
                }
            },
            {"credentials": {"stackby": {"api_key": "test-api-key"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["view"] == "All Stories"
    assert request_kwargs["params"]["maxrecord"] == 25
    assert request_kwargs["params"]["offset"] == 50
    assert request_kwargs["json"] is None
    assert (
        client.request.await_args.args[1]
        == "https://stackby.com/api/betav1/rowlist/stack1/Stories"
    )


@pytest.mark.asyncio
async def test_batch19_stackby_append_sends_only_the_body():
    connector = _connector_for("stackby")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    body = {"records": [{"field": {"Name": "Acme", "Status": "Active"}}]}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "append_rows",
            {"params": {"stack_id": "stack1", "table": "Stories"}, "body": body},
            {"credentials": {"stackby": {"api_key": "test-api-key"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["json"] == body
    assert request_kwargs["params"] is None
    assert (
        client.request.await_args.args[1]
        == "https://stackby.com/api/betav1/rowcreate/stack1/Stories"
    )


@pytest.mark.asyncio
async def test_batch19_stackby_row_ids_are_sent_in_the_query_string():
    connector = _connector_for("stackby")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_row",
            {"params": {"stack_id": "stack1", "table": "Stories", "row_id": "row1"}},
            {"credentials": {"stackby": {"api_key": "test-api-key"}}},
        )
        await connector.op_execute(
            "delete_rows",
            {"params": {"stack_id": "stack1", "table": "Stories", "row_id": "row1"}},
            {"credentials": {"stackby": {"api_key": "test-api-key"}}},
        )

    read_url = client.request.await_args_list[0].args[1]
    delete_url = client.request.await_args_list[1].args[1]
    assert read_url == "https://stackby.com/api/betav1/rowlist/stack1/Stories?rowIds=row1"
    assert delete_url == "https://stackby.com/api/betav1/rowdelete/stack1/Stories?rowIds=row1"
    assert client.request.await_args_list[1].kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch19_storyblok_uses_the_raw_access_token_header():
    connector = _connector_for("storyblok")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_story",
            {"params": {"space_id": "space1", "story_id": "story1"}},
            {"credentials": {"storyblok": {"access_token": "test-access-token"}}},
        )

    headers = client.request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "test-access-token"
    assert not headers["Authorization"].startswith("Bearer ")
    assert (
        client.request.await_args.args[1]
        == "https://mapi.storyblok.com/v1/spaces/space1/stories/story1"
    )


@pytest.mark.asyncio
async def test_batch19_strapi_uses_host_bearer_and_v4_data_envelope():
    connector = _connector_for("strapi")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    body = {"data": {"title": "Hello"}}

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "create_entry",
            {"params": {"host": "strapi.example.com", "content_type": "articles"}, "body": body},
            {"credentials": {"strapi": {"api_token": "test-api-token"}}},
        )

    assert (
        client.request.await_args.args[1]
        == "https://strapi.example.com/api/articles"
    )
    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["headers"]["Authorization"] == "Bearer test-api-token"
    assert request_kwargs["json"] == body


@pytest.mark.asyncio
async def test_batch19_unknown_operation_is_rejected():
    connector = _connector_for("stackby")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "drop_everything",
            {},
            {"credentials": {"stackby": {"api_key": "test-api-key"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch19_http_401_maps_to_auth_failure():
    connector = _connector_for("storyblok")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "list_stories",
                {"params": {"space_id": "space1"}},
                {"credentials": {"storyblok": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch19_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)
    assert set(VENDOR_SPECS) == {"stackby", "storyblok", "strapi"}

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_19"
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
        for operation_key, operation in definition.operations.items():
            spec_operation = connector.spec.operations[operation_key]
            assert operation.credential_require == connector.spec.key
            assert operation.node_types == [connector.spec.key]
            assert operation.input_schema["required"] == list(spec_operation.requires)
            assert operation.retryable is spec_operation.retryable
            assert operation.idempotency == spec_operation.idempotency


def test_batch19_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        assert "endpoint_url" not in spec.base_url
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch19_uses_only_expected_hosts():
    assert {spec.base_url for spec in VENDOR_SPECS.values()} == {
        "https://stackby.com/api/betav1",
        "https://mapi.storyblok.com",
        "https://{host}/api",
    }


def test_batch19_reports_unimplemented_catalog_keys():
    assert set(BATCH19_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH19_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH19_KEYS)
    assert set(BATCH19_CATALOG_KEYS) == {
        "split_in_batches",
        "splunk",
        "spotify",
        "spreadsheet_file",
        "stackby",
        "sticky_note",
        "storyblok",
        "strapi",
        "strava",
        "summarize",
    }
    assert set(UNSUPPORTED_BATCH19_KEYS) == {
        "split_in_batches",
        "splunk",
        "spotify",
        "spreadsheet_file",
        "sticky_note",
        "strava",
        "summarize",
    }

    for key, reason in UNSUPPORTED_BATCH19_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch19_unsupported_reasons_are_specific():
    assert "local flow-control" in UNSUPPORTED_BATCH19_KEYS["split_in_batches"]
    assert "form-urlencoded" in UNSUPPORTED_BATCH19_KEYS["splunk"]
    assert "XML" in UNSUPPORTED_BATCH19_KEYS["splunk"]
    assert "OAuth2 authorization-code" in UNSUPPORTED_BATCH19_KEYS["spotify"]
    assert "spreadsheet binaries" in UNSUPPORTED_BATCH19_KEYS["spreadsheet_file"]
    assert "canvas annotation" in UNSUPPORTED_BATCH19_KEYS["sticky_note"]
    assert "OAuth2 authorization-code" in UNSUPPORTED_BATCH19_KEYS["strava"]
    assert "form-encoded" in UNSUPPORTED_BATCH19_KEYS["strava"]
    assert "aggregation" in UNSUPPORTED_BATCH19_KEYS["summarize"]
