"""Contract tests for the eighth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch8 import (
    BATCH8_CATALOG_KEYS,
    UNSUPPORTED_BATCH8_KEYS,
    VENDOR_SPECS,
    build_batch8_connectors,
)


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict[str, Any]:
        return {"ok": True}


_PARAM_VALUES: dict[str, str] = {
    "certificate_id": "cert1",
    "collection": "articles",
    "form": "contact",
    "form_id": "form1",
    "goal_name": "steps",
    "host": "cockpit.example.com",
    "list_id": "list1",
    "project_id": "project1",
    "singleton": "settings",
    "tag_id": "tag1",
    "task_id": "task1",
    "team_id": "team1",
    "time_entry_id": "entry1",
    "workspace_id": "workspace1",
    "zone_id": "zone1",
}


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch8_connectors()


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


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_every_batch8_connector_makes_a_fixed_host_request(key):
    spec = VENDOR_SPECS[key]
    connector = _connector_for(key)
    assert isinstance(connector, VendorRESTConnector)

    operation = next(iter(spec.operations.values()))
    params = _params(spec)
    credentials = _creds(spec)
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            operation.key,
            {"params": params, "body": {"name": "test"}},
            {"credentials": {spec.key: credentials}},
        )

    assert result["success"] is True
    assert result["connector"] == key

    method, url = client.request.await_args.args
    assert method == operation.method
    expected_base = spec.base_url.format(**params, **credentials).rstrip("/")
    assert url == expected_base or url.startswith(f"{expected_base}/")
    assert "endpoint_url" not in url

    request_kwargs = client.request.await_args.kwargs
    if spec.auth_kind == "bearer":
        assert request_kwargs["headers"]["Authorization"] == "Bearer test-token"
    elif spec.auth_kind == "header":
        assert request_kwargs["headers"][spec.auth_header] == f"{spec.auth_prefix}test-token"
    elif spec.auth_kind == "query":
        assert request_kwargs["params"][spec.query_param] == "test-token"
    else:  # pragma: no cover - no batch 8 spec uses another auth kind
        raise AssertionError(f"Unexpected auth kind for {key}: {spec.auth_kind}")


@pytest.mark.parametrize("key", ["beeminder", "click_up", "cloudflare", "cockpit"])
@pytest.mark.asyncio
async def test_batch8_connector_requires_credentials(key):
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


def test_batch8_connectors_are_native_definitions():
    pairs = _pairs()
    implemented_keys = set(BATCH8_CATALOG_KEYS) - set(UNSUPPORTED_BATCH8_KEYS)
    assert {connector.spec.key for connector, _definition in pairs} == implemented_keys

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_8"
        assert definition.lifecycle_status == "beta"
        assert definition.operations
        assert set(definition.operations) == set(connector.spec.operations)
        assert definition.credential_types
        credential = definition.credential_types[connector.spec.key]
        assert credential.secret_fields == list(connector.spec.credential_fields)
        assert credential.encryption_required is True
        for operation in definition.operations.values():
            assert operation.credential_require == connector.spec.key
            assert operation.node_types == [connector.spec.key]


def test_batch8_catalog_keys_are_accounted_for():
    assert set(VENDOR_SPECS).isdisjoint(UNSUPPORTED_BATCH8_KEYS)
    assert set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH8_KEYS) == set(BATCH8_CATALOG_KEYS)
    assert all(reason.strip() for reason in UNSUPPORTED_BATCH8_KEYS.values())
    assert {connector.spec.key for connector, _definition in _pairs()} == set(VENDOR_SPECS)


def test_batch8_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "endpoint_url" not in operation.path
