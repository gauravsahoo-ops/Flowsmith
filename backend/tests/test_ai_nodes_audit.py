"""Audit test suite: AI Node, AI Agent Node, and RAG Pipeline.

14 targeted tests covering prompt/response, tool calling, multi-turn loops,
max-turn limits, credential validation, JSON format, agent final-answer
parsing, and RAG ingest+retrieve+synthesize — all with mocked LLM/embeddings.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import MemoryKVStore, NodeContext
from app.nodes.ai import AINode, AIParams
from app.nodes.ai_agent import AIAgentNode, AgentParams
from app.nodes.rag_pipeline import RAGPipelineNode, RAGParams


# ── Helpers ─────────────────────────────────────────────────────────

LLM_CRED = {"api_key": "test-key", "model": "gpt-4", "base_url": "https://api.openai.com/v1"}


def _make_ctx(
    credentials: dict[str, Any] | None = None,
    http_client: AsyncMock | None = None,
) -> NodeContext:
    return NodeContext(
        execution_id="test_exec",
        workflow_id="test_wf",
        node_id="test_node",
        logger=logging.getLogger("test_ai"),
        http_client=http_client or AsyncMock(),
        storage=MemoryKVStore(),
        emit_event=lambda *a, **k: None,
        credentials=credentials or {},
        user_id=1,
    )


def _make_llm_post_return(message: dict[str, Any]) -> MagicMock:
    """Build a mock httpx.Response for chat_completion's client.post()."""
    body = {"choices": [{"message": message}], "model": "gpt-4"}
    resp = MagicMock()
    resp.status_code = 200
    resp.text = json.dumps(body)
    resp.json.return_value = body
    return resp


def _llm_msg(content: str | None = None, tool_calls: list | None = None) -> dict:
    """Build the assistant message dict for LLM responses."""
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return message


def _tool_call_msg(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _setup_mock_http_client(responses):
    """Create a mock httpx.AsyncClient class that returns the given responses.

    Used with @patch('app.ai.client.httpx.AsyncClient') for nodes that
    don't pass http_client to chat_completion (Agent, RAG).
    """
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.post = AsyncMock(side_effect=responses if isinstance(responses, list) else [responses])
    mock_instance.aclose = AsyncMock()
    mock_cls.return_value = mock_instance
    return mock_cls


# ══════════════════════════════════════════════════════════════════════
#  AI NODE TESTS
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ai_simple_prompt():
    """1. Simple prompt -> mock LLM returns response -> verify output."""
    http = AsyncMock()
    http.post = AsyncMock(return_value=_make_llm_post_return(
        _llm_msg("Hello from the model!")
    ))

    ctx = _make_ctx(credentials={"llm": LLM_CRED}, http_client=http)
    params = AIParams(prompt="Say hello")
    node = AINode()
    result = await node.run(ctx, params, [])

    assert result.output_items[0]["response"] == "Hello from the model!"
    assert result.output_items[0]["turns"] == 1
    assert result.output_items[0]["tool_calls"] == []


@pytest.mark.asyncio
async def test_ai_tool_calling():
    """2. Tool calling -> mock LLM returns tool_call -> tool is executed -> final response."""
    http = AsyncMock()

    tool_resp = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_1", "current_time", {})],
    ))
    final_resp = _make_llm_post_return(_llm_msg("The current time is 2024-01-01T00:00:00Z"))
    http.post = AsyncMock(side_effect=[tool_resp, final_resp])

    ctx = _make_ctx(credentials={"llm": LLM_CRED}, http_client=http)
    params = AIParams(prompt="What time is it?", tools=["current_time"])
    node = AINode()
    result = await node.run(ctx, params, [])

    assert result.output_items[0]["response"] == "The current time is 2024-01-01T00:00:00Z"
    assert result.output_items[0]["turns"] == 2
    assert len(result.output_items[0]["tool_calls"]) == 1
    assert result.output_items[0]["tool_calls"][0]["tool"] == "current_time"


