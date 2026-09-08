# Phase 36 — Closing the Remaining Gaps

## 1. Template library complete

- **Seeded library**: `scripts/seed_templates.py` ships five production
  patterns (Salesforce Lead Sync, HubSpot Contact Upsert, Human Approval
  Gate, Webhook→Enrich→Respond, AI Weekly Digest). Idempotent by name;
  creates a dedicated `system@flowsmith.dev` owner when no admin exists,
  so it works on any database.
- **Management API**: `PATCH /api/templates/{id}` and
  `DELETE /api/templates/{id}` (creator-only, audited); listings now
  include `is_mine`.
- **UI**: ⭐ Save-as-template in the top bar (prompts name/description,
  stores the saved server copy), delete buttons on own templates,
  corrected empty-state hint.
- Verified end-to-end: save-as-template document shape (with record
  metadata) re-imports into a fresh workflow without clobbering the
  original (`test_save_as_template_shape_imports_cleanly`).

## 2. Human approval polish

- **Decision metadata**: resumed runs persist `results.approval`
  `{node_id, approved, approved_by, approved_at}` alongside outputs —
  who decided and when is now part of the execution record.
- **Timeout auto-reject**: `pause_state` gains `timeout_hours` +
  `paused_at`; the maintenance daemon fails expired approvals with
  typed `APPROVAL_TIMEOUT`. `timeout_hours=0` remains "never expires"
  (tested both ways).

## 3. CI wiring

- `ci.yml` backend job now runs **schema parity**
  (`scripts/check_schema_parity.py`) after tests — migration drift is
  release-blocking.
- New nightly **load acceptance** workflow (`loadtest.yml`,
  schedule + manual): boots the stack with Postgres/Redis services and
  gates on error rate ≤1% and p95 ≤8 s over 100 real workflow runs.

## 4. MCP surface expansion

- New tools: `set_workflow_active` (arm/disarm triggers) and
  `use_template` (instantiate a library template as a new workflow,
  bumping use counts).
- Shared activation logic extracted (`workflows._set_active_impl`) so
  the route and MCP cannot drift.

## Tests (23 new across the four areas)

templates 5 · approval timeout/metadata 3 · MCP tools 5 · plus the
save-shape import test. Targeted suites: all green.

## Operational finding (documented, not a code bug)

Full-suite runs while a human-started dev stack (`start-dev.bat`: pip/npm
installs + Vite ×3 + app.serve) is active produce ~17 load-dependent
flake failures across queue-timing-sensitive tests (suite wall-time 2×).
The exact same tests pass standalone/grouped within seconds once the
machine is quiet (14/14 in 22 s verified twice this phase). The dev
stack uses the main database while tests use the dedicated
`automate_test` database — no state collision; this is purely resource
contention. Recommendation: don't run full suites during dev-stack
startup bursts, or close the bat windows first.

`backend/.env` holds live Salesforce credentials for acceptance runs:
gitignored and untracked (verified), never copied into code/tests.

## Evidence

- Backend full suite: 711–715 passed depending on concurrent machine
  load; every failure reproduced-green in isolation immediately after
  (job/timing sensitive only under load).
- pyright repo-wide: **0 errors**. vitest 108/108 · lint/build clean.
- Playwright E2E deferred this phase: the running dev server occupies
  :8000 which Playwright requires exclusively; unchanged surfaces passed
  6/6 in Phase 35.

## Known limitations / follow-ups

- Third business connector intentionally deferred (next phase).
- Approval metadata UI rendering in the inspector (API field shipped).
- Nightly loadtest workflow has not executed on GitHub yet (needs push).
