"""Comprehensive Test Suite for Flowsmith Advanced AI Engine.

Tests:
1. Multi-Provider LLM Engine (OpenAI, Anthropic, Gemini, DeepSeek, Groq, Ollama formatting & routing)
2. Tri-Tier Agent Memory (Working, Summary Buffer, Episodic Vector)
3. Advanced RAG Engine (Recursive/Markdown Splitters, BM25, Reciprocal Rank Fusion)
4. Dynamic Tool Registry (Calculator, Current Time, Approval Gates)
5. MCP Client (Tool Discovery & Conversion)
6. Autonomous ReAct Agent Node Execution with Memory & Tools
"""

import pytest
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.providers import (
    get_provider,
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    DeepSeekProvider,
    GroqProvider,
    OllamaProvider,
    LLMResponse,
    ToolCall,
)
from app.ai.client import chat_completion
from app.ai.memory import WorkingMemory, SummaryBufferMemory, EpisodicVectorMemory
from app.ai.rag import (
    RecursiveTextSplitter,
    MarkdownTextSplitter,
    DocumentChunk,
    reciprocal_rank_fusion,
    simple_bm25_search,
)
from app.ai.tools import TOOLS, run_tool, ToolSpec, openai_tools
from app.ai.mcp_client import MCPClient
from app.nodes.ai_agent import AIAgentNode, AgentParams
from app.engine.node_base import NodeContext, MemoryKVStore


def _make_ctx(
    execution_id: str = "test",
    credentials: dict[str, Any] | None = None,
    storage: Any = None,
) -> NodeContext:
    return NodeContext(
        execution_id=execution_id,
        workflow_id="wf_test",
        node_id="node_test",
        logger=logging.getLogger("test_ai"),
        http_client=AsyncMock(),
        storage=storage or MemoryKVStore(),
        credentials=credentials or {},
    )


# ---------------------------------------------------------------------------
# 1. Multi-Provider LLM Engine Tests
# ---------------------------------------------------------------------------

def test_provider_resolution():
    """Verify get_provider resolves correct classes from names or models."""
    assert isinstance(get_provider("openai"), OpenAIProvider)
    assert isinstance(get_provider("anthropic"), AnthropicProvider)
    assert isinstance(get_provider(model="claude-3-5-sonnet-20241022"), AnthropicProvider)
    assert isinstance(get_provider("gemini"), GeminiProvider)
    assert isinstance(get_provider(model="gemini-2.0-flash"), GeminiProvider)
    assert isinstance(get_provider("deepseek"), DeepSeekProvider)
    assert isinstance(get_provider("groq"), GroqProvider)
    assert isinstance(get_provider("ollama"), OllamaProvider)


@pytest.mark.asyncio
async def test_openai_provider_mock():
    """Verify OpenAIProvider correctly parses choices and tool calls."""
    prov = OpenAIProvider()
    mock_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Result",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "calculator", "arguments": "{\"expression\": \"2 + 2\"}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response
        mock_post.return_value = mock_resp

        res = await prov.chat(
            messages=[{"role": "user", "content": "Calculate 2+2"}],
            model="gpt-4o",
            api_key="test_key",
        )

        assert res.content == "Result"
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "calculator"
        assert res.tool_calls[0].arguments == {"expression": "2 + 2"}


@pytest.mark.asyncio
async def test_anthropic_provider_conversion():
    """Verify AnthropicProvider converts OpenAI schemas to native Anthropic format."""
    prov = AnthropicProvider()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calc",
                "description": "Calculate formula",
                "parameters": {"type": "object", "properties": {"expr": {"type": "string"}}},
            },
        }
    ]
    converted = prov._convert_tools(tools)
    assert len(converted) == 1
    assert converted[0]["name"] == "calc"
    assert "input_schema" in converted[0]

    system, formatted = prov._format_messages([
        {"role": "system", "content": "You are a math helper."},
        {"role": "user", "content": "Hello!"},
    ])
    assert system == "You are a math helper."
    assert len(formatted) == 1
    assert formatted[0]["role"] == "user"