@pytest.mark.asyncio
async def test_ai_multi_turn_tool_calling():
    """3. Multi-turn: LLM calls tool, gets result, calls another tool, returns final answer."""
    http = AsyncMock()

    call1 = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_1", "current_time", {})],
    ))
    call2 = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_2", "current_time", {})],
    ))
    final = _make_llm_post_return(_llm_msg("Done with two tool calls"))
    http.post = AsyncMock(side_effect=[call1, call2, final])

    ctx = _make_ctx(credentials={"llm": LLM_CRED}, http_client=http)
    params = AIParams(prompt="Check time twice", tools=["current_time"], max_turns=5)
    node = AINode()
    result = await node.run(ctx, params, [])

    assert result.output_items[0]["response"] == "Done with two tool calls"
    assert result.output_items[0]["turns"] == 3
    assert len(result.output_items[0]["tool_calls"]) == 2


@pytest.mark.asyncio
async def test_ai_max_turns_exceeded():
    """4. Max turns exceeded -> error raised."""
    http = AsyncMock()

    tool_resp = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_1", "current_time", {})],
    ))
    http.post = AsyncMock(return_value=tool_resp)

    ctx = _make_ctx(credentials={"llm": LLM_CRED}, http_client=http)
    params = AIParams(prompt="Loop forever", tools=["current_time"], max_turns=2)
    node = AINode()
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [])
    assert exc_info.value.code == "AI_MAX_TURNS"
    assert "2-turn limit" in exc_info.value.message


@pytest.mark.asyncio
async def test_ai_missing_credential():
    """5. Missing LLM credential -> error raised."""
    ctx = _make_ctx(credentials={})
    params = AIParams(prompt="Hello")
    node = AINode()
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [])
    assert exc_info.value.code == "CREDENTIALS_REQUIRED"


@pytest.mark.asyncio
async def test_ai_json_response_format():
    """6. JSON response format -> response is parsed as JSON."""
    http = AsyncMock()
    json_content = json.dumps({"key": "value", "number": 42})
    http.post = AsyncMock(return_value=_make_llm_post_return(_llm_msg(content=json_content)))

    ctx = _make_ctx(credentials={"llm": LLM_CRED}, http_client=http)
    params = AIParams(prompt="Return JSON", response_format="json")
    node = AINode()
    result = await node.run(ctx, params, [])

    response = result.output_items[0]["response"]
    assert isinstance(response, dict)
    assert response["key"] == "value"
    assert response["number"] == 42


# ══════════════════════════════════════════════════════════════════════
#  AI AGENT NODE TESTS
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
async def test_agent_simple_question(mock_client_cls):
    """7. Simple question -> mock LLM returns final answer -> verify output."""
    mock_instance = MagicMock()
    mock_instance.post = AsyncMock(return_value=_make_llm_post_return(_llm_msg(content="The answer is 42")))
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = AgentParams(instructions="Answer questions.", input="What is the meaning of life?")
    node = AIAgentNode()
    result = await node.run(ctx, params, [])

    assert result.output_items[0]["result"] == "The answer is 42"


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
async def test_agent_with_tool_use(mock_client_cls):
    """8. Agent with tool use -> LLM calls tool -> gets result -> returns final answer."""
    mock_instance = MagicMock()
    tool_resp = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_1", "current_time", {})],
    ))
    final_resp = _make_llm_post_return(_llm_msg(
        content='{"action": "final", "answer": "Current time retrieved."}'
    ))
    mock_instance.post = AsyncMock(side_effect=[tool_resp, final_resp])
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = AgentParams(instructions="Use tools to answer.", input="What time is it?")
    node = AIAgentNode()
    result = await node.run(ctx, params, [])

    assert result.output_items[0]["result"] == "Current time retrieved."
    assert mock_instance.post.call_count == 2


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
async def test_agent_max_iterations_exceeded(mock_client_cls):
    """9. Max iterations exceeded -> error raised."""
    mock_instance = MagicMock()
    tool_resp = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_1", "current_time", {})],
    ))
    mock_instance.post = AsyncMock(return_value=tool_resp)
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = AgentParams(
        instructions="Keep calling tools.",
        input="Do something",
        max_iterations=2,
    )
    node = AIAgentNode()
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [])
    assert exc_info.value.code == "AI_MAX_ITERATIONS"
    assert "max iterations" in exc_info.value.message.lower()


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
async def test_agent_final_answer_parsing(mock_client_cls):
    """10. Final answer parsing with {"action": "final", "answer": "..."} format."""
    mock_instance = MagicMock()
    tool_resp = _make_llm_post_return(_llm_msg(
        content=None,
        tool_calls=[_tool_call_msg("call_1", "current_time", {})],
    ))
    final_resp = _make_llm_post_return(_llm_msg(
        content='{"action": "final", "answer": "The time has been retrieved successfully."}'
    ))
    mock_instance.post = AsyncMock(side_effect=[tool_resp, final_resp])
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = AgentParams(
        instructions="Use tools, then return a final answer.",
        input="Get me the time",
    )
    node = AIAgentNode()
    result = await node.run(ctx, params, [])

    assert result.output_items[0]["result"] == "The time has been retrieved successfully."


