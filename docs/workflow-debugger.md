# Phase 13 — Workflow Debugger

Turns the execution inspector into a real debugger: a timeline of the
run, per-node input/output/error inspection with retry counts and API
status, replay, safe single-node retry (upstream never re-runs), and
execution comparison. **Secrets are masked twice** — server-side before
payloads leave the API and client-side in every JSON viewer.

## What you see

| Requirement | Where |
|---|---|
| Execution timeline | `ExecutionTimeline.jsx` — span chart; bar left/width from `started_at`+`duration_ms` relative to the run window; colour by status; retry-touched bars get an amber ring |
| Node inputs | step detail → Inputs (`JsonTree`, collapsible) |
| Node outputs | step detail → Outputs |
| Errors | failed steps carry code + message inline; execution-level banner unchanged; ✨ Explain AI hook retained |
| Retry attempts | structured `attempts`/`retries` on every trace step (backend now records them — previously only prose notes); badges + ↻N chips in the list |
| Duration | per-step wall clock + whole-run duration; Δ column in compare |
| Branches | derived from persisted handle outputs: `true/false` (IF), `route_0..2`/`default` (Switch) — chips show which branch took how many items |
| Loop iterations | loop nodes emit one output item per iteration — the debugger surfaces item counts as outputs/branch chips (visible scale without new engine instrumentation) |
| API status | HTTP-shaped outputs `{status, body\|items}` surface an `API 200` badge (green <400, red otherwise) |
| Connector responses | connector-served steps show a 🔌 badge parsed from the engine note + full response payload in Outputs |

## Actions

- **Inspect** — select any timeline bar or step row; full detail pane.
- **Replay** — existing endpoint: re-runs the exact snapshotted version
  with the original trigger input.
- **Safe node retry** *(new)* — `POST /api/executions/{id}/retry
  {node_id}`. Backend rules:
  - target must exist in the snapshot AND have status error/failed,
    else 404/409;
  - creates a NEW execution (trigger `node_retry`) whose job carries
    `_retry_from_node` + `_retry_source`;
  - `run_job` seeds `initial_results` from the source execution's
    persisted outputs **minus the target and its descendants**
    (`engine.graph.descendant_ids`) — the engine skips seeded nodes, so
    upstream side effects can never repeat;
  - audited with `{mode: node, node_id}`.
  The UI classifies safety from catalog idempotency metadata: declared
  idempotent/conditionally-idempotent → one click; anything else →
  explicit "side effects may repeat" confirmation.
- **Execution comparison** — pick any sibling execution; aligned
  per-node table with status transitions, duration Δ (green/red),
  retries and structural output-equality flags.

## Secret handling (never expose secrets)

1. Nodes never receive raw credentials (side-channel resolver) and the
   engine does not record them.
2. NEW `app/engine/redact.py`: before `GET /executions/{id}` and
   `/trace` return, every string under a sensitive-looking key
   (password/token/api[_-]key/auth/cookie/secret/…) is replaced with
   `••••••••`. Key-name based only — ordinary debugging fields survive.
3. Client-side mirror (`utils/debugger.maskJson`) re-applies masking in
   every `JsonTree`, so even locally-cached payloads render masked.

## Files

```
backend/app/engine/redact.py          # key-based payload redaction
backend/app/engine/graph.py           # + descendant_ids()
backend/app/engine/executor.py        # trace steps gain attempts/retries
backend/app/engine/errors.py          # declare retry_after attribute
backend/app/api/executions.py         # retry {node_id}, redacted reads
backend/app/execution_runtime.py      # _retry_from_node seeding
frontend/src/utils/debugger.js        # pure debugger helpers
frontend/src/components/{JsonTree,ExecutionTimeline,StepDetail,ExecutionCompare}.jsx
frontend/src/components/ExecutionInspector.jsx  # debugger shell (3 tabs)
```

## Tests

Backend `tests/test_api/test_debugger.py`: flaky-node fixture proves
attempts/retries on success and give-up paths; secret-masking through
both read endpoints; full-stack node retry (409 on non-failed target,
404 unknown node, upstream seeded — no `trigger` step in the new run —
target re-executed); full replay regression. Frontend
`src/debugger.test.js` (12): masking incl. separator normalisation,
timeline math, branch/API-status/connector parsing, retry-safety
classification, diff logic. vitest 147/147 · build clean · pyright 0 on
touched modules.