# ---------------------------------------------------------------------------
# 2. Tri-Tier Memory Tests
# ---------------------------------------------------------------------------

def test_working_memory_sliding_window():
    """Verify WorkingMemory retains only the specified window length."""
    mem = WorkingMemory(max_entries=3)
    mem.add_message("user", "msg1")
    mem.add_message("assistant", "msg2")
    mem.add_message("user", "msg3")
    mem.add_message("assistant", "msg4")

    msgs = mem.get_messages()
    assert len(msgs) == 3
    assert msgs[0]["content"] == "msg2"
    assert msgs[2]["content"] == "msg4"


@pytest.mark.asyncio
async def test_summary_buffer_memory():
    """Verify SummaryBufferMemory compresses older turns via summarizer."""
    mem = SummaryBufferMemory(max_recent_entries=2)
    mem.add_message("user", "My favorite color is emerald green.")
    mem.add_message("assistant", "Noted, emerald green.")
    mem.add_message("user", "What is 10 + 10?")
    mem.add_message("assistant", "It is 20.")

    async def mock_llm_summarizer(*args, **kwargs):
        return {"content": "User prefers emerald green."}

    await mem.compress_if_needed(mock_llm_summarizer, {"model": "test"})
    msgs = mem.get_messages()

    # Should contain 1 system summary prefix + 2 recent messages
    assert len(msgs) == 3
    assert msgs[0]["role"] == "system"
    assert "User prefers emerald green" in msgs[0]["content"]
    assert msgs[1]["content"] == "What is 10 + 10?"


@pytest.mark.asyncio
async def test_episodic_vector_memory():
    """Verify EpisodicVectorMemory stores and recalls relevant facts."""
    mem = EpisodicVectorMemory(session_id="test_user_42")
    await mem.store_memory("User lives in San Francisco and prefers Python over JavaScript.")
    await mem.store_memory("User is working on the Flowsmith automation platform.")

    results = await mem.recall_relevant_memories("Where does the user live?")
    assert len(results) >= 1
    assert "San Francisco" in results[0]


# ---------------------------------------------------------------------------
# 3. Advanced RAG Engine Tests
# ---------------------------------------------------------------------------

def test_recursive_text_splitter():
    """Verify RecursiveTextSplitter chunks text with natural boundary preservation."""
    text = "Paragraph one with some details.\n\nParagraph two with more details.\n\nParagraph three concluding."
    splitter = RecursiveTextSplitter(chunk_size=40, chunk_overlap=10)
    chunks = splitter.split_text(text)

    assert len(chunks) >= 3
    assert all(len(c) <= 60 for c in chunks)


def test_markdown_text_splitter():
    """Verify MarkdownTextSplitter respects markdown header boundaries."""
    md = "# Introduction\nThis is the intro section.\n\n# Architecture\nThis covers the core engine."
    splitter = MarkdownTextSplitter(chunk_size=100)
    chunks = splitter.split_text(md)

    assert len(chunks) == 2
    assert chunks[0].startswith("# Introduction")
    assert chunks[1].startswith("# Architecture")


def test_hybrid_search_rrf():
    """Verify Reciprocal Rank Fusion correctly scores and merges dense and sparse results."""
    doc1 = DocumentChunk(chunk_id="c1", text="Python async programming with FastAPI.")
    doc2 = DocumentChunk(chunk_id="c2", text="PostgreSQL pgvector cosine distance.")
    doc3 = DocumentChunk(chunk_id="c3", text="Flowsmith automation platform architecture.")

    dense = [doc1, doc2]
    sparse = [doc2, doc3]

    fused = reciprocal_rank_fusion(dense, sparse, k=60, top_n=3)
    # doc2 appeared in both rankings, so it should rank highest!
    assert fused[0].chunk_id == "c2"
    assert fused[0].score > fused[1].score


