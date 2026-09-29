"""Unit tests for Phase 40 backlog connectors: BigQuery, SendGrid, Intercom, DocuSign, Coda, Xero, Zoho CRM, Freshsales, ActiveCampaign."""

from unittest.mock import AsyncMock, patch
import pytest

from app.connectors import get_registry, register_builtin_connectors, ConnectorError
from app.connectors.bigquery_connector import BigQueryConnector
from app.connectors.sendgrid_connector import SendGridConnector
from app.connectors.intercom_connector import IntercomConnector
from app.connectors.docusign_connector import DocuSignConnector
from app.connectors.coda_connector import CodaConnector
from app.connectors.xero_connector import XeroConnector
from app.connectors.zoho_crm_connector import ZohoCrmConnector
from app.connectors.freshsales_connector import FreshsalesConnector
from app.connectors.activecampaign_connector import ActiveCampaignConnector


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# =============================================================================
# 1. BIGQUERY
# =============================================================================

def test_bigquery_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("bigquery")
    assert defn is not None
    assert defn.display_name == "Google BigQuery"
    assert "query" in defn.operations
    assert "get_query_results" in defn.operations
    assert "list_datasets" in defn.operations
    assert "list_tables" in defn.operations
    assert "get_table" in defn.operations
    assert "bigquery" in defn.credential_types


@pytest.mark.asyncio
async def test_bigquery_connector_query():
    conn = BigQueryConnector()
    mock_res = {
        "jobReference": {"jobId": "job_123"},
        "schema": {"fields": [{"name": "total", "type": "INTEGER"}]},
        "rows": [{"f": [{"v": "42"}]}],
        "totalRows": "1",
    }
    with patch.object(conn._provider, "request_bigquery", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "query",
            {"query": "SELECT 42 as total;"},
            context={"credentials": {"bigquery": {"project_id": "flowsmith-prod", "access_token": "mock_token"}}}
        )
        assert res["totalRows"] == "1"
        assert res["jobReference"]["jobId"] == "job_123"


# =============================================================================
# 2. SENDGRID
# =============================================================================

def test_sendgrid_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("sendgrid")
    assert defn is not None
    assert defn.display_name == "Twilio SendGrid"
    assert "send_mail" in defn.operations
    assert "list_contacts" in defn.operations
    assert "event_webhook" in defn.triggers
    assert "sendgrid" in defn.credential_types


@pytest.mark.asyncio
async def test_sendgrid_connector_send_mail():
    conn = SendGridConnector()
    mock_res = {"success": True, "message": "Email accepted for delivery"}
    with patch.object(conn._provider, "request_sendgrid", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "send_mail",
            {"to_email": "user@example.com", "from_email": "alerts@flowsmith.io", "subject": "Workflow Alert", "content": "Job completed."},
            context={"credentials": {"sendgrid": {"api_key": "SG.mock_key"}}}
        )
        assert res["success"] is True


# =============================================================================
# 3. INTERCOM
# =============================================================================

def test_intercom_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("intercom")
    assert defn is not None
    assert defn.display_name == "Intercom"
    assert "list_conversations" in defn.operations
    assert "reply_conversation" in defn.operations
    assert "search_contacts" in defn.operations
    assert "conversation_webhook" in defn.triggers
    assert "intercom" in defn.credential_types


@pytest.mark.asyncio
async def test_intercom_connector_search_contacts():
    conn = IntercomConnector()
    mock_res = {
        "type": "list",
        "data": [{"type": "contact", "id": "cont_999", "email": "customer@acme.com"}],
        "total_count": 1,
    }
    with patch.object(conn._provider, "request_intercom", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "search_contacts",
            {"field": "email", "operator": "=", "value": "customer@acme.com"},
            context={"credentials": {"intercom": {"access_token": "mock_intercom_token"}}}
        )
        assert res["total_count"] == 1
        assert res["data"][0]["email"] == "customer@acme.com"


# =============================================================================
# 4. DOCUSIGN
# =============================================================================

def test_docusign_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("docusign")
    assert defn is not None
    assert defn.display_name == "DocuSign"
    assert "create_envelope" in defn.operations
    assert "get_envelope" in defn.operations
    assert "envelope_status_webhook" in defn.triggers
    assert "docusign" in defn.credential_types


@pytest.mark.asyncio
async def test_docusign_connector_get_envelope():
    conn = DocuSignConnector()
    mock_res = {"envelopeId": "env_001", "status": "completed"}
    with patch.object(conn._provider, "request_docusign", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "get_envelope",
            {"envelope_id": "env_001"},
            context={"credentials": {"docusign": {"account_id": "acc_123", "access_token": "mock_ds_token"}}}
        )
        assert res["status"] == "completed"


