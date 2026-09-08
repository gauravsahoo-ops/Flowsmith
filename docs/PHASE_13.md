# Phase 13 — RAG Pipeline node (spec 20)

> **Milestone:** the third AI node — ingest documents, embed them,
> retrieve relevant chunks and synthesize an answer, all in one node.
> **Status:** done — `tests/test_nodes/test_rag_pipeline.py` (5 tests)
> green; full suite 229 passed; pyright clean.

## 1. What Phase 13 delivers

```text
[any upstream node] ──► RAG Pipeline
                          │   source_type: text | file | url
                          │   source:      content / path / URL
                          │   collection_name (default "rag_default")
                          │   chunk_size / chunk_overlap
                          │   embedding_model (all-MiniLM-L6-v2)
                          │   query / top_k / similarity_threshold
                          │   system_prompt / temperature / max_tokens
                          ▼
              ingestion: chunk → embed (sentence-transformers) → store
              retrieval: embed query → top_k → filter by cosine threshold
              synthesis: context → LLM (openai-compatible, `llm` credential)
                          ▼
                   output: { answer, chunks_used, chunks[] }
```

- **`app/nodes/rag_pipeline.py`** — ingestion (text/file/URL), automatic
  overlapping chunking, local embedding via sentence-transformers,
  vector storage in ChromaDB (`CHROMA_PERSIST_DIR`, default
  `./chroma_db`), retrieval with a `similarity_threshold` on cosine
  distance, and LLM synthesis. Missing query → `MISSING_QUERY`; missing
  `llm` credential → `CREDENTIALS_REQUIRED`; no relevant context →
  `{answer: "No relevant context found.", chunks_used: 0}` **without
  calling the LLM**.
- **Optional extras, not new core deps.** `chromadb` +
  `sentence-transformers` are heavy (torch), so they live in
  `backend/requirements-ai.txt` and are imported **lazily inside the
  node**. The node imports cleanly on a base install and reports a
  friendly `OPTIONAL_DEPS_MISSING` error when run without the extras —
  base Docker image and CI stay lean.
- **No chromadb embedding-function coupling.** Instead of the library's
  embedding-function protocol (which changed across chromadb versions),
  the node computes embeddings itself and passes `embeddings=` /
  `query_embeddings=` directly — version-proof and keeps a single
  embedding source of truth.

## 2. Why it took the shape it did (bugs found on the way)

1. **chromadb 1.5.x broke with the legacy custom embedding function** —
   create_collection on a bare callable blew up with an `InternalError`
   (the library now requires the `is_legacy()` protocol). Fixed by not
   passing an embedding function at all: the node embeds with
   sentence-transformers and hands chromadb ready-made vectors.
2. **EphemeralClient shares one in-memory system per process** — in
   chromadb the `"ephemeral"` identifier is process-global, so tests
   writing the same collection name contaminated each other's results
   (a chunk from one test appeared in another). Tests now use unique
   collection names.
3. **Editor/CI environment split** — the vector deps exist in the dev
   venv but not in CI (which installs only requirements.txt); any
   top-level import would fail CI's pyright. Lazy imports + `Any`-typed
   cache settle both worlds (and Pylance noise was traced to a stale
   root `pyrightconfig.json` pointing at a nonexistent venv path).

## 3. Files

```text
backend/app/
├── nodes/rag_pipeline.py   # RAGPipelineNode + chunk/embed/retrieve helpers
└── requirements-ai.txt     # NEW: optional AI extras (chromadb, sentence-transformers)
backend/tests/
└── test_nodes/test_rag_pipeline.py  # 5 tests (chunking, threshold filter,
                                     #   cred/query/deps errors, happy path,
                                     #   no-context path) — chroma tests
                                     #   importorskip on a base install
```

## 4. Verification

- `pytest tests/test_nodes/test_rag_pipeline.py` — 5 passed (with the
  extras installed); without the extras they skip, mirroring the node's
  lazy behaviour.
- Full suite 229 passed, pyright clean, registry lists `rag_pipeline`
  (11 built-in nodes).