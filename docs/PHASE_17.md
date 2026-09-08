# Phase 17 — Node idempotency metadata (spec 35/26.1)

> **Spec 35: "every retry-capable node should document whether it is
> idempotent / conditionally idempotent / non-idempotent."** Every node
> now declares its retry safety, the registry rejects unknown levels,
> the catalog (`GET /api/nodes`) surfaces it, and the config panel
> shows it with a per-level hint so authors know what `retry_max_attempts`
> really buys them.
> **Status:** done — 5 new catalog tests; full suite 278 passed (was
> 273); pyright, vitest (14) and lint/build clean.

## 1. What Phase 17 delivers

- **`BaseNode.idempotency`** (spec 35) — one of:
  - `idempotent` (default) — deterministic, no external side effects:
    `manual_trigger`, `webhook`, `schedule`, `set_data`,
    `if_condition`. Re-running produces the same result.
  - `conditionally_idempotent` — safe only for the read-only variant:
    `http_request` (GET/HEAD/PUT/DELETE vs POST/PATCH),
    `database_query` (SELECT vs INSERT/UPDATE/DELETE).
  - `non-idempotent` — every run has irreversible/costed side effects:
    `send_email`, `ai`, `ai_agent`, `rag_pipeline` (model calls are
    billed on every run). Retrying after a failure may duplicate them.
- **Registry guard** — `register()` rejects invalid levels, so a
  typo'd declaration fails at import, not at runtime.
- **Catalog** — `list_nodes()` (and thus `GET /api/nodes`) includes
  `idempotency` per node (spec 26.1 metadata completeness, now
  covered by tests).
- **UI** — the config panel shows the node's level with a colored
  hint: "Safe to retry…", "Safe to retry for read-only runs…", or
  "Retrying may duplicate side effects (emails sent, model calls
  billed, rows written)."

## 2. Notes

- The engine already treats retries the way spec 35 asks: retries are
  opt-in per node (`retry_max_attempts`), permanent errors
  (`retryable=False`: bad credentials, invalid parameters) are never
  retried, and transient ones (network/timeout) are. The new metadata
  makes the remaining risk — duplicate side effects on a failed
  retryable node — visible to the author in the UI.
- Idempotency *keys* (the other half of spec 35) exist where a
  duplicate is a real concern: webhook deliveries carry
  `Idempotency-Key` support and the queue rejects duplicate
  `execution_id`s. Node-level external-POST idempotency keys remain a
  per-node feature for a future phase.

## 3. Files

```text
backend/app/engine/node_base.py    # idempotency attr + levels + docs
backend/app/nodes/{http_request,database_query,send_email,ai,ai_agent,
                    rag_pipeline}.py  # declarations + constant imports
backend/app/nodes/registry.py      # guard + catalog field
backend/tests/test_api/test_nodes.py  # NEW: 5 tests (first /api/nodes tests)
frontend/src/components/ConfigPanel.jsx  # idempotency badge + hint
frontend/src/index.css              # badge styles
```

## 4. Verification

- `pytest tests/test_api/test_nodes.py` — 5 passed (core metadata
  completeness, valid levels, pure-local nodes idempotent,
  side-effect nodes declared, unknown level rejection via the guard).
- Full suite **278 passed**; pyright clean; vitest 14 passed;
  `npm run build` / `npm run lint` clean (pre-existing warnings only).