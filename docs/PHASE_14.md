# Phase 14 — Vector store abstraction (sqlite-vec + chroma)

> **Milestone:** decouple the RAG Pipeline node from a single vector
> database. New `app/vectorstores/` layer with two backends: **sqlite-vec**
> (embedded, zero extra dependencies — the default) and **chroma**
> (existing optional-extras path). Ingestion/chunking/retrieval/
> synthesis behaviour is unchanged; only *where* vectors live is now
> pluggable, driven by one env var.
> **Status:** done — 18 new tests (9 sqlite_vec store, 5 chroma store,
> 4 more node) green; full suite 247 passed (was 229); pyright clean.

## 1. What Phase 14 delivers

```text
rag_pipeline node
      │  VECTOR_STORE env / config  (default: sqlite_vec)
      ▼
app/vectorstores/            contract (VectorStore ABC):
  sqlite_vec.py  ◄──┐         ensure_collection(name, dim) -> handle
  chroma.py  ◄──────┴──┐      add(handle, documents=, embeddings=, metadatas=)
                       │      query(handle, qvec, top_k) -> [{content,
                       │            metadata, similarity}]  best-first
                       ▼
              cosine similarity semantics on EVERY backend
              (1.0 == identical; threshold filters downstream in the node)
```

- **`app/vectorstores/`** — `VectorStore` ABC + `register_store`
  decorator + `get_vector_store()` factory reading
  `Settings.vector_store`. New backends are one file + one decorator.
- **`sqlite_vec.py` (new default)** — vectors live in a plain SQLite
  file (`VECTOR_STORE_PATH`, default `./data/vectors.db`) via the
  sqlite-vec extension (`requirements.txt`, tiny — **no** AI extras
  needed). Per-collection `vec0` virtual tables (`distance_metric`
  cosine) + metadata tables; auto-assigned integer chunk ids; sha256
  collection suffixes (safe identifiers, friendly listing), dimension
  mismatch → clear error; auto `PRAGMA busy_timeout` for concurrent
  node runs.
- **`chroma.py`** — the old hardwired path becomes backend #2 with the
  identical contract; collection now created with **explicit cosine
  space** (`hnsw:space: "cosine"`) — chroma's default is L2, which made
  "similarity" wrong for multi-chunk results (latent bug found by the
  new ordering tests). Requires `requirements-ai.txt`; raises
  `VectorStoreUnavailable` (→ node `OPTIONAL_DEPS_MISSING`) otherwise.
- **Node** (`rag_pipeline.py`) — store usage is now configuration
  driven; query drives collection dimension; `UNKNOWN_VECTOR_STORE`
  error for a bad backend name. `OPTIONAL_DEPS_MISSING` now applies to
  embeddings only (sentence-transformers) — the sqlite_vec path works
  on a base install once embeddings exist.
- **pgvector** is the planned next backend (PostgreSQL); documented in
  `vectorstores/__init__.py`, not yet implemented.

## 2. Why it took the shape it did (bugs found on the way)

1. **sqlite-vec `executemany` with bare strings** — Python's `sqlite3`
   treats each row as a parameter *sequence*, so a JSON-array string
   was splattered into 13/15 bindings ("Incorrect number of bindings").
   Every row must be a 1-tuple.
2. **chroma's default space is L2, not cosine** — the Phase 13 store
   assumed cosine for `1.0 - distance`, which only passed because
   single-chunk tests never compared orderings. Store tests now pin
   ordering and similarity on both backends; chroma collections are
   created cosine explicitly.
3. **chroma rejects empty metadata dicts** — `{}` raises
   "Expected metadata to be a non-empty dict"; normalized to `None` in
   the chroma backend (round-trips as `{}`), so the contract stays
   "metadatas may be empty" for both stores.
4. **Chromadb loader needs `enable_load_extension(True)` first** — the
   sqlite-vec `load()` helper fails with "not authorized" otherwise
   (Python 3.12+).

## 3. Files

```text
backend/app/
├── vectorstores/            # NEW plugin layer
│   ├── __init__.py          #   VectorStore ABC, registry, factory
│   ├── sqlite_vec.py        #   default embedded backend (sqlite-vec)
│   └── chroma.py            #   ChromaDB backend (optional extras)
├── nodes/rag_pipeline.py    # store-driven refactor (same params/outputs)
└── config.py                # vector_store / vector_store_path / chroma_persist_dir
backend/tests/
├── test_vectorstores/       # NEW
│   ├── test_sqlite_vec.py   #   9 tests (contract, isolation, persistence,
│   │                        #     dim mismatch, factory selection)
│   └── test_chroma.py       #   5 tests (same contract; importorskip)
└── test_nodes/test_rag_pipeline.py   # rewritten on sqlite_vec + FakeStore
                                       #   threshold/selection/dim tests
```

## 4. Verification

- `pytest tests/test_vectorstores tests/test_nodes/test_rag_pipeline.py`
  — 25 passed (all runnable on a base install except the chroma suite,
  which skips via importorskip).
- Full suite **247 passed**, pyright clean, `GET /api/nodes` still
  serves the unchanged `rag_pipeline` schema.