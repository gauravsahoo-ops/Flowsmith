"""Tri-Tier Memory Architecture for Flowsmith AI Agents.

Provides:
1. WorkingMemory: Fast sliding window of recent message turns.
2. SummaryBufferMemory: LLM-powered compression of older turns when token budgets are reached.
3. EpisodicVectorMemory: Long-term persistent semantic memory powered by PostgreSQL + pgvector.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import datetime
import logging
import re
from typing import Any

logger = logging.getLogger("ai.memory")


@dataclass
class MemoryMessage:
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


class WorkingMemory:
    """Sliding window of the most recent message turns."""

    def __init__(self, max_entries: int = 30) -> None:
        self.max_entries = max_entries
        self.messages: list[MemoryMessage] = []

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        self.messages.append(MemoryMessage(role=role, content=content, **kwargs))
        if len(self.messages) > self.max_entries:
            self.messages = self.messages[-self.max_entries:]

    def get_messages(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.messages]

    def clear(self) -> None:
        self.messages.clear()


class SummaryBufferMemory:
    """Maintains a running summary of older context plus recent turns."""

    def __init__(self, max_recent_entries: int = 10) -> None:
        self.max_recent_entries = max_recent_entries
        self.summary: str = ""
        self.recent_messages: list[MemoryMessage] = []

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        self.recent_messages.append(MemoryMessage(role=role, content=content, **kwargs))

    async def compress_if_needed(self, llm_client_fn: Any, credential: dict[str, Any]) -> None:
        """If messages exceed window, compress older ones into running summary."""
        if len(self.recent_messages) <= self.max_recent_entries:
            return

        split_idx = len(self.recent_messages) - self.max_recent_entries
        to_summarize = self.recent_messages[:split_idx]
        self.recent_messages = self.recent_messages[split_idx:]

        transcript = "\n".join(f"{m.role}: {m.content}" for m in to_summarize)
        prompt = (
            f"Update the existing conversation summary with the following older dialogue turns.\n"
            f"Existing Summary: {self.summary or 'None'}\n\n"
            f"New Dialogue:\n{transcript}\n\n"
            f"Provide a concise, factual updated summary capturing key user goals, decisions, and data."
        )

        try:
            res = await llm_client_fn(
                credential=credential,
                messages=[
                    {"role": "system", "content": "You are a concise conversation summarizer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            self.summary = res.get("content") or self.summary
        except Exception as exc:
            logger.warning("Failed to summarize older memory buffer: %s", exc)

    def get_messages(self) -> list[dict[str, Any]]:
        result = []
        if self.summary:
            result.append({
                "role": "system",
                "content": f"[Previous Conversation Summary]: {self.summary}",
            })
        result.extend([m.to_dict() for m in self.recent_messages])
        return result


class EpisodicVectorMemory:
    """Semantic episodic memory stored in PostgreSQL + pgvector or local store.

    Recalls relevant past user facts, preferences, and dialogue items based on
    semantic similarity to the current turn's query.
    """

    def __init__(self, session_id: str, collection_name: str = "agent_memories") -> None:
        self.session_id = session_id
        self.collection_name = collection_name
        self._in_memory_records: list[dict[str, Any]] = []

    async def store_memory(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> None:
        """Store an episodic memory entry."""
        entry = {
            "session_id": self.session_id,
            "text": text,
            "metadata": metadata or {},
            "embedding": embedding,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self._in_memory_records.append(entry)

        # Attempt to persist to pgvector if vector store is initialized
        try:
            from app.vectorstores import get_vector_store
            store = get_vector_store()
            if store and embedding:
                handle = store.ensure_collection(self.collection_name, len(embedding))
                store.add(
                    handle,
                    documents=[text],
                    embeddings=[embedding],
                    metadatas=[{"session_id": self.session_id, **(metadata or {})}],
                    ids=[f"{self.session_id}_{len(self._in_memory_records)}"],
                )
        except Exception:
            # Fallback to local in-memory store if DB is offline or in mock test
            pass

    async def recall_relevant_memories(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 3,
    ) -> list[str]:
        """Retrieve the top-k most semantically relevant memories."""
        if not self._in_memory_records:
            return []

        # Try pgvector query first
        if query_embedding:
            try:
                from app.vectorstores import get_vector_store
                store = get_vector_store()
                if store:
                    handle = store.ensure_collection(self.collection_name, len(query_embedding))
                    results = store.query(handle, query_embedding, top_k)
                    if results:
                        return [r.get("content", "") for r in results if r.get("content")]
            except Exception:
                pass

        # Smart lexical fallback if embeddings not ready or running in-memory
        clean_q = re.sub(r"[^\w\s]", " ", query.lower()).split()
        stopwords = {
            "where", "does", "the", "a", "an", "in", "on", "at", "to", "for",
            "of", "is", "are", "was", "were", "what", "how", "when", "who", "which"
        }
        q_tokens = [w for w in clean_q if w not in stopwords] or clean_q

        scored: list[tuple[float, str]] = []
        for r in self._in_memory_records:
            clean_t = re.sub(r"[^\w\s]", " ", r["text"].lower()).split()
            t_tokens = set(clean_t)
            score = 0.0
            for q_tok in q_tokens:
                if q_tok in t_tokens:
                    score += 1.0
                elif any(t.startswith(q_tok) or q_tok.startswith(t) for t in t_tokens if len(t) >= 3 and len(q_tok) >= 3):
                    score += 0.8
            scored.append((score, r["text"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [text for score, text in scored[:top_k] if score > 0]


class SessionMemoryManager:
    """Manages active memories across user sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, WorkingMemory | SummaryBufferMemory] = {}
        self._vector_memories: dict[str, EpisodicVectorMemory] = {}
        self._lock = asyncio.Lock()

    async def get_working_memory(self, session_id: str, max_entries: int = 30) -> WorkingMemory:
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = WorkingMemory(max_entries=max_entries)
            return self._sessions[session_id]  # type: ignore

    async def get_summary_memory(self, session_id: str, max_recent: int = 10) -> SummaryBufferMemory:
        async with self._lock:
            if session_id not in self._sessions or not isinstance(self._sessions[session_id], SummaryBufferMemory):
                self._sessions[session_id] = SummaryBufferMemory(max_recent_entries=max_recent)
            return self._sessions[session_id]  # type: ignore

    async def get_episodic_memory(self, session_id: str) -> EpisodicVectorMemory:
        async with self._lock:
            if session_id not in self._vector_memories:
                self._vector_memories[session_id] = EpisodicVectorMemory(session_id=session_id)
            return self._vector_memories[session_id]

    async def clear_session(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
            self._vector_memories.pop(session_id, None)


# Global singleton manager
_global_memory_manager = SessionMemoryManager()


def get_memory_manager() -> SessionMemoryManager:
    return _global_memory_manager
