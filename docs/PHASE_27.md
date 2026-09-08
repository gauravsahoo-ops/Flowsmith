# Phase 27 — Workflow Delete Functionality

> **Milestone:** deleting a workflow is now a **soft delete** end to end.
> The backend already had a DELETE endpoint (owner-only), but it hard-
> deleted the row — which would 500 on PostgreSQL (executions/versions
> hold FK references without ON DELETE) and silently orphan history on
> SQLite. The delete now marks `deleted_at` + deactivates the workflow:
> it disappears from every access path (list/get/run/versions/shares/
> executions), yet the record, its version snapshots, and its execution
> history stay in the database and remain auditable by the owner.
> Shares are removed and trigger registrations reconciled.
> **Status:** done — full backend suite 517 passed, vitest 24 passed,
> 3/3 e2e passed, pyright clean on changed app code.
> **API:** `DELETE /api/workflows/{id}` (unchanged surface, owner-only).

## 1. What already existed (not duplicated)

- Backend `DELETE /api/workflows/{id}` in `app/api/workflows.py`
  (owner-only via `is_owner`, audit `workflow.delete`, trigger sync) —
  but a **hard delete** (`db.delete(rec)`). `WorkflowRecord` had no
  `deleted_at` column.
- Frontend delete option (delete button + confirmation + store action +
  tests) was already implemented in the UI work prior to this phase.

## 2. Why soft delete (the decision)

- `Execution.workflow_id` → FK `"workflows.id"` with **no ON DELETE**
  (`app/models/execution.py`): executions are audit rows that keep a
  `workflow_data` snapshot.
- `WorkflowVersionRecord.workflow_id` — same, no ON DELETE.
- `WorkflowShare.workflow_id` — `ondelete="CASCADE"` (schema intent:
  shares die with the workflow).
- SQLite dev/test DBs don't enable `PRAGMA foreign_keys=ON`, so a hard
  delete silently orphans executions/versions locally; PostgreSQL
  (production) enforces the FK and would raise IntegrityError → 500.
- **Conclusion:** soft delete (`deleted_at`) is the only approach
  consistent with the schema: execution history is preserved for audit,
  shares are removed at delete time (schema intent), and it works on
  both databases. Do NOT blind-cascade executions/versions.

## 3. Backend changes

- `app/models/workflow.py`: added `deleted_at` column
  (auto-migrated on existing SQLite DBs by `_migrate_missing_columns`).
- `app/api/access.py`: `get_permission`, `accessible_ids`, `editable_ids`
  now exclude `deleted_at is not None` — deleted workflows are invisible
  to *every* caller and every endpoint (404), so no endpoint needed a
  per-route guard.
- `app/api/workflows.py` DELETE: sets `deleted_at` + `active=False`,
  deletes the workflow's share rows, commits, records `workflow.delete`
  audit, and runs `sync_webhooks` (deactivation also removes webhook/
  schedule trigger rows — verified by test).
- `app/api/workflows.py` rollback: now permission-scoped via
  `get_workflow(..., require_edit=True)` — this closes a pre-existing
  authz gap found during the delete work (rollback previously checked
  only row existence, so a stranger could roll back a workflow they
  couldn't see, and a soft-deleted workflow could be *resurrected*
  through it). Soft-deleted workflows now 404 on rollback like every
  other path.
- `app/api/executions.py` `_can_view_execution`: the **owner** may still
  open the detail/trace of executions belonging to a deleted workflow
  (audit preservation — each row carries its own snapshot). Non-owners
  lose access with the workflow. Execution **listing** excludes deleted
  workflows (via `accessible_ids`) and **retry** stays denied (404) —
  `_can_edit_execution` unchanged.
- Deleting twice → 404 (not a silent no-op). POST to a deleted id →
  409 (id cannot be resurrected). **No Salesforce functionality was
  touched.**

## 4. Frontend changes

None needed — the delete option shipped earlier (TopBar 🗑 Delete with
`window.confirm`, `workflowStore.deleteWorkflow` action that clears the
pending save timer, resets state, and loads the first remaining workflow
or a fresh "My Workflow", select `key={workflow?.id}` remount). This
phase added the end-to-end proof:

- `frontend/tests/e2e/delete-workflow.spec.ts`: fresh user → capture
  workflow id → dismiss dialog (workflow kept) → accept (store switches
  to a fresh workflow, `GET /api/workflows/{id}` → 404, id absent from
  the list) → refresh (app boots on the new workflow, never the deleted
  one). Fix during development: the wait condition had to require a
  non-null workflow id (delete passes through `workflow: null`).

## 5. Tests

- `backend/tests/test_api/test_workflow_delete.py` (9, full stack):
  successful delete hides the workflow everywhere (list/get/put/patch/
  run/versions/rollback all 404, row soft-deleted + deactivated); 404
  for stranger and shared editor; 404 unknown; 404 already-deleted;
  version snapshots preserved in DB but unreachable; execution history
  preserved (row + snapshot) with owner detail/trace still readable,
  excluded from listing, retry 404, stranger 404; shares removed from
  DB and shared user sees nothing; webhook trigger rows removed; audit
  `workflow.delete` recorded.
- Full backend suite: **517 passed** (508 + 9 new; no regressions).
- Frontend: vitest **24 passed** (incl. the 3 delete-workflow store
  tests), playwright **3/3 passed** (save-reload, delete-workflow,
  happy-path). Pyright clean on changed `app/` code.

## 6. Known issues / notes

- PostgreSQL production DBs need the new `deleted_at` column via
  `create_all` on a fresh DB; existing PG DBs need one manual
  `ALTER TABLE workflows ADD COLUMN deleted_at TIMESTAMPTZ`.
- Deleted workflows are gone forever — there is no restore endpoint
  (rollback is blocked on deleted rows). Intended.
- The aborted earlier e2e attempt left no file; the spec was written
  fresh in this phase.

## 7. Run

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests/test_api/test_workflow_delete.py tests/test_api/test_workflows.py -q
cd ..\frontend
npx vitest run
npx playwright test delete-workflow.spec.ts
```
