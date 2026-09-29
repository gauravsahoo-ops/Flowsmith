"""Unit tests for Box and Typeform connectors (Phase 39)."""

from unittest.mock import AsyncMock, patch
import pytest

from app.connectors import get_registry, register_builtin_connectors, ConnectorError
from app.connectors.box_connector import BoxConnector
from app.connectors.typeform_connector import TypeformConnector


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# =============================================================================
# BOX TESTS
# =============================================================================

def test_box_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("box")
    assert defn is not None
    assert defn.display_name == "Box"
    assert "list_folder_items" in defn.operations
    assert "get_file" in defn.operations
    assert "create_folder" in defn.operations
    assert "delete_file" in defn.operations
    assert "search" in defn.operations
    assert "upload_file" in defn.operations
    assert "webhook" in defn.triggers
    assert "box" in defn.credential_types


@pytest.mark.asyncio
async def test_box_connector_credentials_validation():
    conn = BoxConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("list_folder_items", {})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_box_connector_list_folder_items():
    conn = BoxConnector()
    mock_res = {
        "total_count": 2,
        "entries": [
            {"type": "file", "id": "12345", "name": "Annual_Report.pdf"},
            {"type": "folder", "id": "67890", "name": "Financials"},
        ]
    }
    with patch.object(conn._provider, "request_box", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "list_folder_items",
            {"folder_id": "0"},
            context={"credentials": {"box": {"access_token": "box_mock_token_123"}}}
        )
        assert res["total_count"] == 2
        assert len(res["entries"]) == 2
        assert res["entries"][0]["name"] == "Annual_Report.pdf"


@pytest.mark.asyncio
async def test_box_connector_search():
    conn = BoxConnector()
    mock_res = {
        "total_count": 1,
        "entries": [{"type": "file", "id": "999", "name": "Q3_Budget.xlsx"}]
    }
    with patch.object(conn._provider, "request_box", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "search",
            {"query": "Budget"},
            context={"credentials": {"box": {"access_token": "box_mock_token_123"}}}
        )
        assert res["total_count"] == 1
        assert res["entries"][0]["name"] == "Q3_Budget.xlsx"


# =============================================================================
# TYPEFORM TESTS
# =============================================================================

def test_typeform_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("typeform")
    assert defn is not None
    assert defn.display_name == "Typeform"
    assert "list_forms" in defn.operations
    assert "get_form" in defn.operations
    assert "get_responses" in defn.operations
    assert "create_webhook" in defn.operations
    assert "delete_webhook" in defn.operations
    assert "form_response" in defn.triggers
    assert "typeform" in defn.credential_types


@pytest.mark.asyncio
async def test_typeform_connector_credentials_validation():
    conn = TypeformConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("list_forms", {})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_typeform_connector_get_responses():
    conn = TypeformConnector()
    mock_res = {
        "total_items": 1,
        "page_count": 1,
        "items": [
            {
                "landing_id": "resp_001",
                "token": "tok_abc123",
                "submitted_at": "2026-09-29T10:00:00Z",
                "answers": [
                    {"field": {"id": "fld_1", "type": "text"}, "type": "text", "text": "Customer Feedback"}
                ]
            }
        ]
    }
    with patch.object(conn._provider, "request_typeform", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "get_responses",
            {"form_id": "form_abc"},
            context={"credentials": {"typeform": {"token": "tfp_mock_token"}}}
        )
        assert res["total_items"] == 1
        assert res["items"][0]["token"] == "tok_abc123"
