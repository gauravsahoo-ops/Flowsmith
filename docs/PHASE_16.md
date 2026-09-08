# Phase 16 — Queue-ready deployment & UI

> **Phase 15 made every run go through the job queue; Phase 16 makes
> that a production deployment and lets the UI live with it.**
> Docker compose now runs the API enqueue-only plus a **worker**
> service (`python -m app.queue.worker`, scale freely); deployment
> docs cover both worker modes, scaling, crash recovery and backends.
> The frontend treats `queued` as the live status it is: the store
> stays subscribed (WS + poll fallback) and the status chips show
> "queued…". 3 new frontend tests; suite green (backend 273, frontend
> 14), pyright + lint + build clean.

## 1. What Phase 16 delivers

- **`docker-compose.yml`** — two services from the one image:
  - `app` — UI/API/webhooks/stream on :8000, `QUEUE_EMBEDDED_CONSUMER
    =false` (enqueue only);
  - `worker` — `python -m app.queue.worker`, same `app-data` volume,
    `restart: unless-stopped`, starts after `app` (which initializes
    the shared schema).
  - Scale out with `docker compose up -d --scale worker=3`; claims are
    atomic so every job still runs exactly once.
- **`docs/deployment.md`** — new §1b: worker modes (embedded vs
  external), scaling, stale-heartbeat crash recovery (a crashed
  worker's claim is re-queued by an idle sweep), job timeouts belong
  to the workflow not the worker, queue backends (`QUEUE_BACKEND=db`
  zero-infra default; Postgres via `DATABASE_URL` or `redis` +
  `REDIS_URL` for workers across hosts), systemd template for bare
  metal. New env-var rows + `queue.worker` log note. `backend/
  .env.example` documents the same variables.
- **Frontend (`queued` is live, not terminal):**
  - `executionStore.js` — `load()` treats `queued` as live (connects
    the WS/poll so the run is picked up the moment a worker claims
    it); the WS-fallback poll loop and the 500ms `poll()` continue
    while `queued`.
  - `TopBar`, `ExecutionInspector`, `ExecutionHistory` — `queued…`
    status labels (the Cancel button was already available because the
    store's live flag drives it).
- **Tests** — executionStore tests cover `load()` with a `queued`
  execution (stays live), alongside the existing running/terminal
  cases.

## 2. Notes

- The compose stack shares one SQLite file between `app` and `worker`
  (multi-process SQLite is fine for a single host). For `--scale
  worker=N` with real concurrency, switch `DATABASE_URL` to Postgres —
  the queue backend then reads the same tables with zero code change.
- `QUEUE_BACKEND=redis` is the no-DB alternative; both backends pass
  the same contract tests (Phase 15).

## 3. Files

```text
docker-compose.yml                # + worker service; app enqueue-only
docs/deployment.md                # + §1b Queue workers, env table rows
backend/.env.example              # + QUEUE_BACKEND / REDIS_URL / consumer
frontend/src/stores/executionStore.js   # queued is a live status (3 spots)
frontend/src/components/TopBar.jsx       # + queued label
frontend/src/components/ExecutionInspector.jsx  # + queued label
frontend/src/components/ExecutionHistory.jsx    # + queued label
frontend/src/stores/executionStore.test.js      # + queued-load test
```

## 4. Verification

- `npm test` — 14 passed (3 in executionStore, new queued case green);
  `npm run build` and `npm run lint` clean (pre-existing warnings only).
- Backend untouched in this phase — Phase 15's 273 tests + pyright
  still green.