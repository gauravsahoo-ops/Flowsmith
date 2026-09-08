# Phase 5 — Live execution status over WebSocket (M5)

> **Milestone:** real-time node status on the canvas (spec 10) — an event
> bus in the backend plus a WebSocket endpoint, with the UI streaming
> events and falling back to polling.
> **Status:** backend + frontend done, E2E verified (direct and through
> the Vite proxy).

## 1. What Phase 5 delivers

M4 polled `GET /api/executions/{id}` every 500ms. M5 replaces that with
a live push channel:

```text
engine --events--> event bus --> WebSocket endpoint <--wss/ws--> canvas UI
```

- **Event bus** (`app/eventbus.py`) — in-process, Redis-shaped buffer.
  `publish(execution_id, event)` from the worker thread, `drain(execution_id, after_seq)`
  from the API loop. Per-execution ring buffer (maxlen 500) with an
  execution cap (100) and FIFO eviction; dropping this module for real
  Redis pub/sub is a drop-in change behind the same API.
- **Engine streaming** — `execute_workflow(..., event_sink=...)`: every
  event (execution started/completed/failed/cancelled, node
  started/completed/failed) is forwarded the moment it happens, in
  addition to being collected in `result.events`.
- **WebSocket endpoint** — `GET /api/ws/executions/{execution_id}?token=…`
  (browsers can't set WS headers, so auth goes in the query string):
  - bad token → close `4401`; unknown/foreign execution → close `4404`
  - drains the bus every 50ms and pushes each event
  - sends `{"type": "execution.terminal", "status", "error"}` and closes
    after a terminal event; if events were missed (e.g. the client
    connected after the run finished), a DB status fallback delivers the
    terminal anyway
- **Frontend** — `executionStore` opens the socket with the JWT,
  applies `node.started/completed/failed` statuses to node colors in
  real time, stops on `execution.terminal`, and falls back to the old
  500ms polling if the socket errors or closes unexpectedly. The Vite
  dev proxy forwards WS upgrades (`ws: true`).

## 2. Why it took the shape it did (bugs found on the way)

The naive first version had real races that only show against a live
server (TestClient runs the app in-process, so it hid them):

1. **Terminal status race** — the engine publishes `execution.completed`
   *before* the DB row is committed, so reading the DB at that moment
   yields `running`. The WS now derives the status from the event itself
   and only consults the DB for the error detail.
2. **Stale SQLite snapshot / deadlock** — a long-lived request session
   keeps an open read transaction; SQLite then (a) never lets the WS see
   the worker's later commits, and (b) blocks the worker's write commit
   (5s busy timeout) while it lives. The WS handler now `rollback()`s
   after every read, so each check is a fresh snapshot and never holds a
   lock the worker needs.
3. **`bus.clear()` race** — clearing the buffer when an execution
   finished could wipe the terminal events between the worker publishing
   them and the WS's next 50ms drain. The bus is now never cleared
   eagerly; it's bounded (500 events/execution, 100 executions) and
   evicts oldest-first, which makes late joiners work as a bonus.
4. **No `websockets` in the venv** — uvicorn was installed without
   `[standard]`, so real WS upgrades failed with 1006 (TestClient talks
   ASGI directly and never noticed). `websockets` is now in
   requirements.txt.

## 3. Files

```text
backend/app/
├── eventbus.py            # publish/drain/clear, seq numbers, eviction
├── api/ws.py              # /api/ws/executions/{id}?token= endpoint
├── api/executions.py      # event_sink -> bus.publish
├── api/common.py          # TERMINAL_STATUSES
└── engine/executor.py     # event_sink param, _forward helper

backend/tests/test_api/
├── conftest.py            # slow_node fixture moved here (shared)
└── test_ws.py             # 6 tests: stream, cancel, 4401 x2, 4404, fallback

frontend/
├── vite.config.js         # ws: true on the /api proxy
└── src/stores/executionStore.js  # WebSocket + poll fallback
```

## 4. Verified

- `pytest` — **114 passed** (6 new WS tests, re-run 4x for flakiness)
- `pyright` — 0 errors
- `npm run build` clean
- Live E2E through the Vite proxy: register → create → run → WS stream
  `execution.started → node.started/completed ×2 → execution.completed
  → terminal success`, socket closes 1000.
