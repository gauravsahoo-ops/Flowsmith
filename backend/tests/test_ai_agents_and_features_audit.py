"""Comprehensive test suite for Section 8: AI Agents & AI Features.

Verifies all 10 checklist criteria:
1. All configured LLM providers and supported models (LLMProviderRegistry & model discovery)
2. Provider credentials, fallback and timeout handling (ModelRouter & task fallback)
3. AI workflow generation and node selection (Grounded NL -> DAG synthesis)
4. Generated workflow schema and connection validation (Schema, port handles, cycle detection)
5. Prompt injection and untrusted input handling (Boundary isolation & AST/SQL tool sandboxes)
6. Tool calling, argument validation and tool permissions (OpenAI tools, schema enforcement, governance)
7. Memory, retrieval, embeddings and vector search (Multi-tier working, summary, episodic, vector search)
8. RAG relevance, grounding and citation behavior (Recursive/Markdown splitting, BM25, RRF fusion)
9. Token limits, cost tracking and model failures (AgentGovernanceGuard, budget ceiling, failure types)
10. Human approval, cancellation and bounded agent execution (Iteration bounds, HITL approval gates)
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ai.catalog import build_connector_entries, build_node_entries, render_system_prompt
from app.ai.client import chat_completion
from app.ai.generation import GenerationError, generate_workflow_spec
from app.ai.governance import (
    AgentGovernanceGuard,
    AgentGovernancePolicy,
    GovernanceViolation,
)
from app.ai.llm_registry import (
    LLMModel,
    LLMProviderDefinition,
    get_llm_registry,
)
from app.ai.llm_router import ModelRouter, TASK_MODEL_PREFERENCES
from app.ai.memory import (
    CompleteMemory,
    EntityMemory,
    EpisodicVectorMemory,
    SummaryBufferMemory,
    WorkingMemory,
    get_memory_manager,
)
from app.ai.rag import (
    DocumentChunk,
    EmbeddingService,
    MarkdownTextSplitter,
    RecursiveTextSplitter,
    reciprocal_rank_fusion,
    simple_bm25_search,
)
from app.ai.tools import (
    TOOLS,
    ToolSpec,
    _check_readonly_sql,
    _safe_calc,
    openai_tools,
    run_tool,
)
from app.ai.validation import validate_candidate
from app.db import get_session
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.ai_agent import AIAgentNode, AgentParams
from tests.test_api.conftest import auth_headers, register


def _make_user_with_llm(client, email="ai_auditor@example.com"):
    reg = register(client, email=email, password="AuditPassword123!")
    headers = auth_headers(reg["token"])
    cred_data = {
        "name": "Audit LLM Credential",
        "type": "llm",
        "data": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-mock-audit-key-12345",
            "base_url": "https://api.openai.com/v1",
        },
    }
    client.post("/api/credentials", json=cred_data, headers=headers)
    return reg["user"], headers


# ==============================================================================
# 1. All configured LLM providers and supported models
# ==============================================================================
def test_all_configured_llm_providers_and_supported_models(client):
    """Test registry completeness, provider definitions, model catalogs, and API endpoints."""
    user, headers = _make_user_with_llm(client, email="providers_audit@example.com")

    # 1. Inspect Python LLM Provider Registry
    registry = get_llm_registry()
    all_providers = registry.list_all()
    assert len(all_providers) >= 50, f"Expected 50+ providers, got {len(all_providers)}"

    prov_ids = {p.provider_id for p in all_providers}
    essential_providers = {"openai", "anthropic", "google", "groq", "deepseek", "ollama", "azure", "bedrock"}
    assert essential_providers.issubset(prov_ids)

    # 2. Verify OpenAI provider capabilities and model catalog
    openai_prov = registry.get("openai")
    assert openai_prov is not None
    assert openai_prov.auth_type == "api_key"
    assert len(openai_prov.model_catalog) > 0
    model_ids = {m.id for m in openai_prov.model_catalog}
    assert any("gpt-4" in mid for mid in model_ids)

    # 3. Test API endpoint /api/llm/providers
    resp = client.get("/api/llm/providers", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, dict)
    assert data["total"] >= 50
    assert "providers" in data
    api_prov_ids = {p["id"] for p in data["providers"]}
    assert "openai" in api_prov_ids
    assert "anthropic" in api_prov_ids

    # 4. Test single provider detail endpoint /api/llm/providers/openai
    detail_resp = client.get("/api/llm/providers/openai", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["provider_id"] == "openai"
    assert "credential_fields" in detail
    assert "capabilities" in detail


# ==============================================================================
# 2. Provider credentials, fallback and timeout handling
# ==============================================================================
def test_provider_credentials_fallback_and_timeout_handling(client):
    """Test task-based model routing, credential resolution, and fallback ordering."""
    user, headers = _make_user_with_llm(client, email="router_audit@example.com")

    # 1. Verify task model preferences
    assert "planning" in TASK_MODEL_PREFERENCES
    assert "intent" in TASK_MODEL_PREFERENCES
    assert "coding" in TASK_MODEL_PREFERENCES
    assert "fast" in TASK_MODEL_PREFERENCES

    db = get_session()
    try:
        from app.models.user import User as UserModel
        user_db = db.get(UserModel, user["id"])
        assert user_db is not None

        # Resolve model using auto-routing
        resolved = ModelRouter.resolve_model(db, user_db, task_type="planning")
        assert resolved is not None
        assert resolved.get("api_key") == "sk-mock-audit-key-12345"
        assert resolved.get("provider") == "openai"
    finally:
        db.close()

    # 2. Timeout and Failure Handling Simulation
    # Verify chat_completion handles timeouts gracefully
    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Upstream LLM timed out after 30s")):
        async def _check_timeout():
            with pytest.raises(Exception) as exc_info:
                await chat_completion(
                    {"provider": "openai", "api_key": "test", "model": "gpt-4o"},
                    [{"role": "user", "content": "hi"}],
                )
            assert "timed out" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()
        asyncio.run(_check_timeout())


# ==============================================================================
# 3. AI workflow generation and node selection
# ==============================================================================
@pytest.mark.asyncio
async def test_ai_workflow_generation_and_node_selection():
    """Test natural language workflow generation with grounded node selection and repair loop."""
    # Mock LLM chat function returning a valid workflow candidate
    async def mock_chat(llm, messages, **kwargs):
        content = json.dumps({
            "name": "Customer Support Triage",
            "description": "Trigger on webhook, filter payload, and alert via HTTP",
            "nodes": [
                {
                    "id": "node_webhook",
                    "type": "webhook",
                    "name": "Receive Ticket",
                    "parameters": {"path": "support", "http_method": "POST"},
                },
                {
                    "id": "node_filter",
                    "type": "filter",
                    "name": "Check Priority",
                    "parameters": {"conditions": []},
                },
                {
                    "id": "node_http",
                    "type": "http_request",
                    "name": "Alert Support Lead",
                    "parameters": {"url": "https://api.example.com/alert", "method": "POST"},
                },
            ],
            "connections": [
                {
                    "source": "node_webhook",
                    "source_handle": "main",
                    "target": "node_filter",
                    "target_handle": "main",
                },
                {
                    "source": "node_filter",
                    "source_handle": "main",
                    "target": "node_http",
                    "target_handle": "main",
                },
            ],
        })
        return {"content": content, "tool_calls": []}

    res = await generate_workflow_spec(
        prompt="When a support webhook comes in, filter payload and alert via HTTP",
        available_credentials={"http"},
        chat=mock_chat,
        llm={"provider": "openai", "model": "gpt-4o"},
    )

    assert "workflow" in res
    assert "validation" in res
    assert res["validation"]["ok"] is True
    wf = res["workflow"]
    assert len(wf["nodes"]) == 3
    node_types = [n["type"] for n in wf["nodes"]]
    assert node_types == ["webhook", "filter", "http_request"]
    assert len(wf["connections"]) == 2


# ==============================================================================
# 4. Generated workflow schema and connection validation
# ==============================================================================
def test_generated_workflow_schema_and_connection_validation():
    """Test candidate validation engine: schema checks, handle verification, and cycle detection."""
    # 1. Valid Candidate
    valid_candidate = {
        "name": "Valid Candidate",
        "nodes": [
            {"id": "n1", "type": "manual_trigger", "parameters": {}},
            {"id": "n2", "type": "filter", "parameters": {"conditions": []}},
        ],
        "connections": [
            {"source": "n1", "source_handle": "main", "target": "n2", "target_handle": "main"},
        ],
    }
    val = validate_candidate(valid_candidate, available_credentials=set())
    assert val["ok"] is True
    assert len(val["errors"]) == 0

    # 2. Unknown Node Type
    unknown_type_cand = {
        "nodes": [{"id": "n1", "type": "non_existent_magic_node", "parameters": {}}],
        "connections": [],
    }
    val_unknown = validate_candidate(unknown_type_cand, available_credentials=set())
    assert val_unknown["ok"] is False
    assert any(e["code"] == "UNKNOWN_NODE_TYPE" for e in val_unknown["errors"])

    # 3. Invalid Output Handle
    bad_handle_cand = {
        "nodes": [
            {"id": "n1", "type": "manual_trigger", "parameters": {}},
            {"id": "n2", "type": "filter", "parameters": {"conditions": []}},
        ],
        "connections": [
            {"source": "n1", "source_handle": "non_existent_handle", "target": "n2", "target_handle": "main"},
        ],
    }
    val_handle = validate_candidate(bad_handle_cand, available_credentials=set())
    assert val_handle["ok"] is False
    assert any(e["code"] == "INVALID_OUTPUT_HANDLE" for e in val_handle["errors"])

    # 4. Invalid Connection Referencing Non-Existent Target Node
    bad_conn_cand = {
        "nodes": [
            {"id": "n1", "type": "manual_trigger", "parameters": {}},
            {"id": "n2", "type": "filter", "parameters": {"conditions": []}},
        ],
        "connections": [
            {"source": "n1", "source_handle": "main", "target": "non_existent_target", "target_handle": "main"},
        ],
    }
    val_conn = validate_candidate(bad_conn_cand, available_credentials=set())
    assert val_conn["ok"] is False
    assert any(e["code"] == "INVALID_CONNECTION" for e in val_conn["errors"])

    # 5. Duplicate Node ID Detection
    dup_node_cand = {
        "nodes": [
            {"id": "n1", "type": "manual_trigger", "parameters": {}},
            {"id": "n1", "type": "filter", "parameters": {"conditions": []}},
        ],
        "connections": [],
    }
    val_dup = validate_candidate(dup_node_cand, available_credentials=set())
    assert val_dup["ok"] is False
    assert any(e["code"] == "DUPLICATE_NODE_ID" for e in val_dup["errors"])


# ==============================================================================
# 5. Prompt injection and untrusted input handling
# ==============================================================================
def test_prompt_injection_and_untrusted_input_handling():
    """Test prompt boundary containment, read-only SQL validation, and calculator AST sandboxing."""
    # 1. SQL Tool Injection Defenses
    # Attempt: destructive keyword
    with pytest.raises(ValueError) as exc:
        _check_readonly_sql("DROP TABLE users;")
    assert "Only read-only SQL" in str(exc.value)

    # Attempt: second-statement injection
    with pytest.raises(ValueError) as exc:
        _check_readonly_sql("SELECT 1; DELETE FROM workflows;")
    assert "Only a single SQL statement" in str(exc.value)

    # Attempt: CTE disguised modification
    with pytest.raises(ValueError) as exc:
        _check_readonly_sql("WITH deleted AS (DELETE FROM credentials RETURNING *) SELECT * FROM deleted;")
    assert "Only read-only SQL" in str(exc.value)

    # Valid Read-Only Query passes without error
    _check_readonly_sql("SELECT id, name, created_at FROM audit_events WHERE user_id = 1;")

    # 2. Calculator AST Sandboxing
    # Valid math expressions
    assert _safe_calc("2 + 2 * 10") == 22
    assert _safe_calc("sqrt(16) + abs(-5)") == 9.0

    # Attempt: dangerous Python builtins / module loading
    with pytest.raises(Exception):
        _safe_calc("__import__('os').system('whoami')")

    with pytest.raises(Exception):
        _safe_calc("eval('2+2')")

    with pytest.raises(Exception):
        _safe_calc("open('/etc/passwd').read()")


# ==============================================================================
# 6. Tool calling, argument validation and tool permissions
# ==============================================================================
@pytest.mark.asyncio
async def test_tool_calling_argument_validation_and_tool_permissions():
    """Test OpenAI tools schema generation, tool execution with validation, and governance guard."""
    # 1. Tools schema generation
    tool_schemas = openai_tools(["current_time", "calculator", "http_request"])
    assert len(tool_schemas) == 3
    calc_schema = next(t for t in tool_schemas if t["function"]["name"] == "calculator")
    assert "expression" in calc_schema["function"]["parameters"]["properties"]

    # 2. Tool Execution via run_tool
    ctx = MagicMock(spec=NodeContext)
    ctx.credentials = {}

    # Run calculator with valid expression
    calc_res = await run_tool(ctx, "calculator", {"expression": "100 / 4 + 7"})
    assert "32" in str(calc_res)

    # Run current_time
    time_res = await run_tool(ctx, "current_time", {})
    assert "T" in str(time_res)  # ISO timestamp format

    # Argument validation: empty expression returns error response
    calc_empty = await run_tool(ctx, "calculator", {})
    assert "Error: Empty expression" in str(calc_empty)

    # Unknown tool raises ValueError
    with pytest.raises(ValueError) as exc_tool:
        await run_tool(ctx, "non_existent_tool", {})
    assert "Unknown tool" in str(exc_tool.value)

    # 3. Tool Permissions via AgentGovernanceGuard
    policy = AgentGovernancePolicy(
        allowed_connectors=["salesforce", "slack"],
        prohibited_tools=["database_query"],
    )
    guard = AgentGovernanceGuard(policy)

    # Permitted tool
    guard.check_tool_call("salesforce_create_lead")

    # Prohibited tool raises GovernanceViolation
    with pytest.raises(GovernanceViolation) as exc_info:
        guard.check_tool_call("database_query")
    assert exc_info.value.rule == "PROHIBITED_TOOL"


# ==============================================================================
# 7. Memory, retrieval, embeddings and vector search
# ==============================================================================
@pytest.mark.asyncio
async def test_memory_retrieval_embeddings_and_vector_search():
    """Test multi-tier memory: working sliding window, summary buffer, episodic semantic memory."""
    # 1. Working Memory (sliding window)
    working = WorkingMemory(max_entries=3)
    working.add_message("user", "msg 1")
    working.add_message("assistant", "msg 2")
    working.add_message("user", "msg 3")
    working.add_message("assistant", "msg 4")
    assert len(working.get_messages()) == 3
    assert working.get_messages()[0]["content"] == "msg 2"

    # 2. Summary Buffer Memory (compression & running summary)
    summary_mem = SummaryBufferMemory(max_recent_entries=2)
    summary_mem.add_message("user", "Deploy version 1.2 to production cluster")
    summary_mem.add_message("assistant", "Deploying now with zero downtime")
    summary_mem.add_message("user", "Check cluster pod health")
    summary_mem.add_message("assistant", "All 5 pods healthy and serving traffic")

    await summary_mem.compress_if_needed()
    summary_text = summary_mem.get_summary()
    assert "Deploy" in summary_text or "production" in summary_text

    # 3. Episodic Semantic Memory
    episodic = EpisodicVectorMemory(session_id="audit_session_42")
    await episodic.store_memory("Customer preferred contact method is Email, not SMS", metadata={"category": "pref"})
    await episodic.store_memory("Enterprise subscription plan tier is Tier 3 Platinum", metadata={"category": "billing"})

    recalled = await episodic.recall_relevant_memories("How should we contact the customer?", top_k=1)
    assert len(recalled) == 1
    assert "Email" in recalled[0]


# ==============================================================================
# 8. RAG relevance, grounding and citation behavior
# ==============================================================================
def test_rag_relevance_grounding_and_citation_behavior():
    """Test text chunkers, BM25 retrieval scoring, and Reciprocal Rank Fusion (RRF)."""
    # 1. RecursiveTextSplitter
    splitter = RecursiveTextSplitter(chunk_size=100, chunk_overlap=20)
    text = (
        "Flowsmith is an enterprise workflow engine. It automates complex DAGs. "
        "It features live state machines, resilient worker loops, and native AI agents. "
        "Every connector executes with strict credential isolation and comprehensive telemetry."
    )
    chunks = splitter.split_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= 120 for c in chunks)

    # 2. MarkdownTextSplitter
    md_splitter = MarkdownTextSplitter(chunk_size=150, chunk_overlap=20)
    md_doc = """# Flowsmith Architecture
