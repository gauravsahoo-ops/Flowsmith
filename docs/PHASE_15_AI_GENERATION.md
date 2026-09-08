# Phase 15 — Natural-language workflow generation (grounded + validated)

> **Milestone:** "Describe it → review it → create it." The planner is
> grounded in the LIVE node/connector registries, every candidate is
> validated against reality before the user ever sees it, and creation
> is an explicit approval step. Generated workflows are born as
> **inactive drafts**; activation stays a manual decision.
> **Status:** done — 39 new backend tests (5 catalog, 18 validation,
> 10 deterministic eval, 6 full-stack API), vitest 159 (+4 approval-gate),
> pyright 0 on touched modules.

## 1. Pipeline

```text
user prompt
  → system prompt RENDERED FROM LIVE REGISTRIES   (app/ai/catalog.py)
  → LLM candidate JSON                             (app/ai/generation.py)
  → validate_candidate()                           (app/ai/validation.py)
      ├─ node existence        (engine graph validation)
      ├─ schema compatibility  (pydantic params + op input schemas)
      ├─ operation existence   (connector definitions only)
      ├─ connections/handles/cycles
      ├─ expression lint       (roots/pipes/dunder/braces)
      └─ credentials           (missing → warning, never silent)
  → bounded repair loop (≤2 attempts, errors fed back verbatim)
  → PREVIEW response {workflow, validation, created: false}
  → user clicks "Create workflow" → draft (inactive)
```

The old implementation hardcoded 9 node types and auto-created whatever
the model returned — including teaching the model a fictional
`if_condition` parameter shape (`left/operator: "==|!=|..."`) that the
real schema rejects. The prompt is now generated from `NODE_REGISTRY`
(28 types with their true JSON schemas) plus the ConnectorRegistry
(21 connectors / 83 operations), rendered deterministically.

## 2. Anti-invention contract

- The model can only be *told about* node types, operations, parameters
  and credential types that actually exist (they come from the
  registries).
- Even if it hallucinates anyway, `validate_candidate` rejects:
  unknown node type (`UNKNOWN_NODE_TYPE`), invented operation
  (`INVALID_OPERATION`), missing required operation field
  (`MISSING_REQUIRED_FIELD`), schema-violating parameters
  (`INVALID_PARAMETER`), dangling connections/cycles, expressions with
  unknown roots/pipes or dunder access (`INVALID_EXPRESSION`,
  `UNSAFE_EXPRESSION`).
- Connector-op validation mirrors executor routing exactly: registered
  node classes always win over connector fallbacks, and trigger-only
  connector definitions (e.g. `webhook`, zero ops) are not op surfaces.

## 3. Approval gate

- API returns `created: false`; nothing is persisted by the generate
  endpoint. Audit still records `ai.generate` with attempt/warning counts.
- Frontend (`Sidebar`): the AI box swaps to a preview card — name, node
  list with operations, validation errors (block) and warnings (e.g.
  `MISSING_CREDENTIAL` for unconnected providers) — with explicit
  **Create workflow** / **Discard** actions (`approveGenerated` /
  `discardGenerated` in workflowStore).
- Created workflows are `status="draft"` server-side regardless of what
  the model claims; activation remains the manual toggle.

## 4. Deterministic evaluation

`tests/test_ai/test_eval.py` runs the real pipeline with a scripted
fake chat (no network, no credentials): an eval matrix pins
(plan, creds) → verdict with exact issue codes, proves the repair loop
fixes-or-refuses hallucinated nodes, checks markdown-fence tolerance,
and requires byte-identical reports across repeated runs.

## 5. Latent bug fixed along the way

`TestClient(app)` without a `with` block never runs lifespan, so the
connector registry was empty on the request path — any connector-only
node type failed validation as UNKNOWN_NODE_TYPE outside production
startup order. Added idempotent `ensure_builtin_connectors()` used by
graph validation, catalog building and candidate validation.

## 6. Files

```text
backend/app/ai/{catalog,validation,generation}.py   # NEW: plan, check, repair
backend/app/api/ai.py            # endpoint rewritten: grounded + preview-only
backend/app/engine/graph.py      # lazy connector fallback registration
backend/app/connectors/__init__.py  # ensure_builtin_connectors()
frontend/src/components/Sidebar.jsx  # preview/approval UI
frontend/src/stores/workflowStore.js # generated state + approve/discard
backend/tests/test_ai/*          # catalog, validation, eval suites
backend/tests/test_api/test_generation_api.py
```
