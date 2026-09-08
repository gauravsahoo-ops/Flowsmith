# Phase 31 — Environments End-to-End (`{{ $env.* }}`)

Workspace-scoped environment variables are now a first-class part of the
execution model, not just stored configuration.

## What was already there (and what was broken)

- `environments` table + `/api/environments` CRUD existed, scoped per
  workspace, with secret masking on list.
- **Gaps fixed this phase:**
  - Values were stored as plaintext despite the "encrypted at rest"
    contract (spec 12/29).
  - `GET /api/environments/{workspace_id}` had **no tenant check** — any
    authenticated user could read any workspace's variables.
  - Nothing resolved env vars at execution time; there was no `$env`
    expression surface at all.

## Implementation

- **Encryption at rest**: every create/update now stores values through
  `app.security.crypto.encrypt_text` (the credential Fernet keyring,
  multi-key rotation compatible). Legacy plaintext rows keep resolving
  (best-effort decrypt falls back to the raw value).
- **Tenant isolation**: listing requires workspace/org membership
  (`_require_ws_member`); existence is hidden with 404. Write access
  stays creator-only (unchanged semantics).
- **Runtime resolution**: workers resolve the job's workspace variables
  from PostgreSQL at job start (`app.environments.resolve_env_vars`) —
  workers stay stateless (spec 34). The enqueue payload carries
  `workspace_id`; jobs queued before this change fall back to a workflow
  lookup.
- **Expression surface**: `$env` joined the context next to `$cred`
  (`build_context(..., env_vars=...)`). Unresolved refs stay visible
  (`{{ $env.NOPE }}`), matching the existing contract.
- **Workflow ↔ workspace link**: `POST /api/workflows` accepts an
  optional `workspace_id` (validated membership) so workflows can opt in.

## Secret hygiene

- Secret values are masked in API responses (last-4 only).
- Decryption happens once per job, inside the worker.
- Verified end-to-end: a secret consumed by an `http_request` header via
  `{{ $env.API_TOKEN }}` never appears in the persisted execution
  record, results or trace.

## Tests (11 new)

- `tests/test_api/test_env_execution.py` (7): full-stack resolution via
  the queue/worker/engine with a recording HTTP client; secret never in
  the record; encryption-at-rest against the raw DB row; tenant
  isolation; non-owner write rejection; unresolved-ref contract;
  no-workflow-workspace defaulting.
- `tests/test_expressions.py` (4): `$env` lookup, missing-ref visibility,
  interpolation inside strings, `??` fallback.

## Test-infrastructure hardening (same phase)

While verifying this phase, two environmental failure modes were root-
caused and eliminated permanently:

- **Stale server processes stealing jobs**: any app process sharing the
  dev database consumes from the same job queue; a leftover
  ``python -m app.serve`` would claim queued test jobs and execute them
  against its own node registry (impossible-looking UNKNOWN_NODE_TYPE /
  connector errors). Tests now default to a **dedicated
  ``automate_test`` database** (auto-created; CI keeps its explicit
  ``DATABASE_URL``), so stray servers can never see test jobs.
- **IPv6 loopback hijack**: on dual-stack Windows hosts another listener
  can occupy ``[::1]:5432``; ``localhost`` may resolve there first and
  hit an unrelated PostgreSQL. The harness normalizes localhost to
  ``127.0.0.1``.

## Known limitations / follow-ups

- No environment manager UI yet (API-only); planned with the templates/
  approvals UX batch (P32).
- Env vars are not exposed to connector-level auth flows (OAuth connect
  still uses its own credential storage).
- `{{ $env }}` is resolved at job start — long-running executions do not
  observe mid-run edits (deliberate: deterministic runs).
