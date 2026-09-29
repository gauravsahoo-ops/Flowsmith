"""Unit tests for Tier-1 AI and Cloud Data connectors: Anthropic, Gemini, and Snowflake (Phase 39)."""

from unittest.mock import AsyncMock, patch
import pytest

from app.connectors import get_registry, register_builtin_connectors, ConnectorError
from app.connectors.anthropic_connector import AnthropicConnector
from app.connectors.gemini_connector import GeminiConnector
from app.connectors.snowflake_connector import SnowflakeConnector


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# =============================================================================
# ANTHROPIC CLAUDE TESTS
# =============================================================================

def test_anthropic_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("anthropic")
    assert defn is not None
    assert defn.display_name == "Anthropic Claude"
    assert "generate_message" in defn.operations
    assert "count_tokens" in defn.operations
    assert "anthropic" in defn.credential_types


@pytest.mark.asyncio
async def test_anthropic_connector_credentials_validation():
    conn = AnthropicConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("generate_message", {"prompt": "Hello"})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_anthropic_connector_generate_message():
    conn = AnthropicConnector()
    mock_res = {
        "id": "msg_01X9",
        "model": "claude-3-5-sonnet-20241022",
        "role": "assistant",
        "content": [{"type": "text", "text": "FlowSmith is an advanced integration and workflow platform."}],
        "usage": {"input_tokens": 12, "output_tokens": 10},
    }
    with patch.object(conn._provider, "request_anthropic", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "generate_message",
            {"prompt": "What is FlowSmith?"},
            context={"credentials": {"anthropic": {"api_key": "sk-ant-test-key"}}}
        )
        assert res["text"] == "FlowSmith is an advanced integration and workflow platform."
        assert res["model"] == "claude-3-5-sonnet-20241022"
        assert res["usage"]["output_tokens"] == 10


# =============================================================================
# GOOGLE GEMINI TESTS
# =============================================================================

def test_gemini_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("gemini")
    assert defn is not None
    assert defn.display_name == "Google Gemini"
    assert "generate_content" in defn.operations
    assert "embed_content" in defn.operations
    assert "count_tokens" in defn.operations
    assert "gemini" in defn.credential_types


@pytest.mark.asyncio
async def test_gemini_connector_credentials_validation():
    conn = GeminiConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("generate_content", {"prompt": "Explain workflows"})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_gemini_connector_generate_content():
    conn = GeminiConnector()
    mock_res = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Workflows automate discrete sequential processes."}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 8, "totalTokenCount": 13},
    }
    with patch.object(conn._provider, "request_gemini", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "generate_content",
            {"prompt": "Explain workflows"},
            context={"credentials": {"gemini": {"api_key": "AIzaSyTestKey123"}}}
        )
        assert "automate discrete" in res["text"]
        assert res["model"] == "gemini-1.5-flash"


@pytest.mark.asyncio
async def test_gemini_connector_embed_content():
    conn = GeminiConnector()
    mock_res = {
        "embedding": {
            "values": [0.0123, -0.0456, 0.0789]
        }
    }
    with patch.object(conn._provider, "request_gemini", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "embed_content",
            {"text": "Embedding vector test"},
            context={"credentials": {"gemini": {"api_key": "AIzaSyTestKey123"}}}
        )
        assert len(res["values"]) == 3
        assert res["values"][0] == 0.0123


# =============================================================================
# SNOWFLAKE DATA CLOUD TESTS
# =============================================================================

def test_snowflake_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("snowflake")
    assert defn is not None
    assert defn.display_name == "Snowflake Data Cloud"
    assert "execute_query" in defn.operations
    assert "get_query_results" in defn.operations
    assert "cancel_query" in defn.operations
    assert "describe_table" in defn.operations
    assert "list_tables" in defn.operations
    assert "snowflake" in defn.credential_types


@pytest.mark.asyncio
async def test_snowflake_connector_credentials_validation():
    conn = SnowflakeConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("execute_query", {"statement": "SELECT 1;"})
    assert "NOT_CONFIGURED" in exc_info.value.code


@pytest.mark.asyncio
async def test_snowflake_connector_execute_query():
    conn = SnowflakeConnector()
    mock_res = {
        "statementHandle": "01b0abcd-0000-1234-0000-000123456789",
        "code": "090000",
        "sqlState": "00000",
        "resultSetMetaData": {
            "numRows": 2,
            "rowType": [
                {"name": "ID", "type": "fixed", "precision": 38, "scale": 0},
                {"name": "NAME", "type": "text", "length": 100},
            ]
        },
        "data": [
            ["1", "Customer A"],
            ["2", "Customer B"],
        ]
    }
    with patch.object(conn._provider, "request_snowflake", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "execute_query",
            {"statement": "SELECT ID, NAME FROM CUSTOMERS LIMIT 2;"},
            context={"credentials": {"snowflake": {"account": "xy12345.us-east-1", "token": "mock_jwt_token"}}}
        )
        assert res["statementHandle"] == "01b0abcd-0000-1234-0000-000123456789"
        assert len(res["data"]) == 2
        assert res["resultSetMetaData"]["numRows"] == 2


@pytest.mark.asyncio
async def test_snowflake_connector_describe_table():
    conn = SnowflakeConnector()
    mock_res = {
        "statementHandle": "01b0abcd-0000-1234-0000-000123456790",
        "code": "090000",
        "data": [
            ["ID", "NUMBER(38,0)", "COLUMN", "N", "None", "N", "N", "None", "None", "None"],
            ["EMAIL", "VARCHAR(255)", "COLUMN", "Y", "None", "N", "N", "None", "None", "None"],
        ]
    }
    with patch.object(conn._provider, "request_snowflake", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_res
        res = await conn.op_execute(
            "describe_table",
            {"table_name": "USERS", "schema": "PUBLIC", "database": "PROD_DB"},
            context={"credentials": {"snowflake": {"account": "xy12345.us-east-1", "token": "mock_jwt_token"}}}
        )
        assert res["statementHandle"] == "01b0abcd-0000-1234-0000-000123456790"
        assert len(res["data"]) == 2
