# Phase 10 — Executions history view (M8 completion)

> **Milestone:** the executions *list* UI to complete M8's History UI
> (list + per-node I/O inspector + retry — the inspector, retry and
> cancel already existed from M5/M8 backend work).
> **Status:** done; frontend tests + build, live API smoke verified.

## 1. What Phase 10 delivers

```text
TopBar 🕘 History ─▶ GET /api/executions?page&pageSize ─▶ ExecutionHistory panel
                                 │  (pagination meta, current-workflow filter)
                                 ▼ click a row
                    executionStore.load(id) ─▶ inspector hydrates with
                    the full trace/node statuses; still-running runs
                    resume live WebSocket updates
```

- **Backend**: `GET /api/executions` now joins each row's
  `workflow_name` from the workflows table so the list is readable
  without a second lookup. (`_to_dict` already exposed id, version,
  trigger, status, error, started/finished.)
- **Frontend `api.js`**: a `requestEnvelope` variant that returns
  `{data, meta}` (the old `request` unwraps as before) and
  `api.listExecutions({workflowId, page, pageSize})`.
- **`executionStore`**: `history`, `historyMeta` (page/pageSize/total),
  `historyLoading/Error`, `fetchHistory({workflowId, page})` for the
  list, and `load(id)` — opens *any* past execution into the inspector
  (status, trace, node statuses, version, times, error); if the run is
  still running it resumes the live WebSocket stream; failures surface
  as a `LOAD_FAILED` error in the inspector instead of a dead panel.
- **`ExecutionHistory.jsx`**: side panel with status-dot rows (name,
  trigger, status, time, duration, version), refresh, "Load more…"
  pagination (25/page), and — when a workflow is open — a filter to
  just that workflow's runs.
- **`TopBar`**: a 🕘 History button; the panel opens/closes like the
  Credentials modal.

## 2. Why it took the shape it did

1. **`request()` was shaped for bodies, not lists** — the envelope
  (`{data, meta}`) existed server-side but the client discarded `meta`;
  adding `requestEnvelope` instead of parsing headers kept pagination
  totals without touching every existing caller.
2. **Old runs can still be executing** — webhook/schedule runs outlive
  the canvas, so `load(id)` had to feed the *poll/WebSocket fallback*
  path (`connect(id)` for live runs), not just render a snapshot.

## 3. Files

```text
backend/app/api/executions.py       # workflow_name join in list endpoint
backend/tests/                      # test_executions.py (shape) 12 passed

frontend/src/
├── api.js                          # requestEnvelope + listExecutions
├── stores/executionStore.js        # history + fetchHistory + load(id)
├── stores/executionStore.test.js   # 6 tests: pagination, filter, error,
│                                   #   load hydration, live, load failure
├── components/ExecutionHistory.jsx # new panel (94 lines)
├── components/TopBar.jsx           # 🕘 History button
├── App.jsx                         # panel toggle
└── index.css                       # panel/row/status-dot styles
```

## 4. Verification

- `npm run test` — 13 frontend tests pass (7 canvas + 6 history store);
  `npm run build` clean; `pytest tests/test_api/test_executions.py`
  passes.
- Live E2E: created a workflow via the API, ran it, then
  `GET /api/executions?pageSize=5` returned
  `total=1, workflow_name="History Smoke", trigger="manual",
  status="success", workflow_version=1`; clicking the row in the UI
  opened the trace in the inspector. The `backend/logs/e2e_*.log`
  artifacts from that run were removed from tracking.

## 5. Known limits

- The history is workspace-wide, not cross-tenant; pagination is
  cursor-free (offset), fine at the current scale.