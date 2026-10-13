"""Unit tests for Batch 2 operation expansion: Jira, Notion, HubSpot, and MongoDB.

Verifies newly implemented operations, parameter schemas, negative validation guards,
and definition integrity in ConnectorRegistry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.connectors import get_registry, register_builtin_connectors, ConnectorError
from app.connectors.jira_connector import JiraConnector
from app.connectors.notion_connector import NotionConnector
from app.connectors.hubspot_connector import HubSpotConnector
from app.connectors.mongodb_connector import MongoDBConnector


def _make_response(data: dict[str, Any] | list[Any], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.content = b'{"success": true}'
    return resp


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# =============================================================================
# 1. JIRA OPERATIONS (get_issue, get_projects)
# =============================================================================

@pytest.mark.asyncio
async def test_jira_get_issue_success():
    conn = JiraConnector()
    with patch.object(conn._provider, "request_jira", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "key": "PROJ-123",
            "id": "10001",
            "fields": {"summary": "Fix login bug", "status": {"name": "In Progress"}},
        })
        res = await conn.op_execute(
            "get_issue",
            {"issue_key": "PROJ-123", "field_list": ["summary", "status"]},
            context={"credentials": {"jira": {
                "site_url": "https://example.atlassian.net",
                "email": "dev@example.com",
                "api_token": "token123",
            }}},
        )
        assert res["success"] is True
        assert res["key"] == "PROJ-123"
        assert res["id"] == "10001"
        assert res["issue"]["fields"]["summary"] == "Fix login bug"


@pytest.mark.asyncio
async def test_jira_get_issue_invalid_key():
    conn = JiraConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            "get_issue",
            {"issue_key": "invalid_key_without_dash"},
            context={"credentials": {"jira": {
                "site_url": "https://example.atlassian.net",
                "email": "dev@example.com",
                "api_token": "token123",
            }}},
        )
    assert "A Jira issue key looks like PROJ-123" in str(exc_info.value)


@pytest.mark.asyncio
async def test_jira_get_projects_success():
    conn = JiraConnector()
    with patch.object(conn._provider, "request_jira", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response([
            {"id": "10000", "key": "PROJ", "name": "Main Project"},
            {"id": "10001", "key": "OPS", "name": "Operations"},
        ])
        res = await conn.op_execute(
            "get_projects",
            {},
            context={"credentials": {"jira": {
                "site_url": "https://example.atlassian.net",
                "email": "dev@example.com",
                "api_token": "token123",
            }}},
        )
        assert res["success"] is True
        assert res["count"] == 2
        assert res["projects"][0]["key"] == "PROJ"


# =============================================================================
# 2. NOTION OPERATIONS (get_page, append_block_children)
# =============================================================================

@pytest.mark.asyncio
async def test_notion_get_page_success():
    conn = NotionConnector()
    with patch.object(conn._provider, "request_notion", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "id": "12345678-1234-1234-1234-123456789abc",
            "url": "https://notion.so/12345678123412341234123456789abc",
            "properties": {"Title": {"type": "title"}},
        })
        res = await conn.op_execute(
            "get_page",
            {"page_id": "12345678-1234-1234-1234-123456789abc"},
            context={"credentials": {"notion": {"integration_token": "secret_notion_mock"}}},
        )
        assert res["success"] is True
        assert res["page_id"] == "12345678-1234-1234-1234-123456789abc"
        assert "notion.so" in res["url"]


@pytest.mark.asyncio
async def test_notion_append_block_children_success():
    conn = NotionConnector()
    with patch.object(conn._provider, "request_notion", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "results": [
                {
                    "object": "block",
                    "id": "block_child_123",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "plain_text": "Hello Notion"}]},
                }
            ]
        })
        res = await conn.op_execute(
            "append_block_children",
            {
                "block_id": "12345678-1234-1234-1234-123456789abc",
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "Hello Notion"}}]},
                    }
                ],
            },
            context={"credentials": {"notion": {"integration_token": "secret_notion_mock"}}},
        )
        assert res["success"] is True
        assert res["count"] == 1
        assert res["results"][0]["id"] == "block_child_123"


@pytest.mark.asyncio
async def test_notion_append_block_children_empty_validation():
    conn = NotionConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            "append_block_children",
            {
                "block_id": "12345678-1234-1234-1234-123456789abc",
                "children": [],
            },
            context={"credentials": {"notion": {"integration_token": "secret_notion_mock"}}},
        )
    assert "append_block_children requires a non-empty children array" in str(exc_info.value)


# =============================================================================
# 3. HUBSPOT OPERATIONS (get_properties, associate_records)
# =============================================================================

@pytest.mark.asyncio
async def test_hubspot_get_properties_success():
    conn = HubSpotConnector()
    with patch.object(conn._provider, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "results": [
                {"name": "firstname", "label": "First Name", "type": "string"},
                {"name": "email", "label": "Email", "type": "string"},
            ]
        })
        res = await conn.op_execute(
            "get_properties",
            {"object_type": "contacts"},
            context={"credentials": {"hubspot": {"private_token": "pat-mock-token"}}},
        )
        assert res["success"] is True
        assert res["object_type"] == "contacts"
        assert res["count"] == 2
        assert res["properties"][0]["name"] == "firstname"


@pytest.mark.asyncio
async def test_hubspot_associate_records_success():
    conn = HubSpotConnector()
    with patch.object(conn._provider, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({}, status_code=200)
        res = await conn.op_execute(
            "associate_records",
            {
                "from_object_type": "contacts",
                "from_record_id": "101",
                "to_object_type": "companies",
                "to_record_id": "202",
                "association_type_id": "1",
            },
            context={"credentials": {"hubspot": {"private_token": "pat-mock-token"}}},
        )
        assert res["success"] is True
        assert res["from_object_type"] == "contacts"
        assert res["from_record_id"] == "101"
        assert res["to_object_type"] == "companies"
        assert res["to_record_id"] == "202"
        assert res["association_type_id"] == "1"


@pytest.mark.asyncio
async def test_hubspot_associate_records_missing_ids():
    conn = HubSpotConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            "associate_records",
            {
                "from_object_type": "contacts",
                "from_record_id": "",
                "to_object_type": "companies",
                "to_record_id": "202",
            },
            context={"credentials": {"hubspot": {"private_token": "pat-mock-token"}}},
        )
    assert "operation=associate_records requires from_record_id" in str(exc_info.value)


# =============================================================================
# 4. MONGODB OPERATIONS (aggregate, count_documents)
# =============================================================================

@pytest.mark.asyncio
async def test_mongodb_aggregate_success():
    conn = MongoDBConnector()
    mock_docs = [
        {"_id": "64b000000000000000000001", "total": 150, "status": "A"},
        {"_id": "64b000000000000000000002", "total": 300, "status": "A"},
    ]
    with patch.object(conn._provider, "aggregate", new_callable=AsyncMock) as mock_agg:
        mock_agg.return_value = {"documents": mock_docs, "count": len(mock_docs), "success": True}
        res = await conn.op_execute(
            "aggregate",
            {
                "database": "my_db",
                "collection": "orders",
                "pipeline": [{"$match": {"status": "A"}}],
            },
            context={"credentials": {"mongodb": {"uri": "mongodb://localhost:27017"}}},
        )
        assert res["success"] is True
        assert res["count"] == 2
        assert res["documents"][0]["total"] == 150


@pytest.mark.asyncio
async def test_mongodb_count_documents_success():
    conn = MongoDBConnector()
    with patch.object(conn._provider, "count_documents", new_callable=AsyncMock) as mock_cnt:
        mock_cnt.return_value = {"count": 42, "database": "my_db", "collection": "orders", "success": True}
        res = await conn.op_execute(
            "count_documents",
            {
                "database": "my_db",
                "collection": "orders",
                "filter": {"status": "active"},
            },
            context={"credentials": {"mongodb": {"uri": "mongodb://localhost:27017"}}},
        )
        assert res["success"] is True
        assert res["count"] == 42
        assert res["collection"] == "orders"


# =============================================================================
# 5. REGISTRY AND DEFINITION INTEGRITY
# =============================================================================

def test_batch2_definitions_in_registry():
    register_builtin_connectors()
    registry = get_registry()

    # Jira
    jira_def = registry.get_definition("jira")
    assert jira_def is not None

    assert "get_issue" in jira_def.operations
    assert "get_projects" in jira_def.operations
    assert jira_def.operations["get_issue"].input_schema["required"] == ["issue_key"]

    # Notion
    notion_def = registry.get_definition("notion")
    assert notion_def is not None
    assert "get_page" in notion_def.operations
    assert "append_block_children" in notion_def.operations
    assert notion_def.operations["get_page"].input_schema["required"] == ["page_id"]
    assert "children" in notion_def.operations["append_block_children"].input_schema["required"]

    # HubSpot
    hubspot_def = registry.get_definition("hubspot")
    assert hubspot_def is not None
    assert "get_properties" in hubspot_def.operations
    assert "associate_records" in hubspot_def.operations
    assert hubspot_def.operations["get_properties"].input_schema["required"] == ["object_type"]

    # MongoDB
    mongo_def = registry.get_definition("mongodb")
    assert mongo_def is not None
    assert "aggregate" in mongo_def.operations
    assert "count_documents" in mongo_def.operations
    assert "pipeline" in mongo_def.operations["aggregate"].input_schema["required"]