def test_simple_bm25():
    """Verify BM25 keyword matching returns relevant matches."""
    chunks = [
        DocumentChunk(chunk_id="1", text="The quick brown fox jumps over the lazy dog."),
        DocumentChunk(chunk_id="2", text="Deep learning and artificial intelligence with PyTorch."),
        DocumentChunk(chunk_id="3", text="FastAPI high-performance asynchronous Python web framework."),
    ]
    results = simple_bm25_search("PyTorch artificial intelligence", chunks, top_k=2)
    assert len(results) >= 1
    assert results[0].chunk_id == "2"


# ---------------------------------------------------------------------------
# 4. Dynamic Tool Registry Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calculator_tool():
    """Verify calculator tool evaluates mathematical formulas securely."""
    ctx = _make_ctx(execution_id="test", credentials={})
    res = await run_tool(ctx, "calculator", {"expression": "(1250 * 0.2) + 40"})
    assert res == "290.0"

    # Verify disallowed code execution is rejected
    res_bad = await run_tool(ctx, "calculator", {"expression": "__import__('os').system('dir')"})
    assert "Error: Invalid math expression" in res_bad


@pytest.mark.asyncio
async def test_tool_approval_gate():
    """Verify tools flagged with requires_approval pause with a pending status."""
    def dummy_delete(ctx, args):
        return "Deleted"

    spec = ToolSpec(
        name="delete_database",
        description="Dangerous delete",
        parameters={},
        handler=dummy_delete,
        requires_approval=True,
    )
    TOOLS["delete_database"] = spec

    ctx = _make_ctx(execution_id="test", credentials={})
    output = await run_tool(ctx, "delete_database", {})
    parsed = json.loads(output)
    assert parsed.get("status") == "pending_approval"


# ---------------------------------------------------------------------------
# 5. MCP Client Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_client_tool_conversion():
    """Verify MCPClient converts external MCP tool schemas into ToolSpecs."""
    client = MCPClient("http://localhost:8999/mcp")
    mcp_tools = [
        {
            "name": "search_github",
            "description": "Search GitHub repositories",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    specs = client.convert_to_tool_specs(mcp_tools)
    assert len(specs) == 1
    assert specs[0].name == "mcp_search_github"
    assert specs[0].category == "mcp"
    assert specs[0].parameters["required"] == ["query"]


# ---------------------------------------------------------------------------
# 6. Autonomous ReAct Agent Node Execution Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_agent_node_execution():
    """Verify AIAgentNode executes ReAct reasoning loop with tools and memory."""
    node = AIAgentNode()
    ctx = _make_ctx(
        execution_id="test_exec_001",
        credentials={"llm": {"provider": "openai", "api_key": "test", "model": "gpt-4o"}},
        storage=MemoryKVStore(),
    )
    params = AgentParams(
        instructions="You are a helpful math agent.",
        input="What is 100 * 5?",
        tools=["calculator"],
        memory_type="window",
        session_id="test_session",
    )

    # Mock chat_completion:
    # 1st call -> emit tool call to calculator
    # 2nd call -> emit final answer
    call_count = 0

    async def mock_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "role": "assistant",
                "content": "I will calculate 100 * 5.",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": "{\"expression\": \"100 * 5\"}"},
                    }
                ],
            }
        return {
            "role": "assistant",
            "content": "The answer is 500.",
        }

    with patch("app.nodes.ai_agent.chat_completion", side_effect=mock_chat):
        result = await node.run(ctx, params, [])

        assert len(result.output_items) == 1
        item = result.output_items[0]
        assert item["final_answer"] == "The answer is 500."
        assert "calculator" in item["tools_used"]
        assert item["iterations"] == 2
        assert len(item["trace"]) == 2
        assert item["session_id"] == "test_session"