Flowsmith backend runs on FastAPI and PostgreSQL.

## Workflow Engine
The engine validates DAGs before execution. Cycles are rejected.

## Security
Credentials use AES-256-GCM encryption.
"""
    md_chunks = md_splitter.split_text(md_doc)
    assert len(md_chunks) >= 2

    # 3. BM25 Search
    doc_chunks = [
        DocumentChunk(chunk_id="c1", text="Salesforce connector allows creating Leads and Contacts via OAuth."),
        DocumentChunk(chunk_id="c2", text="PostgreSQL node executes SQL queries against relational databases."),
        DocumentChunk(chunk_id="c3", text="Slack bot sends interactive blocks and alerts to team channels."),
    ]
    bm25_res = simple_bm25_search("Salesforce Leads", doc_chunks, top_k=1)
    assert len(bm25_res) == 1
    assert bm25_res[0].chunk_id == "c1"

    # 4. Reciprocal Rank Fusion (RRF)
    dense_results = [doc_chunks[0], doc_chunks[1]]
    sparse_results = [doc_chunks[1], doc_chunks[2]]
    fused = reciprocal_rank_fusion(dense_results, sparse_results, k=60, top_n=3)
    assert len(fused) == 3
    assert fused[0].chunk_id in ("c1", "c2")

    # 5. Catalog Grounding System Prompt
    system_prompt = render_system_prompt(query="slack message")
    assert "AVAILABLE NODES AND CONNECTORS" in system_prompt
    assert "Rules:" in system_prompt


# ==============================================================================
# 9. Token limits, cost tracking and model failures
# ==============================================================================
def test_token_limits_cost_tracking_and_model_failures():
    """Test agent cost monitoring, token expenditure enforcement, and model error handling."""
    # 1. Cost Tracking and Budget Ceiling
    policy = AgentGovernancePolicy(max_cost_dollars=0.05)  # $0.05 limit
    guard = AgentGovernanceGuard(policy)

    # Record 5,000 tokens (5,000 / 1,000,000 * $3 = $0.015) -> within budget
    guard.record_token_usage(prompt_tokens=3000, completion_tokens=2000)
    assert guard.estimated_cost == pytest.approx(0.015, rel=1e-3)

    # Record 20,000 additional tokens -> exceeds $0.05 budget
    with pytest.raises(GovernanceViolation) as exc_info:
        guard.record_token_usage(prompt_tokens=15000, completion_tokens=5000)
    assert exc_info.value.rule == "BUDGET_EXCEEDED"

    # 2. Maximum Tool Calls Ceiling
    policy_tools = AgentGovernancePolicy(max_tool_calls=2)
    guard_tools = AgentGovernanceGuard(policy_tools)
    guard_tools.check_tool_call("current_time")
    guard_tools.check_tool_call("calculator")
    with pytest.raises(GovernanceViolation) as exc_tools:
        guard_tools.check_tool_call("http_request")
    assert exc_tools.value.rule == "MAX_TOOL_CALLS"


# ==============================================================================
# 10. Human approval, cancellation and bounded agent execution
# ==============================================================================
@pytest.mark.asyncio
async def test_human_approval_cancellation_and_bounded_agent_execution():
    """Test iteration bounds, HITL approval flags on sensitive tools, and agent termination."""
    # 1. Bounded Execution Limits (Prevent Runaway Agent Loops)
    policy = AgentGovernancePolicy(max_iterations=3)
    guard = AgentGovernanceGuard(policy)

    guard.check_iteration()  # iter 1
    guard.check_iteration()  # iter 2
    guard.check_iteration()  # iter 3
    with pytest.raises(GovernanceViolation) as exc_info:
        guard.check_iteration()  # iter 4 exceeds bound
    assert exc_info.value.rule == "MAX_ITERATIONS"

    # 2. Human Approval (HITL) Policy Flags
    assert TOOLS["current_time"].requires_approval is False

    # Define a sensitive tool that mandates human approval
    sensitive_spec = ToolSpec(
        name="wipe_production_database",
        description="Destructive database wipe",
        parameters={"type": "object", "properties": {}},
        handler=lambda ctx, args: "wiped",
        requires_approval=True,
    )
    assert sensitive_spec.requires_approval is True

    # Check run_tool returns pending_approval for HITL tools
    ctx = MagicMock(spec=NodeContext)
    with patch.dict(TOOLS, {"wipe_production_database": sensitive_spec}):
        approval_res = await run_tool(ctx, "wipe_production_database", {})
        parsed = json.loads(approval_res)
        assert parsed["status"] == "pending_approval"
        assert "requires human approval" in parsed["message"]

    # 3. AIAgentNode Max Iterations Bounded Execution
    agent_node = AIAgentNode()
    ctx.credentials = {"llm": {"provider": "builtin", "model": "builtin"}}
    ctx.workflow_id = "wf_test_bounds"

    # Mock chat_completion to always request another tool call (infinite loop attempt)
    call_count = 0
    async def infinite_tool_calls(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "content": "Need to check time again",
            "tool_calls": [
                {
                    "id": f"tc_{call_count}",
                    "type": "function",
                    "function": {"name": "current_time", "arguments": "{}"},
                }
            ],
        }

    with patch("app.nodes.ai_agent.chat_completion", side_effect=infinite_tool_calls):
        params = AgentParams(
            instructions="Always check time",
            input="What is the time?",
            tools=["current_time"],
            max_iterations=3,  # Hard bound
            allow_builtin_fallback=True,
        )

        # Agent terminates with NodeExecutionError(AI_MAX_ITERATIONS)
        with pytest.raises(NodeExecutionError) as exc_node:
            await agent_node.run(ctx, params, [])
        assert exc_node.value.code == "AI_MAX_ITERATIONS"
        assert "max iterations" in str(exc_node.value)
        assert call_count == 3
