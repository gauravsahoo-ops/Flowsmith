# Connector Ecosystem Expansion — Prioritized Implementation Plan

**Date:** 2026-10-13
**Inputs:** `CONNECTOR_ECOSYSTEM_AUDIT.md` (capability inventory + evidence-based status),
`CONNECTOR_LICENSE_RISK_REPORT.md` (clearance).
**Ordering rule:** honesty fixes first, then the shared framework (highest leverage), then breadth,
then verification. Nothing ships as a placeholder.

---

## Priority legend

- **P0** — violates an explicit spec rule (fake success / placeholder). Blocks everything else.
- **P1** — shared framework; unlocks consistent UI for *every* node at once.
- **P2** — breadth: missing connectors/nodes/pagination in the stated priority order.
- **P3** — consistency, test depth, hardening.

---

## P0 — Honesty & integrity fixes (do first)

| ID | Work item | Files | Done when |
|---|---|---|---|
| **P0-1** | **`mssql`**: remove the fabricated `{"executed": True, "rows_affected": 1}` fallback. A missing driver or a host matching `mock|test|localhost` must raise a typed, actionable error — never return success. Keep the real `pymssql` path. | `backend/app/connectors/mssql_connector.py` | No code path returns success without a driver round-trip; test asserts error on missing driver. |
| **P0-2** | **`rabbitmq`**: same treatment. Simulated results must be explicitly flagged **and** never masquerade as delivery; ImportError must raise, not return `"status":"success"`. | `backend/app/connectors/rabbitmq_connector.py` | Same assertions. |
| **P0-3** | **`s3`**: implement genuinely — SigV4-signed REST calls over the existing `httpx`/`cryptography` stack (no new dependency) for `upload_file`, `download_file`, `list_objects`, `delete_object`. If credentials/driver are absent, raise. | `backend/app/connectors/s3_connector.py` | Unit tests pass against a local mock HTTP transport; no hardcoded `{"status":"success"}` remains. |
| **P0-4** | **Config panel**: delete the fabricated `Test Step` preview (`status: "success", simulated: true`). When there is no execution path, disable the button with an explanatory reason instead of inventing output. | `frontend/src/components/parameters/DynamicNodeConfigPanel.jsx` | Test asserts: no `onExecuteStep` ⇒ button disabled, no fabricated payload. |
| **P0-5** | **`schedule` / `webhook` connectors**: return neutral, clearly-labelled metadata (`{"kind": "trigger_metadata"}`) rather than `"success": True`. | `schedule_connector.py`, `webhook_connector.py` | No `success: True` emitted without work performed. |
| **P0-6** | Regression guard: a repo-wide test that fails if any connector `op_execute` returns a hardcoded success literal on an error path. | `backend/tests/test_no_fake_success.py` | Test suite enforces P0-1..5 permanently. |

---

## P1 — Schema-driven configuration framework (the core deliverable)

> Objective 5: *one consistent configuration panel for every node*, with dynamically generated
> fields, dropdowns, credential selection, conditional parameters, validation, descriptions,
> defaults, and output previews.

| ID | Work item | Files | Done when |
|---|---|---|---|
| **P1-1** | Finish `ParameterSchemaBuilder`: emit `show_if` for **all** conditional relationships (not just operation membership), `group`, `advanced`, `required`, `options` with labels, `placeholder`, and **`output_preview`** (JSON-Schema of the operation result). | `backend/app/parameters/schema.py` | Unit tests cover select/conditional/required/advanced/output-preview extraction. |
| **P1-2** | Expose enriched fields on **both** catalog and single-node endpoints. | `backend/app/api/nodes.py` (`GET /nodes`, `GET /nodes/{type}/parameters`, `GET /nodes/{type}/schema`) | `GET /api/nodes/{type}` returns `fields[]` + `operations` + `output_preview`. |
| **P1-3** | Make `DynamicNodeConfigPanel` consume `fields[]`: honour `show_if`, render `group`/`advanced` sections, show `required` marks, use `options[].label`, `placeholder`, and per-field validation messages. | `DynamicNodeConfigPanel.jsx` | Conditional fields show/hide correctly; invalid required field blocks Test Step. |
| **P1-4** | **Validation**: required-field + type/min/max/enum validation before execute; inline error text under each field. | `DynamicNodeConfigPanel.jsx` + `utils/parameterValidation.js` | Unit tests for each rule. |
| **P1-5** | **Output preview**: show the operation's declared output schema (shape, required keys) in the panel, and render the real result beneath it after a run. | `DynamicNodeConfigPanel.jsx` | Panel shows expected-vs-actual. |
| **P1-6** | **Credential selection for every node**: iterate *all* `credential_types`, not just `[0]`; support "create new credential" inline. | `DynamicNodeConfigPanel.jsx` | Multi-credential nodes (e.g. HTTP generic auth) can pick per type. |
| **P1-7** | **Editor registry**: replace the 20-branch conditional in `NodeEditorModal.jsx` with a `nodeEditorRegistry = { type: Component, fallback: DynamicNodeConfigPanel }`. Dedicated editors stay; routing becomes declarative. | `NodeEditorModal.jsx`, new `utils/nodeEditorRegistry.js` | Same behaviour, one lookup table, default = dynamic panel ⇒ **every** node has a config panel. |
| **P1-8** | Frontend tests for the panel (visibility, validation, credential picker, output preview, disabled test button). | `parameters/DynamicNodeConfigPanel.test.jsx` | Vitest green. |

---

## P2 — Breadth: connectors, operations, pagination

Ordered by the brief's stated priority.

### P2-A Priority connectors (verify + deepen, don't rebuild)

