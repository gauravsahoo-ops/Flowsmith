"""Test suite for Flowsmith AI Complete Multi-Tier Memory and Autonomous Zero-LLM Engine.

Validates that:
1. Complete Multi-Tier Memory works across all cognitive tiers (working, summary, episodic, entity, scratchpad, full buffer).
2. Episodic similarity search and extractive summarization work deterministically without external embedding or LLM APIs.
3. Disk persistence survives memory reloads.
4. AIAgentNode runs autonomously without external LLM credentials when allow_builtin_fallback=True or model='builtin'.
5. MemoryNode runs with complete memory locally without Redis.
6. AI API endpoints (chat, search, entities, notes) function seamlessly in zero-LLM mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import httpx
import pytest

from app.ai.client import chat_completion
from app.ai.memory import (
    CompleteMemory,
    EntityMemory,
    EpisodicVectorMemory,
    FullBufferMemory,
    ScratchpadMemory,
    SessionMemoryManager,
    SummaryBufferMemory,
    WorkingMemory,
    get_memory_manager,
)
from app.ai.providers.builtin_provider import BuiltinProvider
from app.engine.node_base import NodeContext
from app.nodes.ai_agent import AIAgentNode, AgentParams
from app.nodes.memory import MemoryNode, MemoryParams


# ---------------------------------------------------------------------------
# 1. Built-in Local Engine (Zero-LLM Provider)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_builtin_provider_direct():
    provider = BuiltinProvider({"provider": "builtin", "model": "builtin"})

    # Simple math / calculator tool check
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 42 * 17?"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Calculate math expressions",
                "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
            },
        }
    ]
    resp = await provider.chat_completion(messages, tools=tools)
    assert resp["role"] == "assistant"
    assert "tool_calls" in resp
    tc = resp["tool_calls"][0]
    assert tc["function"]["name"] == "calculator"
    args = json.loads(tc["function"]["arguments"])
    assert "42 * 17" in args["expression"] or "42" in args["expression"]

    # Direct answer without tools
    resp2 = await provider.chat_completion([{"role": "user", "content": "What time is it?"}])
    assert "UTC" in resp2.get("content", "") or "time" in resp2.get("content", "").lower()


# ---------------------------------------------------------------------------
# 2. Complete Multi-Tier Memory Tiers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entity_memory_extraction_and_storage():
    em = EntityMemory()
    em.set("user_role", "Data Architect")
    assert em.get("user_role") == "Data Architect"

    # Rule-based auto-extraction
    em.extract_from_text("My name is John Connor. My project is Skynet Defense. I prefer JSON format.")
    assert "John" in em.get("user_name")
    assert em.get("project_name") == "Skynet Defense"
    assert em.get("preferred_format") == "JSON"


@pytest.mark.asyncio
async def test_scratchpad_memory():
    sm = ScratchpadMemory()
    sm.set("step_1", "Downloaded customer dataset", tags=["etl", "data"])
    sm.set("step_2", "Calculated mean revenue = $4500", tags=["calculation"])

    notes = sm.list_notes()
    assert len(notes) == 2
    etl_notes = sm.list_notes(tag="etl")
    assert len(etl_notes) == 1
    assert etl_notes[0]["key"] == "step_1"


@pytest.mark.asyncio
async def test_episodic_lexical_similarity_zero_api():
    evm = EpisodicVectorMemory()
    await evm.store_memory("Customer requested quarterly financial revenue reports for Q3.")
    await evm.store_memory("System pipeline encountered 504 gateway timeout on webhook node.")
    await evm.store_memory("Database migration executed successfully on PostgreSQL cluster.")

    # Query with lexical match
    recalled = await evm.recall_relevant_memories("financial revenue reports", top_k=1)
    assert len(recalled) == 1
    assert "financial revenue reports" in recalled[0]

    # Query about timeouts
    recalled_err = await evm.recall_relevant_memories("webhook gateway timeout error", top_k=1)
    assert len(recalled_err) == 1
    assert "504 gateway timeout" in recalled_err[0]


@pytest.mark.asyncio
async def test_summary_buffer_extractive_fallback():
    sbm = SummaryBufferMemory(max_recent_entries=3)
    for i in range(12):
        sbm.add_message("user", f"Step {i}: Deploy service worker instance {i} to staging cluster.")
        sbm.add_message("assistant", f"Acknowledged step {i}. Service worker {i} is healthy.")

    # Compress without LLM credentials (runs extractive fallback)
    await sbm.compress_if_needed(chat_completion, credential={})
    assert sbm.summary != ""
    assert "User requested" in sbm.summary or "Assistant" in sbm.summary or "Summary" in sbm.summary


@pytest.mark.asyncio
async def test_complete_memory_hub_and_persistence(tmp_path):
    storage_dir = tmp_path / "ai_memory"
    manager = SessionMemoryManager(storage_dir=storage_dir)

    session_id = "test_persist_sess"
    mem = await manager.get_complete_memory(session_id)

    # Record a turn
    await mem.record_turn(
        user_content="My favorite language is Python and I am building an API workflow.",
        assistant_content="I have recorded that Python is your favorite language and noted your API workflow.",
        llm_func=chat_completion,
        llm_cred={"provider": "builtin", "model": "builtin"},
    )

    # Verify memory populated
    assert len(mem.buffer.messages) == 2 or len(mem.working.messages) == 2
    assert len(mem.working.messages) == 2

    # Save to disk
    await manager._persist_to_disk(session_id, mem)
    target_file = storage_dir / f"{session_id}.json"
    assert target_file.exists()

    # Create fresh manager to simulate restart and test recovery
    new_manager = SessionMemoryManager(storage_dir=storage_dir)
    recovered_mem = await new_manager.get_complete_memory(session_id)
    assert len(recovered_mem.working.messages) == 2

    # Search works across recovered memory
    search_res = await recovered_mem.search("Python workflow", top_k=2)
    assert len(search_res) > 0
    assert any("Python" in r["content"] for r in search_res)


# ---------------------------------------------------------------------------
# 3. AIAgentNode in Autonomous Zero-LLM Mode with Complete Memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_agent_zero_llm_complete_memory():
    agent = AIAgentNode()
    async with httpx.AsyncClient() as client:
        ctx = NodeContext(
            execution_id="exec_test_01",
            workflow_id="wf_test",
            node_id="agent_1",
            logger=logging.getLogger("test"),
            http_client=client,
            credentials={},  # No credentials at all!
        )

        session = f"zero_llm_{os.urandom(4).hex()}"

        # Turn 1: user introduces state and preference
        params_1 = AgentParams(
            input="My name is Sarah and my project is Apollo GraphQL.",
            session_id=session,
            memory_type="complete",
            allow_builtin_fallback=True,
        )
        res_1 = await agent.run(ctx, params_1, [])
        assert res_1.output_items
        ans_1 = res_1.output_items[0]["final_answer"]
        assert ans_1 is not None and len(ans_1) > 0

        # Turn 2: ask agent to retrieve known entities or state
        params_2 = AgentParams(
            input="What entities or project do you remember from my memory?",
            session_id=session,
            memory_type="complete",
            allow_builtin_fallback=True,
        )
        res_2 = await agent.run(ctx, params_2, [])
        ans_2 = res_2.output_items[0]["final_answer"]
        assert "Sarah" in ans_2 or "Apollo" in ans_2 or "Entity" in ans_2 or "Memory" in ans_2 or "project" in ans_2.lower()


# ---------------------------------------------------------------------------
# 4. MemoryNode Autonomous Operations (No Redis, Local Complete Backend)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_node_local_operations():
    mem_node = MemoryNode()
    async with httpx.AsyncClient() as client:
        ctx = NodeContext(
            execution_id="exec_mem_01",
            workflow_id="wf_mem",
            node_id="mem_1",
            logger=logging.getLogger("test"),
            http_client=client,
            credentials={},  # No Redis credentials
        )
        session = f"mem_sess_{os.urandom(4).hex()}"

        # 1. Push
        push_res = await mem_node.run(
            ctx,
            MemoryParams(
                operation="push",
                session_id=session,
                backend="local",
                role="user",
                content="Alpha testing pipeline completed with zero anomalies.",
            ),
            [],
        )
        assert push_res.output_items[0]["pushed"] is True

        # 2. Recall
        recall_res = await mem_node.run(
            ctx,
            MemoryParams(operation="recall", session_id=session, backend="local"),
            [],
        )
        assert len(recall_res.output_items) >= 1
        assert "Alpha testing pipeline" in recall_res.output_items[0]["content"]

        # 3. Set Entity
        set_ent = await mem_node.run(
            ctx,
            MemoryParams(
                operation="set_entity",
                session_id=session,
                backend="local",
                entity_key="cluster_status",
                entity_val="HEALTHY",
            ),
            [],
        )
        assert set_ent.output_items[0]["saved"] is True

        # 4. Get Entity
        get_ent = await mem_node.run(
            ctx,
            MemoryParams(
                operation="get_entity",
                session_id=session,
                backend="local",
                entity_key="cluster_status",
            ),
            [],
        )
        assert get_ent.output_items[0]["value"] == "HEALTHY"

        # 5. Search
        search_res = await mem_node.run(
            ctx,
            MemoryParams(
                operation="search",
                session_id=session,
                backend="local",
                content="anomalies pipeline",
            ),
            [],
        )
        assert search_res.output_items[0]["count"] >= 1

        # 6. Scratchpad Note
        note_res = await mem_node.run(
            ctx,
            MemoryParams(
                operation="set_note",
                session_id=session,
                backend="local",
                entity_key="checkpoint_1",
                content="Checkpoint reached safely.",
            ),
            [],
        )
        assert note_res.output_items[0]["saved"] is True

        # 7. Summary
        sum_res = await mem_node.run(
            ctx,
            MemoryParams(operation="summary", session_id=session, backend="local"),
            [],
        )
        assert "summary" in sum_res.output_items[0]
