"""Contract tests for the twelfth native catalog-conversion batch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.vendor_rest import VendorRESTConnector
from app.connectors.vendor_rest_batch12 import (
    BATCH12_CATALOG_KEYS,
    UNSUPPORTED_BATCH12_KEYS,
    VENDOR_SPECS,
    build_batch12_connectors,
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
    "account_id": "00000000-0000-0000-0000-000000000002",
    "attachment_id": "attachment1",
    "calendar_id": "calendar1",
    "contact_id": "contact1",
    "drive_id": "drive1",
    "entity_set": "accounts",
    "environment_host": "acme.crm.dynamics.com",
    "event_id": "event1",
    "file_id": "file1",
    "folder_id": "folder1",
    "group_id": "group1",
    "item_id": "item1",
    "list_id": "list1",
    "message_id": "message1",
    "parent_id": "parent1",
    "query": "budget",
    "range": "A1:C10",
    "record_id": "00000000-0000-0000-0000-000000000001",
    "region": "crm.dynamics.com",
    "secure_score_control_profile_id": "profile1",
    "secure_score_id": "score1",
    "site_id": "contoso.sharepoint.com,site-id,web-id",
    "subdomain": "acme",
    "table_id": "table1",
    "user_id": "user1",
    "workbook_id": "workbook1",
    "worksheet_id": "worksheet1",
}

_OPERATION_CASES = sorted(
    (key, operation_key)
    for key, spec in VENDOR_SPECS.items()
    for operation_key in spec.operations
)


def _pairs() -> list[tuple[VendorRESTConnector, Any]]:
    return build_batch12_connectors()


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
async def test_every_batch12_operation_makes_a_fixed_host_request(key, operation_key):
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
    assert request_kwargs["headers"]["Authorization"] == "Bearer test-token"

    if operation.method in {"POST", "PUT", "PATCH"}:
        assert request_kwargs["json"] == {"name": "test"}
    else:
        assert request_kwargs["json"] is None


@pytest.mark.parametrize("key", sorted(VENDOR_SPECS))
@pytest.mark.asyncio
async def test_batch12_connectors_require_credentials(key):
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
async def test_batch12_get_forwards_query_parameters():
    connector = _connector_for("microsoft_outlook")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "list_messages",
            {"params": {"$top": 5, "$filter": "isRead eq false"}},
            {"credentials": {"microsoft_outlook": {"access_token": "test-token"}}},
        )

    assert client.request.await_args.kwargs["params"]["$top"] == 5
    assert client.request.await_args.kwargs["params"]["$filter"] == "isRead eq false"
    assert client.request.await_args.kwargs["json"] is None


@pytest.mark.asyncio
async def test_batch12_post_sends_only_the_body():
    connector = _connector_for("microsoft_entra")
    client = AsyncMock()
    client.request.return_value = FakeResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        await connector.op_execute(
            "create_user",
            {
                "params": {"displayName": "ignored-in-body"},
                "body": {"displayName": "Ada Lovelace", "accountEnabled": True},
            },
            {"credentials": {"microsoft_entra": {"access_token": "test-token"}}},
        )

    assert client.request.await_args.kwargs["json"] == {
        "displayName": "Ada Lovelace",
        "accountEnabled": True,
    }
    assert client.request.await_args.kwargs["params"] is None


@pytest.mark.asyncio
async def test_batch12_response_json_is_used_with_a_magicmock_response():
    connector = _connector_for("microsoft_excel")
    response = MagicMock()
    response.status_code = 200
    response.text = '{"value": []}'
    response.json.return_value = {"value": []}
    client = AsyncMock()
    client.request.return_value = response

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        result = await connector.op_execute(
            "list_workbooks",
            {},
            {"credentials": {"microsoft_excel": {"access_token": "test-token"}}},
        )

    assert result["data"] == {"value": []}
    assert client.request.await_args.args[1] == (
        "https://graph.microsoft.com/v1.0/me/drive/root/search(q='.xlsx')"
    )


@pytest.mark.asyncio
async def test_batch12_unknown_operation_is_rejected():
    connector = _connector_for("microsoft_entra")
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("delete_everything", {}, {"credentials": {"microsoft_entra": {"access_token": "x"}}})
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_batch12_http_401_maps_to_auth_failure():
    connector = _connector_for("microsoft_outlook")
    client = AsyncMock()
    client.request.return_value = UnauthorizedResponse()

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "list_messages",
                {},
                {"credentials": {"microsoft_outlook": {"access_token": "bad-token"}}},
            )

    assert exc_info.value.code == ConnectorErrorCode.AUTH_FAILED.value
    assert exc_info.value.retryable is False


def test_batch12_connectors_are_native_definitions():
    pairs = _pairs()
    assert {connector.spec.key for connector, _definition in pairs} == set(VENDOR_SPECS)

    for connector, definition in pairs:
        assert isinstance(connector, VendorRESTConnector)
        assert definition.connector_key == connector.spec.key
        assert definition.metadata.get("implementation") == "native"
        assert definition.metadata.get("batch") == "catalog_conversion_12"
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


def test_batch12_operation_paths_are_host_relative():
    for spec in VENDOR_SPECS.values():
        assert spec.base_url.startswith("https://")
        for operation in spec.operations.values():
            assert operation.path.startswith("/")
            assert "://" not in operation.path
            assert "endpoint_url" not in operation.path


def test_batch12_graph_connectors_use_the_fixed_graph_host():
    for key in (
        "microsoft_entra",
        "microsoft_excel",
        "microsoft_excel_share_point",
        "microsoft_graph_security",
        "microsoft_one_drive",
        "microsoft_outlook",
        "microsoft_sharepoint",
    ):
        assert VENDOR_SPECS[key].base_url.startswith("https://graph.microsoft.com/")
        assert VENDOR_SPECS[key].auth_kind == "bearer"


def test_batch12_environment_hosts_are_template_scoped():
    dataverse = VENDOR_SPECS["microsoft_dataverse"]
    assert dataverse.base_url == "https://{environment_host}/api/data/v9.2"
    assert dataverse.extra_required == ("environment_host",)

    dynamics = VENDOR_SPECS["microsoft_dynamics_crm"]
    assert dynamics.base_url == "https://{subdomain}.{region}/api/data/v9.2"
    assert dynamics.extra_required == ("subdomain", "region")


def test_batch12_reports_unimplemented_catalog_keys():
    assert set(BATCH12_CATALOG_KEYS) == set(VENDOR_SPECS) | set(UNSUPPORTED_BATCH12_KEYS)
    assert not set(VENDOR_SPECS) & set(UNSUPPORTED_BATCH12_KEYS)
    assert set(UNSUPPORTED_BATCH12_KEYS) == {"microsoft_sql"}

    for key, reason in UNSUPPORTED_BATCH12_KEYS.items():
        assert reason.strip()
        assert "VendorRESTConnector" in reason
        assert key not in VENDOR_SPECS


def test_batch12_sql_reason_is_specific():
    assert "TDS" in UNSUPPORTED_BATCH12_KEYS["microsoft_sql"]
    assert "mssql" in UNSUPPORTED_BATCH12_KEYS["microsoft_sql"]
    assert "no REST API" in UNSUPPORTED_BATCH12_KEYS["microsoft_sql"]
