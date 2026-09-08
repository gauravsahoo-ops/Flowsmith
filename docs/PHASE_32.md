# Phase 32 — Human Approval End-to-End + Client UX Batch

## Part A — Fixing human approval (it was silently broken)

The node and endpoints existed, but the real flow never worked:

1. The node marked the execution ``waiting_approval`` mid-run, then
   returned normally; the engine finished "successfully" and the runtime
   **overwrote the status with ``success``** — the pause was invisible.
2. ``resume`` therefore always answered 409 ("not waiting").
3. Even if it had worked, resume re-enqueued a payload whose
   ``_approval_data`` never reached the node (nothing seeded the node KV
   store), so the node would have paused again forever.
4. Re-enqueueing was impossible anyway: the jobs table is unique per
   execution and the original row stayed terminal.
5. Latent engine bug surfaced by the work: ``ctx.node_id`` was never set
   per node, so nodes could not identify themselves.

### What replaced it

- **Engine**: ``execute_workflow(initial_results=..., storage_seed=...)``
  replays persisted node outputs (pre-seeded nodes are not re-executed)
  and pre-loads the per-run KV store; ready descendants of pre-seeded
  nodes are scheduled without re-running parents.
- **Runtime**: when a run ends while the DB says ``waiting_approval``,
  progress (trace/statuses/results) is persisted but no terminal status
  or ``finished_at`` is written; the job completes as done.
- **Node contract**: on resume the decision arrives via storage —
  approved → input items pass through; rejected → the run fails typed
  with ``APPROVAL_REJECTED``. ``pause_state`` on the execution row
  records node id/message/approvers for the inbox and authorization.
- **API**:
  - ``POST /api/executions/{id}/resume`` takes ``{"approved": bool}``
    (query param still accepted), enforces edit permission plus the
    node's ``approvers`` list, resets the original job row via the new
    ``QueueBackend.requeue`` (DB + Redis implemented).
  - ``GET /api/executions?status=…`` filter powers the inbox.
  - Cancelling a waiting execution terminates it immediately.
- **Model**: ``executions.pause_state`` JSON column (auto-added by the
  existing startup column migration).

## Part B — Client-facing UI

Three panels over previously API-only backends, following the existing
React/zustand conventions:

- **✅ Approvals inbox** (`ApprovalsPanel.jsx`): paused runs with message,
  Approve/Reject actions, inspector hand-off, refresh; non-approvers see
  the backend's 403 verbatim.
- **📋 Templates gallery** (`TemplatesPanel.jsx`): lists templates with
  category/use counts; “Use” copies via the validating import endpoint
  into a brand-new workflow loaded onto the canvas.
- **🌍 Env panel** (`EnvPanel.jsx`): workspace selector, variable list
  (secrets masked), upsert/delete forms with secret flag; shows the
  creator-only write rule through real error text.

Plus: ``waiting approval`` status labels in history/top bar, new API
client functions, CSS matching the existing design language.

## Tests

- Backend (`tests/test_api/test_human_approval_flow.py`, 6): full-stack
  pause → waiting status preserved (no ``success`` clobber), downstream
  untouched while paused, inbox filter, approved resume replays without
  re-running the trigger, rejection fails typed, cancel-while-waiting,
  approver restriction 403, query-param compatibility, double-resume 409.
- Frontend: 10 new vitest cases over the new API surface (108 total).
- Full suites: backend 692 passed / 0 failed · vitest 108/108 ·
  Playwright E2E 6/6 · lint/build clean.

## Known limitations / follow-ups

- Node metadata (who approved, when) is not persisted into results yet —
  visible only as run success/failure (P33 candidate).
- ``timeout_hours`` auto-reject remains unimplemented (documented v1).
- No E2E spec for the approvals panel itself (backend flow fully covered).
