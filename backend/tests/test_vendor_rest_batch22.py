"""Contract tests for the twenty-second native catalog-conversion batch."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch22 import (
    BATCH22_CATALOG_KEYS,
    UNSUPPORTED_BATCH22_KEYS,
    VENDOR_SPECS,
    build_batch22_connectors,
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
    "host": "vendor.example.com",
    "media_id": "media1",
    "message_id": "message1",
    "order_id": "order1",
    "page_id": "page1",
    "phone_number_id": "phone1",
    "post_id": "post1",
    "product_id": "product1",
    "shorturl": "https://sho.rt/abc",
    "stream_id": "stream1",
    "url": "https://example.com/long/path",
    "user_id": "user1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch22_connectors()


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
        "api_key": "test-api-key",
        "consumer_key": "test-consumer-key",
        "consumer_secret": "test-consumer-secret",
        "email": "user@example.com",
        "password": "test-password",
        "signature": "test-signature",
        "username": "test-user",
    }
    return {field: values[field] for field in spec.credential_fields}


def _expected_basic_header(spec, credentials: dict[str, str]) -> str:
    username = spec.basic_user_literal or credentials.get(spec.basic_user_field, "")
    password = credentials.get(spec.basic_password_field) or spec.default_password
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


@pytest.mark.parametrize(("key", "operation_key"), _OPERATION_CASES)
@pytest.mark.asyncio
async def test_every_batch22_operation_makes_a_fixed_host_request(key, operation_key):
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
    elif spec.auth_kind == "basic":
        assert request_kwargs["headers"]["Authorization"] == _expected_basic_header(
            spec, credentials
        )
    elif spec.auth_kind == "query":
        assert request_kwargs["params"][spec.query_param] == credentials[spec.query_param]
        assert "Authorization" not in request_kwargs["headers"]
    else:  # pragma: no cover - batch 22 only uses bearer, basic, and query auth
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch22_connectors_require_credentials(key):
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
async def test_batch22_yourls_uses_a_fixed_action_and_injects_the_signature():
    connector = _connector_for("yourls")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "shorten",
            {"params": {"host": "short.example.com", "url": "https://example.com/long/path"}},
            {"credentials": {"yourls": {"signature": "secret-signature"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args[1] == (
        "https://short.example.com/yourls-api.php?action=shorturl&format=json"
    )
    assert request_kwargs["params"]["signature"] == "secret-signature"
    assert request_kwargs["params"]["url"] == "https://example.com/long/path"
    assert request_kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch22_whats_app_posts_to_the_phone_number_message_path():
    connector = _connector_for("whats_app")
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "15551234567",
        "type": "text",
        "text": {"body": "Hello"},
    }

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "send_message",
            {"params": {"phone_number_id": "phone1"}, "body": body},
            {"credentials": {"whats_app": {"access_token": "meta-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args[0] == "POST"
    assert client.request.await_args.args[1] == "https://graph.facebook.com/v19.0/phone1/messages"
    assert request_kwargs["headers"]["Authorization"] == "Bearer meta-token"
    assert request_kwargs["json"] == body
    assert request_kwargs["params"] is None


@pytest.mark.asyncio
async def test_batch22_wordpress_updates_with_post_and_basic_auth():
    connector = _connector_for("wordpress")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "update_post",
            {"params": {"host": "blog.example.com", "post_id": "42"}, "body": {"title": "Hello"}},
            {
                "credentials": {
                    "wordpress": {"username": "editor", "password": "application-password"}
                }
            },
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args[0] == "POST"
    assert client.request.await_args.args[1] == (
        "https://blog.example.com/wp-json/wp/v2/posts/42"
    )
    assert request_kwargs["headers"]["Authorization"] == (
        "Basic " + base64.b64encode(b"editor:application-password").decode()
    )
    assert request_kwargs["json"] == {"title": "Hello"}


@pytest.mark.asyncio
async def test_batch22_woocommerce_delete_forces_permanent_deletion():
    connector = _connector_for("woo_commerce")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "delete_product",
            {"params": {"host": "shop.example.com", "product_id": "9"}},
            {
                "credentials": {
                    "woo_commerce": {
                        "consumer_key": "ck_test",
                        "consumer_secret": "cs_test",
                    }
                }
            },
        )

    request_kwargs = client.request.await_args.kwargs
    assert client.request.await_args.args[0] == "DELETE"
    assert client.request.await_args.args[1] == (
        "https://shop.example.com/wp-json/wc/v3/products/9?force=true"
    )
    assert request_kwargs["headers"]["Authorization"] == (
        "Basic " + base64.b64encode(b"ck_test:cs_test").decode()
    )
    assert request_kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch22_http_401_maps_to_auth_failure():
    connector = _connector_for("wordpress")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_post",
                {"params": {"host": "blog.example.com", "post_id": "42"}},
                {"credentials": {"wordpress": {"username": "editor", "password": "bad"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_batch22_unknown_operation_is_rejected():
    connector = _connector_for("zulip")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "send_message",
            {},
            {"credentials": {"zulip": {"email": "user@example.com", "api_key": "x"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


def test_batch22_zulip_only_advertises_query_parameter_reads():
    assert set(VENDOR_SPECS["zulip"].operations) == {
        "get_message",
        "list_streams",
        "list_subscriptions",
        "list_topics",
        "get_user",
        "list_users",
    }
    for operation in VENDOR_SPECS["zulip"].operations.values():
        assert operation.method == "GET"


def test_batch22_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_22"
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


def test_batch22_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch22_reports_unimplemented_catalog_keys():
    assert set(BATCH22_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH22_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH22_KEYS)
    assert set(UNSUPPORTED_BATCH22_KEYS) == {
        "write_binary_file",
        "xml",
        "you_tube",
    }

    for key, reason in UNSUPPORTED_BATCH22_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch22_unsupported_reasons_are_specific():
    assert "local-filesystem" in UNSUPPORTED_BATCH22_KEYS["write_binary_file"]
    assert "local transform" in UNSUPPORTED_BATCH22_KEYS["xml"]
    assert "youTubeOAuth2Api" in UNSUPPORTED_BATCH22_KEYS["you_tube"]
    assert "refresh" in UNSUPPORTED_BATCH22_KEYS["you_tube"]
    assert "resumable uploads" in UNSUPPORTED_BATCH22_KEYS["you_tube"]
