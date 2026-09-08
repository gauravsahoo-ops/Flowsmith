# Phase 18 — Production RAG

> **Milestone:** RAG graduates from a node feature to a managed,
> tenant-safe knowledge-base service. Collections are registry objects
> with permission checks; ingestion is idempotent; documents can be
> deleted and re-indexed; retrieval returns scores, timings and
> citation-ready refs. **The existing sqlite_vec store is kept** (chroma
> still optional) — it was extended, not replaced.
> **Status:** done — 34 new backend tests (9 vectorstore hardening,
> 13 service/isolation, 5 full-stack API, 3 node + regressions),
> vitest 165 (+2), pyright 0 on touched modules, schema parity 25 tables.

## Pipeline (hardened)

```text
Document → Loader → Chunker → Embedding → Vector Store → Retrieval
        → [threshold funnel] → cited context [1][2]… → LLM → answer+citations
```

## What changed

| Area | Before | Now |
| --- | --- | --- |
| Tenant isolation | Any workflow could touch any collection by raw name | `rag_collections` registry; physical store names are opaque `rcstore_<rand>` keys; every op checks ownership/membership |
| Permissions | None | Workspace collections: members read, editors write; personal: owner-only; cross-tenant probes get **404** (existence never leaks) |
| Ingestion | Re-running duplicated chunks forever | Stable doc ids (explicit or content-hash) → upsert semantics |
| Re-index / delete | Impossible | Per-document replace (`/documents/{id}/reindex`), delete, whole-collection drop |
| Retrieval debugging | Scores only | `/query` returns threshold funnel (candidates vs kept) + embed/search timings |
| Citations | Raw chunk list | Context blocks labeled `[1]…[n]`, prompt demands inline cites, output carries structured `citations[]` |

### Engine identity plumbing
`NodeContext` now carries `workspace_id`/`user_id` (fed from the queue job through
`execute_workflow`, propagated into sub-workflows). The RAG node resolves
collections through the registry using this identity and auto-provisions in the
run's scope when missing. Bare engine runs without identity keep the legacy
direct-name path for local/test use.

### sqlite_vec hardening (same file format, same default)
- Writes are now ONE transaction with explicit chunk ids — the old two-batch
  autoincrement insert could desynchronise the vec↔meta join on partial failure.
- `meta_*` tables gain a `doc_id` column (ALTER TABLE migration inside the store,
  so existing databases upgrade transparently).
- New contract ops: `delete_chunks`, `delete_documents`, `count`,
  `document_ids`, `list_collections`, `delete_collection`; chroma implements the
  string-id equivalents.

## API

```
GET    /api/rag/collections                     scoped list
POST   /api/rag/collections                     create (workspace_id optional)
GET    /api/rag/collections/{id}                metadata
GET    /api/rag/collections/{id}/stats          chunks + document ids
DELETE /api/rag/collections/{id}                drop registry + vectors
POST   /api/rag/collections/{id}/documents      ingest/upsert (idempotent)
POST   /api/rag/collections/{id}/documents/{doc_id}/reindex   atomic replace
DELETE /api/rag/collections/{id}/documents/{doc_id}           remove
POST   /api/rag/collections/{id}/query          scored retrieval + debug telemetry
```

Embeddings require the optional AI extras (`requirements-ai.txt`);
endpoints answer **503** with install guidance when absent. UI: 📚 Knowledge
panel (create/delete, ingest/re-index, query debugger with scores+timings).

## Files

```text
backend/app/rag/__init__.py              # service: access, ingest, query, citations
backend/app/models/rag_collection.py     # registry model (+alembic d7f1a2b3c4e5)
backend/app/api/rag.py                   # management/query endpoints
backend/app/vectorstores/*               # extended contract + hardened backends
backend/app/nodes/rag_pipeline.py        # scoped resolution, dedupe, citations
backend/app/engine/{node_base,executor}.py, execution_runtime.py  # identity
frontend/src/components/RagPanel.jsx     # management + debug UI
```
