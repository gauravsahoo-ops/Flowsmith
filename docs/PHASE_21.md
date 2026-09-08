# Phase 21 — Workflow versioning & rollback (spec 24.2)

> **Status:** done — every save creates an immutable version snapshot
> (`workflow_versions`), `GET /api/workflows/{id}/versions` lists the
> history, `POST /api/workflows/{id}/rollback` restores an old version
> as a *new* version (never overwrites history), and executions still
> run the exact saved version. Frontend: version badge in the config
> panel + rollback button.

## 1. What Phase 21 delivers

- **Immutable snapshots** — on create (`version=1`) and on every
  `PUT /api/workflows/{id}` the workflow body is stored in a
  `workflow_versions` row before the live record is bumped to the new
  version. History can never be mutated.
- **`GET /api/workflows/{id}/versions`** — version metadata list
  (version number, created_at), newest first; accessible to owner and
  edit-shared users.
- **`POST /api/workflows/{id}/rollback`** — takes `{version: N}`,
  restores snapshot N's body and saves it as version `current + 1`.
  Rolling back is itself a versioned event, so nothing is ever lost.
- **Run fidelity** — executions continue to snapshot the saved
  workflow JSON at run time (spec 24.2), so runs always match the
  version that was active when they started.

## 2. Files

```text
backend/app/models/workflow.py    # workflow_versions table + workflow.version
backend/app/api/workflows.py      # snapshot-on-save, versions, rollback
backend/app/db.py                 # migration: workflow_versions table
frontend/src/components/ConfigPanel.jsx   # version badge + rollback UI
frontend/src/stores/workflowStore.js      # listVersions / rollbackVersion
```

## 3. Verification

- Workflow save bumps version and snapshots; versions list returns
  history; rollback creates a new version with the old body.
- Covered by the workflow API tests; full suite green.