@pytest.mark.asyncio
async def test_agent_missing_credential():
    """Bonus: Missing LLM credential -> error raised."""
    ctx = _make_ctx(credentials={})
    params = AgentParams(instructions="Do something", input="Hello")
    node = AIAgentNode()
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [])
    assert exc_info.value.code == "CREDENTIALS_REQUIRED"


# ══════════════════════════════════════════════════════════════════════
#  RAG PIPELINE TESTS
# ══════════════════════════════════════════════════════════════════════

def _mock_embedding_model():
    """Return a fake embedding model whose encode() returns deterministic vectors."""
    model = MagicMock()

    def fake_encode(texts):
        results = []
        for t in texts:
            h = hash(t) % 1000 / 1000.0
            results.append([h, h + 0.1, h + 0.2])
        return results

    model.encode = fake_encode
    return model


def _mock_vector_store():
    """Return a mock VectorStore with configurable query results."""
    store = MagicMock()
    store.ensure_collection.return_value = "mock_handle"

    store.query.return_value = [
        {
            "content": "Python is a programming language.",
            "metadata": {"chunk_index": 0, "source": "text", "document_id": "doc1"},
            "similarity": 0.92,
        },
        {
            "content": "Python was created by Guido van Rossum.",
            "metadata": {"chunk_index": 1, "source": "text", "document_id": "doc1"},
            "similarity": 0.85,
        },
    ]
    return store


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
@patch("app.nodes.rag_pipeline._get_embedding_model")
@patch("app.nodes.rag_pipeline.get_vector_store")
@patch("app.nodes.rag_pipeline._resolve_collection")
async def test_rag_ingest_text_source(mock_resolve, mock_get_store, mock_get_embed, mock_client_cls):
    """11. Ingest text source -> verify chunks are embedded and stored."""
    mock_instance = MagicMock()
    mock_instance.post = AsyncMock(return_value=_make_llm_post_return(
        _llm_msg("Based on the context, Python is a language.")
    ))
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    mock_get_embed.return_value = _mock_embedding_model()
    store = _mock_vector_store()
    mock_get_store.return_value = store
    mock_resolve.return_value = (store, "rag_default", None)

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = RAGParams(
        source_type="text",
        source="Python is a programming language. Python was created by Guido van Rossum.",
        collection_name="test_collection",
        query="What is Python?",
    )
    node = RAGPipelineNode()
    result = await node.run(ctx, params, [])

    store.add.assert_called_once()
    call_kwargs = store.add.call_args
    assert call_kwargs[1]["documents"]
    assert len(call_kwargs[1]["embeddings"]) > 0
    assert len(call_kwargs[1]["metadatas"]) > 0

    store.query.assert_called_once()
    mock_instance.post.assert_called_once()


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
@patch("app.nodes.rag_pipeline._get_embedding_model")
@patch("app.nodes.rag_pipeline.get_vector_store")
@patch("app.nodes.rag_pipeline._resolve_collection")
async def test_rag_query_without_source(mock_resolve, mock_get_store, mock_get_embed, mock_client_cls):
    """12. Query without source -> verify retrieval and synthesis."""
    mock_instance = MagicMock()
    mock_instance.post = AsyncMock(return_value=_make_llm_post_return(
        _llm_msg("Python is a programming language created by Guido.")
    ))
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    mock_get_embed.return_value = _mock_embedding_model()
    store = _mock_vector_store()
    mock_get_store.return_value = store
    mock_resolve.return_value = (store, "rag_default", None)

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = RAGParams(
        source_type="text",
        source="",
        collection_name="test_collection",
        query="What is Python?",
    )
    node = RAGPipelineNode()
    result = await node.run(ctx, params, [])

    store.add.assert_not_called()

    store.query.assert_called_once()
    mock_instance.post.assert_called_once()

    output = result.output_items[0]
    assert "answer" in output
    assert output["chunks_used"] == 2
    assert len(output["citations"]) == 2


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
@patch("app.nodes.rag_pipeline._get_embedding_model")
@patch("app.nodes.rag_pipeline.get_vector_store")
@patch("app.nodes.rag_pipeline._resolve_collection")
async def test_rag_query_with_source(mock_resolve, mock_get_store, mock_get_embed, mock_client_cls):
    """13. Query with source -> verify ingest + query in one step."""
    mock_instance = MagicMock()
    mock_instance.post = AsyncMock(return_value=_make_llm_post_return(
        _llm_msg("The document discusses AI topics.")
    ))
    mock_instance.aclose = AsyncMock()
    mock_client_cls.return_value = mock_instance

    mock_get_embed.return_value = _mock_embedding_model()
    store = _mock_vector_store()
    mock_get_store.return_value = store
    mock_resolve.return_value = (store, "test_collection", None)

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = RAGParams(
        source_type="text",
        source="Artificial intelligence is transforming industries.",
        collection_name="test_collection",
        query="What is the document about?",
    )
    node = RAGPipelineNode()
    result = await node.run(ctx, params, [])

    store.add.assert_called_once()
    store.query.assert_called_once()
    mock_instance.post.assert_called_once()

    output = result.output_items[0]
    assert output["chunks_used"] == 2