| ID | Connector | Work |
|---|---|---|
| **P2-A1** | **Salesforce** | Already deepest (12 ops, SOQL, bulk, describe, custom API, flow invoke, pagination). *Verify only* — audit each op's request shape against the public REST/SOAP docs; add `returnAll`/`limit` tests. |
| **P2-A2** | **Microsoft Dynamics 365** | 8 ops but **no pagination**. Add cursor/`$skiptoken` paging to `query`/`search`; add entity-schema-driven field hints. |
| **P2-A3** | **HubSpot** | 4 ops, **no pagination**, missing `delete`/`getRecentlyCreated` equivalents. Add `crm/v4` search paging (`after` cursor), add `delete`, `list` (paged) for contacts/companies/deals/tickets. |
| **P2-A4** | **HTTP/API** | Already free-form + generic auth. Add: response pagination modes (`next_url`, page-param, cursor), `paginate` limit, `raise_on_status`. |
| **P2-A5** | **Databases** | postgres/mysql/mssql/sqlite/snowflake/supabase/bigquery/mongo/redis all present. Add `return_all`/`max_rows` guards to `query` ops so large result sets are bounded. |

### P2-B Pagination framework

| ID | Work item |
|---|---|
| **P2-B1** | Reusable pagination abstraction in the connector SDK: `Paginator` with `cursor` / `page_param` / `next_url` strategies + `max_pages` / `page_size` / `return_all` params, surfaced as standard `PaginationSpec` fields. |
| **P2-B2** | Apply to the 54 connectors lacking pagination, starting with priority order: dynamics_crm, hubspot, http, then all `list_*` connectors. |
| **P2-B3** | Declare `max_pages`/`page_size` in each definition so the config panel renders them automatically (ties into P1-3). |

### P2-C Missing core nodes (objective 4)

In dependency order; each must be real, tested, and auto-covered by the dynamic panel:

| ID | node_type | Notes |
|---|---|---|
| **P2-C1** | `rename_keys` | pure transform |
| **P2-C2** | `summarize` | aggregation over items |
| **P2-C3** | `jwt` | sign/verify via already-present `PyJWT` |
| **P2-C4** | `totp` | TOTP/HOTP via `cryptography` |
| **P2-C5** | `ldap` | search/bind via `ldap3` (check license: MIT — add to `THIRD_PARTY_LICENSES.md`) |
| **P2-C6** | `read_pdf` | extract text (pypdf, BSD-3) |
| **P2-C7** | `edit_image` | Pillow (HPND/MIT-CMU) |
| **P2-C8** | `ai_transform` | structured field mapping via existing `chat_completion` |
| **P2-C9** | `sse_trigger` | Server-Sent Events listener |
| **P2-C10** | `workflow_trigger` | lifecycle events (created/updated/executed) |
| **P2-C11** | `amqp` / `mqtt` / `kafka` nodes | optional; only if drivers already available — otherwise documented as a gap |

### P2-D Triggers & webhooks (objective 6)

| ID | Work |
|---|---|
| **P2-D1** | Confirm webhook + schedule + error + form + chat triggers are wired end-to-end (`api/webhooks.py`, `models/webhook.py`, delivery records) and add missing delivery-retry/verification. |
| **P2-D2** | OAuth coverage: verify each OAuth2 connector has a working connect/reconnect path in `credentials/oauth_manager.py`; list connectors whose OAuth is declared but not implemented. |

---

## P3 — Testing, verification, hardening

| ID | Work item |
|---|---|
| **P3-1** | **Unit**: connector op contracts (schema in/out), `ParameterSchemaBuilder`, validation utils, each new node. |
| **P3-2** | **Integration**: mock-transport execution of every priority connector operation (real request shape asserted, not canned responses). |
| **P3-3** | **Security**: SSRF guard, credential redaction, no secret leakage in errors/trace, input-schema fuzzing. |
| **P3-4** | **E2E**: Playwright — open each node type, assert config panel renders with fields + credential picker + operation dropdown; run happy-path workflow. |
| **P3-5** | **Regression**: full `pytest -m "not timing"`, `vitest run`, `npm run build`, `playwright test`. |
| **P3-6** | Migrations (`alembic`) checked for pending revisions; no model change expected this phase. |

---

## Verification gates (every stage)

1. `cd backend && python -m pytest -q -m "not timing"` — must not regress vs. recorded baseline.
2. `cd frontend && npx vitest run` and `npm run build` — must pass.
3. New/changed connectors: at least one integration test per operation asserting a **real**
   outbound request (mock transport) and correct error propagation.
4. No hardcoded success literals added anywhere in `app/connectors` or `app/nodes`.
5. `THIRD_PARTY_LICENSES.md` updated for every new dependency.

---

## Deliverable mapping

| Brief deliverable | Document / artifact |
|---|---|
| 1. Connector & node inventory | `docs/CONNECTOR_ECOSYSTEM_AUDIT.md` §2–§3 |
| 2. License & reuse-risk report | `docs/CONNECTOR_LICENSE_RISK_REPORT.md` |
| 3. Prioritized implementation plan | this document |
| 4. Connector modules + config UI | P0/P1/P2 code changes |
| 5. Automated test results | `docs/CONNECTOR_FINAL_REPORT.md` §test results |
| 6. Final report | `docs/CONNECTOR_FINAL_REPORT.md` |

---

## Scope discipline

- **Do not** rebuild what is already real: 67/69 connectors and all 69 nodes perform genuine I/O.
- **Do not** claim coverage for anything not executed and asserted.
- Work incrementally; run the gates after each priority band.
- Preserve all existing (including uncommitted) FlowSmith work — nothing is reverted or overwritten.
