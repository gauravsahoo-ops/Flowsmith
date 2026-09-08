# Phase 38 — Multi-Instance Readiness + Implementation-Order Execution

Executes the audit's P38–P42 items (P43 deferred) plus Salesforce
reconnect hardening after the dev-database wipe.

## P38 — Multi-instance login budgets
- `RedisFailureThrottle`: same contract as the memory throttle, counters
  in shared Redis (`login:fail:{key}` fixed-window INCR/EXPIRE,
  `login:lock:{key}` SETEX lockout). `get_login_throttle()` factory:
  Redis when REDIS_URL is set, memory otherwise. N API replicas now
  enforce ONE lockout per account/IP instead of N.
- 8 unit tests (fakeredis): lock/unlock/clear/isolation/reset + factory
  selection both ways.

## P41 — Test partitioning (timing marker)
- Registered `timing` marker; module/function marks on all queue-driven
  e2e tests (async recovery, executions incl. slow-node, env-execution,
  salesforce API suite, webhook/ws/schedule skip tests, google+hubspot
  full-stack, mcp tools, worker suites, seed-subprocess test).
- Split verified: **632 fast / 123 timing** of 755 total.
- CI runs both passes (`not timing` then `timing`) — nothing disabled,
  only sequenced so machine-load flake cannot mask real regressions in
  the fast signal.
- Fixed a self-inflicted collection corruption: files with an existing
  `pytestmark` had it overwritten by the batch insert; marks are now
  merged lists, and pytest.ini was restored to include the original
  asyncio config alongside the new marker.

## P40 — Approval UX
- executionStore retains `pause_state` and `results.approval`.
- Inspector: ⏸ waiting banner with the node's message while paused;
  "Approved/Rejected by user #N · timestamp" stamp on resumed runs
  (`formatApprovalStamp` helper + 3 vitest cases).

## P42-lite — MCP resources & prompts
- `GET /api/mcp/resources` — accessible workflows as
  `workflow://{id}` resources; `GET /api/mcp/resources/workflow/{id}`
  returns the document.
- `GET /api/mcp/prompts` — prompt library (summarize-execution,
  draft-lead-sync, explain-workflow).
- 4 tests.

## Salesforce reconnect hardening (post-wipe)
- Org config re-verified end-to-end: authorize URL builds correctly and
  the org responds 302 → login page (live probe).
- Lead Sync template present; admin account recreated; template library
  reseeded into the dev database.

## Evidence
- Fast pass: **627 passed / 0 failed** (325 s)
- Timing pass: **122 passed / 1 fixed race** → ws cancellation now
  accepts either the live event or the durable terminal fallback
  (123/123 green after fix)
- pyright repo-wide **0 errors** · vitest **111** · lint/build clean

## Known limitations / follow-ups
- P43 (fourth connector) intentionally deferred.
- MCP SSE/streamable transport not included (resources/prompts/tools
  over REST only).
- Nightly loadtest still needs a git remote to run on CI.
