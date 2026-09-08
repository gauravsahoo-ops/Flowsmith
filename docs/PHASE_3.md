# Phase 3 — REST API (M3)

> **Milestone:** Auth, workflow CRUD, run/executions endpoints per spec
> section 9. TestClient tests pass.
> **Status:** 108 tests passing, pyright 0 errors.

## 1. What Phase 3 delivers

The backend is now a real API server (FastAPI + SQLAlchemy + SQLite).
The engine from M1/M2 runs behind it, with executions recorded to the
database and a consistent `{"data": ..., "meta": ...}` response
envelope on every endpoint (spec section 9).

```text
frontend (later)  ──►  /api/*  ──►  routers  ──►  SQLAlchemy/SQLite
                                      └───────►  engine (executor)
                                      └───────►  runner thread (background)
```

## 2. Endpoints implemented (all from spec section 9)

- `POST /api/auth/register` · `POST /api/auth/login` — JWT (HS256),
  passwords hashed with PBKDF2-SHA256 (600k iterations)
- `GET/POST /api/workflows` · `GET/PUT/DELETE /api/workflows/{id}`
  · `PATCH /api/workflows/{id}/active`
- `POST /api/workflows/{id}/run` → `execution_id` (202)
- `GET /api/executions?workflow_id=` · `GET /api/executions/{id}`
  · `GET /api/executions/{id}/items` (paginated node snapshots)
  · `POST /api/executions/{id}/retry` · `POST /api/executions/{id}/cancel`
- `GET /api/nodes` · `GET /api/nodes/{type}/schema` (from the registry)
- `GET /api/health`
- `POST /api/webhooks/{path}` — reserved stub (501; arrives with M7)

## 3. Design decisions

- **Validation on write:** create/update run the engine's graph
  validation (cycles, unknown types, duplicate ids, bad handles) and
  reject broken workflows with 422 before anything is stored.
- **Exact-version execution:** every save bumps `version`; each
  execution snapshots the workflow JSON, so retry re-runs the exact
  saved version (spec 24.2/24.3).
- **Background runner** (`app/runner.py`): executions run on a
  dedicated event loop in a daemon thread — never cancelled by request
  lifecycle, cooperatively cancellable via a per-execution
  `asyncio.Event`. Shared httpx client (SSL context creation is
  expensive). This is the v1 stand-in for the Celery worker (M7).
- **SQLite now, Postgres later:** `DATABASE_URL` env var; the schema is
  SQLAlchemy models, so switching to Postgres is config-only. No Docker
  needed locally.
- **Cancellation is cooperative** (spec 25.2): nodes poll
  `ctx.is_cancelled()`; a cancel lands between nodes or on the next
  poll of a running node.

## 4. Verification

```text
108 passed (engine 44 + nodes 29 + API 35)
pyright: 0 errors, 0 warnings
uvicorn app.main:app  →  /api/health returns {"data":{"status":"ok"}}
```

## 5. Known limitations (deferred deliberately)

- Runs are in-process only (single worker); a queue lands with M7.
- Retry is immediate, no backoff config yet (spec 8.6 comes with M9).
- No rate limiting yet (spec 51.4) — single-user v1.
- Credential storage/endpoints (encryption) are M6.