# =============================================================================
# 5. CODA
# =============================================================================

def test_coda_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("coda")
    assert defn is not None
    assert defn.display_name == "Coda"
    assert "list_docs" in defn.operations
    assert "list_rows" in defn.operations
    assert "coda" in defn.credential_types


@pytest.mark.asyncio
async def test_coda_connector_list_docs():
    conn = CodaConnector()
    mock_res = {
        "items": [{"id": "doc_xyz", "name": "Sprint Roadmap", "type": "doc"}],
        "href": "https://coda.io/apis/v1/docs",
    }
    with patch.object(conn._provider, "request_coda", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "list_docs",
            {},
            context={"credentials": {"coda": {"api_key": "coda_mock_token"}}}
        )
        assert len(res["items"]) == 1
        assert res["items"][0]["name"] == "Sprint Roadmap"


# =============================================================================
# 6. XERO
# =============================================================================

def test_xero_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("xero")
    assert defn is not None
    assert defn.display_name == "Xero"
    assert "list_invoices" in defn.operations
    assert "create_invoice" in defn.operations
    assert "xero" in defn.credential_types


@pytest.mark.asyncio
async def test_xero_connector_list_invoices():
    conn = XeroConnector()
    mock_res = {
        "Invoices": [{"InvoiceID": "inv_101", "Type": "ACCREC", "Status": "PAID"}]
    }
    with patch.object(conn._provider, "request_xero", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "list_invoices",
            {"page": 1},
            context={"credentials": {"xero": {"tenant_id": "tenant_abc", "access_token": "mock_xero_token"}}}
        )
        assert len(res["Invoices"]) == 1
        assert res["Invoices"][0]["Status"] == "PAID"


# =============================================================================
# 7. ZOHO CRM
# =============================================================================

def test_zoho_crm_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("zoho_crm")
    assert defn is not None
    assert defn.display_name == "Zoho CRM"
    assert "list_records" in defn.operations
    assert "search_records" in defn.operations
    assert "zoho_crm" in defn.credential_types


@pytest.mark.asyncio
async def test_zoho_crm_connector_list_records():
    conn = ZohoCrmConnector()
    mock_res = {
        "data": [{"id": "lead_123", "First_Name": "Alice", "Last_Name": "Smith"}],
        "info": {"per_page": 50, "count": 1, "page": 1, "more_records": False},
    }
    with patch.object(conn._provider, "request_zoho", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "list_records",
            {"module": "Leads", "page": 1},
            context={"credentials": {"zoho_crm": {"access_token": "zoho_mock_token"}}}
        )
        assert len(res["data"]) == 1
        assert res["data"][0]["First_Name"] == "Alice"


# =============================================================================
# 8. FRESHSALES
# =============================================================================

def test_freshsales_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("freshsales")
    assert defn is not None
    assert defn.display_name == "Freshsales"
    assert "list_contacts" in defn.operations
    assert "create_deal" in defn.operations
    assert "freshsales" in defn.credential_types


@pytest.mark.asyncio
async def test_freshsales_connector_list_contacts():
    conn = FreshsalesConnector()
    mock_res = {
        "contacts": [{"id": "fs_cont_1", "first_name": "Bob", "last_name": "Jones"}]
    }
    with patch.object(conn._provider, "request_freshsales", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "list_contacts",
            {"page": 1},
            context={"credentials": {"freshsales": {"domain": "acme", "api_key": "fs_mock_key"}}}
        )
        assert len(res["contacts"]) == 1
        assert res["contacts"][0]["first_name"] == "Bob"


# =============================================================================
# 9. ACTIVECAMPAIGN
# =============================================================================

def test_activecampaign_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("activecampaign")
    assert defn is not None
    assert defn.display_name == "ActiveCampaign"
    assert "list_contacts" in defn.operations
    assert "list_lists" in defn.operations
    assert "activecampaign" in defn.credential_types


@pytest.mark.asyncio
async def test_activecampaign_connector_list_contacts():
    conn = ActiveCampaignConnector()
    mock_res = {
        "contacts": [{"id": "ac_1", "email": "lead@campaign.com"}],
        "meta": {"total": 1},
    }
    with patch.object(conn._provider, "request_activecampaign", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "list_contacts",
            {"limit": 10},
            context={"credentials": {"activecampaign": {"account": "marketingcorp", "api_key": "ac_mock_key"}}}
        )
        assert len(res["contacts"]) == 1
        assert res["contacts"][0]["email"] == "lead@campaign.com"
