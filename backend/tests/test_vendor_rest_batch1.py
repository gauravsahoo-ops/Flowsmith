"""Contract tests for the first native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorErrorCode, get_registry, register_builtin_connectors
from app.connectors.vendor_rest import VENDOR_SPECS, VendorRESTConnector


class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict[str, Any]:
        return {"ok": True}


@pytest.fixture(autouse=True)
def _register() -> None:
    register_builtin_connectors()


def _params(spec):
    values = {
        "company_domain": "acme",
        "site": "acme",
        "workspace": "acme",
        "domain": "acme",
        "space_id": "space1",
        "environment_id": "master",
        "person_id": "p1",
        "employee_id": "e1",
        "customer_id": "c1",
        "project_slug": "gh/acme/repo",
        "workflow_id": "w1",
        "page_id": "page1",
        "entry_id": "entry1",
        "cluster_id": "cluster1",
        "ticket_id": "ticket1",
        "bitlink": "bit.ly/abc",
    }
    return {key: values[key] for key in spec.extra_required or () if key in values} | {
        key: values[key]
        for op in spec.operations.values()
        for key in op.requires
        if key in values
    }


def _creds(spec):
    return {field: "test-token" for field in spec.credential_fields}


@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
async def test_every_batch_connector_makes_a_fixed_host_request(key):
    spec = VENDOR_SPECS[key]
    connector = get_registry().get(key)
    assert isinstance(connector, VendorRESTConnector)
    operation = next(iter(spec.operations.values()))
    client = AsyncMock()
    client.request.return_value = FakeResponse()
    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            operation.key,
            {"params": _params(spec), "body": {"name": "test"}},
            {"credentials": {spec.key: _creds(spec)}},
        )
    assert result["success"] is True
    assert result["connector"] == key
    url = client.request.await_args.args[1]
    assert url.startswith(spec.base_url.split("{", 1)[0].rstrip("/"))
    assert "endpoint_url" not in url


@pytest.mark.asyncio
async def test_batch_connector_requires_credentials():
    spec = VENDOR_SPECS["circle_ci"]
    connector = get_registry().get("circle_ci")
    assert isinstance(connector, VendorRESTConnector)
    with pytest.raises(Exception) as exc_info:
        await connector.op_execute("get_user", {}, {"credentials": {"circle_ci": {}}})
    assert getattr(exc_info.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value


def test_batch_connectors_are_native_registry_entries():
    registry = get_registry()
    for key in VENDOR_SPECS:
        definition = registry.get_definition(key)
        assert definition is not None
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_1"
        assert definition.operations
