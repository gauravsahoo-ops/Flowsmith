"""Contract tests for the sixteenth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch16 import (
    BATCH16_CATALOG_KEYS,
    BATCH16_KEYS,
    UNSUPPORTED_BATCH16_KEYS,
    VENDOR_SPECS,
    build_batch16_connectors,
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
    "chart": '{"type":"bar","data":{"labels":["A"],"datasets":[{"data":[1]}]}}',
    "notification_name": "wake-up",
    "type": "daily",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


@pytest.fixture(scope="session", autouse=True)
def _pg_harness() -> None:
    """These contract tests mock HTTP and never use the database."""


@pytest.fixture(autouse=True)
def _clean_db() -> None:
    """Override the shared DB cleanup fixture; nothing here touches PostgreSQL."""


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch16_connectors()


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
async def test_every_batch16_operation_makes_a_fixed_host_request(key, operation_key):
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
    if spec.auth_kind == "header":
        assert request_kwargs["headers"][spec.auth_header] == f"{spec.auth_prefix}test-token"
    elif spec.auth_kind == "query":
        assert request_kwargs["params"][spec.query_param] == "test-token"
    elif spec.auth_kind == "none":
        assert "Authorization" not in request_kwargs["headers"]
    else:  # pragma: no cover - batch 16 only uses header, query, and none auth
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(key for key, spec in VENDOR_SPECS.items() if spec.credential_fields))
@pytest.mark.asyncio
async def test_batch16_connectors_require_credentials(key):
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
async def test_batch16_get_forwards_query_parameters():
    connector = _connector_for("profit_well")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_metric",
            {
                "params": {
                    "type": "daily",
                    "month": "2026-10",
                    "metrics": "recurring_revenue,new_customers",
                    "plan_id": "plan1",
                }
            },
            {"credentials": {"profit_well": {"access_token": "test-token"}}},
        )

    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["month"] == "2026-10"
    assert request_kwargs["params"]["metrics"] == "recurring_revenue,new_customers"
    assert request_kwargs["params"]["plan_id"] == "plan1"
    assert request_kwargs["json"] is None
    assert client.request.await_args.args[1] == "https://api.profitwell.com/v2/metrics/daily"


@pytest.mark.asyncio
async def test_batch16_profit_well_uses_the_raw_authorization_header():
    connector = _connector_for("profit_well")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "get_settings",
            {},
            {"credentials": {"profit_well": {"access_token": "test-token"}}},
        )

    headers = client.request.await_args.kwargs["headers"]
    assert headers["Authorization"] == "test-token"
    assert not headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_batch16_pushcut_uses_the_api_key_header():
    connector = _connector_for("pushcut")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "send_notification",
            {
                "params": {"notification_name": "wake-up"},
                "body": {"title": "Backup", "text": "Finished", "devices": ["phone"]},
            },
            {"credentials": {"pushcut": {"api_key": "test-token"}}},
        )

    headers = client.request.await_args.kwargs["headers"]
    assert headers["API-Key"] == "test-token"
    assert client.request.await_args.args[1] == "https://api.pushcut.io/v1/notifications/wake-up"


@pytest.mark.asyncio
async def test_batch16_quick_chart_works_without_credentials():
    connector = _connector_for("quick_chart")
    chart = _PARAM_VALUES["chart"]
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            "create_chart",
            {"params": {"chart": chart, "format": "png", "width": 600}},
            None,
        )

    assert result["success"] is True
    request_kwargs = client.request.await_args.kwargs
    assert request_kwargs["params"]["chart"] == chart
    assert request_kwargs["params"]["format"] == "png"
    assert request_kwargs["params"]["width"] == 600
    assert "Authorization" not in request_kwargs["headers"]
    assert client.request.await_args.args[1] == "https://quickchart.io/chart"


@pytest.mark.asyncio
async def test_batch16_unknown_operation_is_rejected():
    connector = _connector_for("pushcut")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "delete_everything",
            {},
            {"credentials": {"pushcut": {"api_key": "x"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch16_http_401_maps_to_auth_failure():
    connector = _connector_for("profit_well")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "get_settings",
                {},
                {"credentials": {"profit_well": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch16_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)
    assert {connector.spec.key for connector, _definition in pairs} == {
        "profit_well",
        "pushcut",
        "quick_chart",
    }

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_16"
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


def test_batch16_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch16_reports_unimplemented_catalog_keys():
    assert BATCH16_KEYS is BATCH16_CATALOG_KEYS
    assert set(BATCH16_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH16_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH16_KEYS)
    assert set(BATCH16_CATALOG_KEYS) == {
        "profit_well",
        "pushcut",
        "pushover",
        "quest_db",
        "quick_base",
        "quick_books",
        "quick_chart",
        "rabbit_m_q",
        "raindrop",
        "read_binary_file",
    }
    assert set(UNSUPPORTED_BATCH16_KEYS) == {
        "pushover",
        "quest_db",
        "quick_base",
        "quick_books",
        "rabbit_m_q",
        "raindrop",
        "read_binary_file",
    }

    for key, reason in UNSUPPORTED_BATCH16_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch16_unsupported_reasons_are_specific():
    assert "request body" in UNSUPPORTED_BATCH16_KEYS["pushover"]
    assert "PostgreSQL wire-protocol" in UNSUPPORTED_BATCH16_KEYS["quest_db"]
    assert "QB-Realm-Hostname" in UNSUPPORTED_BATCH16_KEYS["quick_base"]
    assert "OAuth2" in UNSUPPORTED_BATCH16_KEYS["quick_books"]
    assert "AMQP" in UNSUPPORTED_BATCH16_KEYS["rabbit_m_q"]
    assert "OAuth2" in UNSUPPORTED_BATCH16_KEYS["raindrop"]
    assert "local filesystem" in UNSUPPORTED_BATCH16_KEYS["read_binary_file"]
