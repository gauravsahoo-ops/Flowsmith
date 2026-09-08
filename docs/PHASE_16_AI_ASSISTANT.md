# Phase 16 — AI automation assistant

> **Milestone:** six assist surfaces over one contract — every
> suggestion is **validated** (against real schemas, the live
> expression engine or deterministic analyzers), **editable** (plain
> JSON/text), **explainable** (rationale included), and **strictly
> non-destructive** (no endpoint mutates anything; applying is a normal
> client-side edit that still goes through the user's explicit save).
> **Status:** done — 24 new backend tests (17 unit + 7 full-stack),
> vitest 163 (+4), pyright 0 on touched modules.

## Surfaces

| Surface | Endpoint | Grounding | LLM role |
| --- | --- | --- | --- |
| Field mapping | `POST /api/ai/suggest-mapping` | upstream output shapes from the last execution (`_uf_impl`/`_flatten_item`); every expression linted; unknown source refs → warnings | proposes `{target: expression}` |
| Expression generation | `POST /api/ai/suggest-expression` | lint + real resolver preview against a sample item (`preview_value`) | writes one expression |
| Node configuration | `POST /api/ai/suggest-node-config` | parameters validated with the node's pydantic schema / connector op contract; caller pins `operation` | proposes parameters + rationale |
| Workflow optimization | `POST /api/ai/optimize-workflow` | **deterministic analyzer** (`UNREACHABLE_NODE`, `NO_TIMEOUT`, `NO_RETRY_ON_IDEMPOTENT` with concrete fix previews) — always correct without an LLM | advisory narrative only |
| Workflow explanation | `POST /api/ai/explain-workflow` | structure summary built from the actual graph | plain-language walkthrough (≤180 words, "never invent steps") |
| Workflow documentation | `POST /api/ai/document-workflow` | markdown skeleton generated deterministically | optional overview paragraph; works with NO llm credential |

Error explanation already existed (`POST /api/ai/explain`, Phase 8).

## Non-destructive guarantee

- Assist endpoints require only **view** permission and never write.
- The ConfigPanel "✨ AI assist" section shows the proposal as editable
  JSON with its validation verdict; **Apply** performs a normal local
  edit via `updateNode` — persistence still requires the usual Save.
- Audit trail: every call logs `ai.assist` with surface + targets.

## Deterministic testing

Scripted chat functions replace the network in both layers:

- Unit (`tests/test_ai/test_assistant.py`): mapping lint/warn rules,
  expression preview values, schema-rejected config suggestions,
  pinned connector operations, exact analyzer findings, doc-without-LLM.
- Full stack (`tests/test_api/test_assistant_api.py`): endpoints return
  validated data, workflow record byte-identical after assist calls,
  intruder gets 404s, document works without any credential.

Found + fixed while building: the reachability analyzer initially walked
*upstream* from triggers (everything flagged unreachable) — caught by
the clean-workflow test before it could mislead users.

## Files

```text
backend/app/ai/assistant.py          # all surfaces (chat injectable)
backend/app/ai/validation.py         # + check_connector_operation / validate_node_parameters
backend/app/api/ai.py                # 6 new endpoints (read-only)
backend/tests/test_ai/test_assistant.py
backend/tests/test_api/test_assistant_api.py
frontend/src/components/ConfigPanel.jsx  # ✨ AI assist (suggest→edit→apply)
frontend/src/api.js (+api.test.js)       # 6 methods
```
