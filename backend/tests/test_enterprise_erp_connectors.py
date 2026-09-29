"""Unit tests for Tier-1 Enterprise ERP connectors: SAP S/4HANA, Workday, and Oracle NetSuite."""

from unittest.mock import AsyncMock, patch
import pytest

from app.connectors import get_registry, register_builtin_connectors, ConnectorError
from app.connectors.sap_connector import SapConnector
from app.connectors.workday_connector import WorkdayConnector
from app.connectors.netsuite_connector import NetSuiteConnector


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# =============================================================================
# SAP S/4HANA TESTS
# =============================================================================

def test_sap_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("sap")
    assert defn is not None
    assert defn.display_name == "SAP S/4HANA"
    assert "query_odata" in defn.operations
    assert "get_entity" in defn.operations
    assert "create_entity" in defn.operations
    assert "update_entity" in defn.operations
    assert "delete_entity" in defn.operations
    assert "get_metadata" in defn.operations
    assert "business_event" in defn.triggers
    assert "sap" in defn.credential_types


@pytest.mark.asyncio
async def test_sap_connector_credentials_validation():
    conn = SapConnector()
    # Missing base_url raises ConnectorError
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("query_odata", {"service": "API_BUSINESS_PARTNER", "entity_set": "A_BusinessPartner"})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_sap_connector_query_odata():
    conn = SapConnector()
    mock_res = {
        "results": [
            {"BusinessPartner": "1000001", "BusinessPartnerCategory": "1", "FirstName": "John", "LastName": "Doe"},
            {"BusinessPartner": "1000002", "BusinessPartnerCategory": "2", "OrganizationBPName1": "Acme Corp"},
        ]
    }
    with patch.object(conn._provider, "request_sap", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "query_odata",
            {"service": "API_BUSINESS_PARTNER", "entity_set": "A_BusinessPartner", "top": 2},
            context={"credentials": {"sap": {"base_url": "https://my-s4hana.s4hana.ondemand.com", "username": "DEMO", "password": "PW"}}}
        )
        assert res["service"] == "API_BUSINESS_PARTNER"
        assert res["count"] == 2
        assert res["results"][0]["BusinessPartner"] == "1000001"


# =============================================================================
# WORKDAY TESTS
# =============================================================================

def test_workday_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("workday")
    assert defn is not None
    assert defn.display_name == "Workday"
    assert "query_wql" in defn.operations
    assert "list_workers" in defn.operations
    assert "get_worker" in defn.operations
    assert "update_worker" in defn.operations
    assert "get_organization" in defn.operations
    assert "create_requisition" in defn.operations
    assert "outbound_event" in defn.triggers
    assert "workday" in defn.credential_types


@pytest.mark.asyncio
async def test_workday_connector_credentials_validation():
    conn = WorkdayConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("list_workers", {})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_workday_connector_query_wql():
    conn = WorkdayConnector()
    mock_res = {
        "total": 1,
        "data": [{"worker": "W-1042", "primaryWorkEmail": "worker@example.com", "legalName": "Jane Doe"}]
    }
    with patch.object(conn._provider, "request_workday", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "query_wql",
            {"query": "SELECT worker, primaryWorkEmail FROM allWorkers", "limit": 10},
            context={"credentials": {"workday": {"host": "https://wd2-impl-services1.workday.com", "tenant": "my_tenant", "token": "mock_token"}}}
        )
        assert res["count"] == 1
        assert res["data"][0]["worker"] == "W-1042"


# =============================================================================
# ORACLE NETSUITE TESTS
# =============================================================================

def test_netsuite_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("netsuite")
    assert defn is not None
    assert defn.display_name == "Oracle NetSuite ERP"
    assert "query_suiteql" in defn.operations
    assert "list_records" in defn.operations
    assert "get_record" in defn.operations
    assert "create_record" in defn.operations
    assert "update_record" in defn.operations
    assert "delete_record" in defn.operations
    assert "get_metadata" in defn.operations
    assert "webhook" in defn.triggers
    assert "netsuite" in defn.credential_types


@pytest.mark.asyncio
async def test_netsuite_connector_credentials_validation():
    conn = NetSuiteConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("list_records", {"record_type": "customer"})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_netsuite_connector_query_suiteql():
    conn = NetSuiteConnector()
    mock_res = {
        "totalResults": 2,
        "hasMore": False,
        "items": [
            {"id": "101", "entityid": "CUST-101", "email": "customer1@example.com"},
            {"id": "102", "entityid": "CUST-102", "email": "customer2@example.com"},
        ]
    }
    with patch.object(conn._provider, "request_netsuite", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "query_suiteql",
            {"query": "SELECT id, entityid, email FROM customer", "limit": 10},
            context={"credentials": {"netsuite": {"account_id": "1234567", "token": "mock_ns_token"}}}
        )
        assert res["total_results"] == 2
        assert res["count"] == 2
        assert res["items"][0]["entityid"] == "CUST-101"