@pytest.mark.asyncio
async def test_rag_missing_credential():
    """14. Missing LLM credential -> error raised."""
    ctx = _make_ctx(credentials={})
    params = RAGParams(query="What is Python?")
    node = RAGPipelineNode()
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [])
    assert exc_info.value.code == "CREDENTIALS_REQUIRED"


@pytest.mark.asyncio
@patch("app.ai.client.httpx.AsyncClient")
@patch("app.nodes.rag_pipeline._get_embedding_model")
@patch("app.nodes.rag_pipeline.get_vector_store")
@patch("app.nodes.rag_pipeline._resolve_collection")
async def test_rag_no_retrieved_chunks(mock_resolve, mock_get_store, mock_get_embed, mock_client_cls):
    """Bonus: No relevant chunks found -> verify graceful fallback."""
    mock_get_embed.return_value = _mock_embedding_model()
    store = MagicMock()
    store.ensure_collection.return_value = "mock_handle"
    store.query.return_value = []
    mock_get_store.return_value = store
    mock_resolve.return_value = (store, "test_collection", None)

    ctx = _make_ctx(credentials={"llm": LLM_CRED})
    params = RAGParams(
        source_type="text",
        source="",
        collection_name="test_collection",
        query="Something unrelated",
    )
    node = RAGPipelineNode()
    result = await node.run(ctx, params, [])

    output = result.output_items[0]
    assert output["answer"] == "No relevant context found."
    assert output["chunks_used"] == 0
    # LLM should NOT be called when no context found
    mock_client_cls.return_value.post.assert_not_called()
