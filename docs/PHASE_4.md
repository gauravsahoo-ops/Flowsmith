# Phase 4 — Canvas v1 (M4)

> **Milestone:** React Flow canvas — drag nodes, connect, save, run,
> see result (spec 18).
> **Status:** Vite + React + React Flow app, E2E verified through the
> dev proxy.

## 1. What Phase 4 delivers

The first UI. A real drag-and-drop canvas backed by the M3 API:

```text
React app (Vite) ──/api──► FastAPI (proxy, port 5173 → 8000)
```

- **Login / signup** screen (JWT stored in localStorage, auto-logout on 401)
- **Sidebar** — node catalog from `GET /api/nodes`, grouped by category, draggable
- **Canvas** — React Flow: drop nodes, connect handles, drag, zoom, minimap
- **Config panel** — schema-driven form per node (text, number, checkbox, JSON
  fields for objects/arrays) plus per-node execution settings
  (`continue_on_error`, `timeout_seconds`)
- **Top bar** — editable workflow name, workflow switcher + "New", save
  indicator, Active toggle, Run / Cancel, run status
- **Autosave** — every canvas change triggers a 500ms-debounced
  `PUT /api/workflows/{id}` (spec 11)
- **Run with live node colors** — Run starts the execution, the UI polls
  `GET /api/executions/{id}` every 500ms (the spec's explicit polling
  fallback) and nodes turn green/red/amber live; skipped nodes grey out.
  M5 upgrades this to WebSockets.

## 2. Structure

```text
frontend/src/
├── api.js                 # fetch wrapper: JWT + {data,meta} unwrap
├── mappers.js             # React Flow <-> workflow JSON (spec 6)
├── stores/
│   ├── workflowStore.js   # nodes/edges + debounced save (spec 11)
│   ├── executionStore.js  # run/cancel + status polling
│   └── uiStore.js         # selection
├── components/
│   ├── Login.jsx          # register/login
│   ├── TopBar.jsx         # name, save state, run/cancel, active toggle
│   ├── Sidebar.jsx        # draggable palette from /api/nodes
│   ├── Canvas.jsx         # React Flow canvas + drop target
│   ├── CustomNode.jsx     # icon + name + live status dot
│   └── ConfigPanel.jsx    # schema-driven parameter form
└── index.css              # dark theme
```

## 3. How to run it

```powershell
# terminal 1
cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --reload

# terminal 2
cd frontend; npm run dev      # http://localhost:5173
```

## 4. Verification

```text
npm run build: clean
E2E through the Vite proxy: register → create workflow → run → success
  with correct node outputs
Backend: 108 tests still green
```

## 5. Known limitations (deferred deliberately)

- Status updates poll instead of WebSockets (that is exactly M5).
- Config panel handles scalar/boolean/JSON fields; rich pickers
  (credential dropdown, expression autocomplete) come later.
- Workflow list is a dropdown, not a full dashboard page.
- No per-node I/O inspector yet (that is M8).