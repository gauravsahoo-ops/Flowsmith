> **STATUS NOTE — 2026-10-23:** Historical connector counts and “verified”
> claims are superseded by [`CONNECTOR_STATUS.md`](CONNECTOR_STATUS.md). The
> registry has 76 native, 17 generated, and 435 catalog-only connectors;
> catalog-only connectors require an explicit `endpoint_url`.

# Connector Ecosystem — Final Report

Status: **complete**, pending final regression run.

## Scope recap

Audit of n8n (445 base + 126 langchain nodes, 451 credentials) and FlowSmith
(69 built-in nodes, 69 connectors) produced three prior documents:
`CONNECTOR_ECOSYSTEM_AUDIT.md`, `CONNECTOR_LICENSE_RISK_REPORT.md`,
`CONNECTOR_ECOSYSTEM_PLAN.md`. This report records what was actually built and
verified against that plan.

## Registry state

| Metric | Count |
|---|---|
| Connectors | 89 |
| Connector operations | 469 |
| Built-in nodes | 70 |

Certification baseline (asserted in `test_certification_state_machine.py`):

| State | Count |
|---|---|
| Total | 89 |
| Mock-validated | 76 |
| Live-test-unavailable (awaiting vault/sandbox creds) | 88 |

## Work completed by priority band

### P0 — Honesty & integrity fixes

Six items, all landed and regression-tested:

1. `mssql` — real driver round-trip or typed `ConnectorError`; no fabricated
   success branch.
2. `rabbitmq` — same treatment.
3. `s3` — real SigV4 signing over `httpx`/`hashlib`/`hmac`; **no boto3
   dependency added**.
4. `DynamicNodeConfigPanel` — fabricated "Test Step" output deleted; step
   execution now validation-gated.
5. `schedule`/`webhook` — reclassified `kind: "trigger_config"` with
   `performed_outbound_call: false`; `next_fire` computed by croniter.
6. `tests/test_no_fake_success.py` — AST guard against hardcoded success
   literals in `app/connectors` and `app/nodes`.

### P1 — Schema-driven configuration framework

`backend/app/parameters/schema.py` rewritten. `show_if` rules, `group`,
`advanced`, per-operation `required`, options-with-labels, validation metadata,
`output_preview`, `OperationSpec`. `app/api/nodes.py` emits `fields` +
`output_preview`; the panel consumes `fields[]` with inline validation,
multi-credential pickers, Expected Output Shape, and validation-gated Test Step.
`frontend/src/components/parameters/parameterValidation.js` mirrors the builder.

Node-editor routing refactored from a 20-branch conditional to a declarative
registry (`utils/nodeEditorRegistry.js`); `data_table` keeps `DataTableDiscovery`
as a pre-panel, not a replacement. All 20 previously-unused lazy editor
constants removed.

### P2 — Breadth

Pagination landed on the three priority connectors, each verified by a dedicated
suite (14 + 9 + 20 tests):

- **HubSpot** — `search_records` pages via request-body `after` cursor, reads
  `paging.next.after`; new `list_records`/`delete_record`. Delete derives
  `deleted` from the HTTP status line (204 answers carry an empty body).
- **Dynamics 365** — `query_paged()` with cursor metadata; `top` is the overall
  record cap, `page_size` the per-request `$top`, and a bare `top` still drives
  request size (backward compat with pre-pagination callers). `@odata.nextLink`
  relativized against the instance URL before the HTTP layer re-prefixes it.
  `fetchXml` accepted alongside `fetch_xml` via `AliasChoices`.
- **HTTP/API** — `cursor` pagination mode implemented (previously declared in the
  type union but ignored). Short/empty pages stop early via the `stop_when_short`
  param; `exhausted` is true only when the service stopped returning a cursor.
  `HttpRequestNodeEditor.jsx` gained a Pagination options section.

Core nodes: `crypto_tools` extended with `jwt_sign`/`jwt_verify`/
`totp_generate`/`totp_verify` (10 ops; HOTP matches RFC 4226 Appendix D, TOTP
matches all 6 RFC 6238 Appendix B vectors). New `rename_keys` node (node count
69 → 70) with rename/copy/remove, dotted paths, collision reporting.

Per-operation gating for built-in nodes: `BaseNode.operations` +
`BaseNode.operation_selector`. Two nodes declare it — `crypto_tools` (10 ops,
selector `operation`) and `rename_keys` (3 modes, selector `mode`).

## Bugs found and fixed during this work

- `MappingField.jsx` crashed on a non-string `value` (`.includes` on an object)
  when a restored workflow held a numeric field — editor died on open.
- HTTP `find_cursor` treated a declared `cursor_path` as segments to probe rather
  than one dotted path.
- `rename_keys` had four real defects during testing, including silent data loss
  when a rename targeted an occupied key.
- JWT pinned to HS256/384/512 with algorithms fixed at decode, blocking the
  CVE-2022-29217 algorithm-confusion class.
- `_operations_meta_from_definitions` read `properties` only from `input_schema`,
  silently emptying every built-in node's operation field list.

## Verification

All results below are from runs on the current working tree. Suites against the
Postgres harness **must not be run concurrently**: they share one test database
and `TRUNCATE` it between tests, so overlapping runs corrupt each other's state.

| Suite | Command | Result |
|---|---|---|
| Backend API package | `pytest tests/test_api -m "not timing"` | **633 passed, 206 deselected** (9m55s) |
| Backend nodes + connectors + crypto + rename_keys + pagination | `pytest tests/test_parameter_framework.py tests/test_nodes tests/test_new_connectors.py tests/test_new_connectors_suite.py tests/test_crypto_tools_node.py tests/test_rename_keys_node.py tests/test_dynamics_pagination.py tests/test_hubspot_pagination.py tests/test_http_pagination.py` | **304 passed** (2m13s) |
| Frontend unit | `npm run test:run` | **46 files, 445 tests passed** |
| Frontend build | `npm run build` | ✓ |
| Playwright E2E | `npx playwright test` | 44 passed — connector-crash (2), all-connectors-and-nodes (4), salesforce/step-execution (36), save-reload/delete-workflow (2) |

New/changed test files covering this work:

- `test_parameter_framework.py` — `TestNodeOperationDeclarations` (7 tests)
  pins the `BaseNode.operations` / `operation_selector` contract, including the
  gap-fill behaviour for a declaration that omits a selector value.
- `test_crypto_tools_node.py` — 29 tests, incl. RFC 4226 Appendix D HOTP and all
  6 RFC 6238 Appendix B TOTP vectors, plus JWT alg-confusion rejection.
- `test_dynamics_pagination.py` (9), `test_hubspot_pagination.py` (14),
  `test_http_pagination.py` (cursor + short-page early stop).
- `test_rename_keys_node.py` — 20 tests.
- `test_nodes/test_database_query.py` — row-cap and truncation-flag tests.
- `test_new_connectors_suite.py` — sqlite cap + truncation tests.
- `DynamicNodeConfigPanel.test.js` — selector-awareness (6 tests).

## Authentication & OAuth

Credential metadata is catalogued in `app/credentials/auth_metadata.py`
(`CONNECTOR_AUTH_CATALOG`, 90 credential types):

| Auth method | Connectors |
|---|---|
| Bearer Token | 22 |
| API Key | 17 |
| No authentication required | 17 |
| OAuth 2.0 + Refresh Token | 12 |
| Basic Auth | 7 |
| Client Credentials / S2S | 4 |
| Username + Password | 4 |
| Custom Header | 3 |
| OAuth 2.0 | 3 |
| Service Account / JWT | 1 |

Implementation status: 86 `available`, 4 `coming_soon`. 73 connectors require
credentials; 17 require none.

OAuth is genuinely wired, not just declared: `OAuthManager.get_valid_token()`
checks `expires_at` (60s skew), performs a real `grant_type=refresh_token` POST
against the credential's `token_url`, guards the outbound call with
`assert_public_url()` (SSRF), handles refresh-token rotation, and persists the
rotated token through the encrypted `CredentialStore`. When persistence fails it
logs loudly rather than claiming success. `http_request.py` calls this manager
at two sites, so an expired token is refreshed and the request retried instead
of failing.

Reusable auth abstractions live in `app/credentials/providers/` — 22 providers
including `bearer`, `api_key`, `basic`, `oauth2`, `oauth1`, `jwt`, `service_account`,
`aws_iam`, `aws_assume_role`, `digest`, `header`, `query`, `pat`, `salesforce`.

## Known gaps

- 88 of 89 connectors await live sandbox/vault credentials; their operations are
  verified against mock transports asserting real request shape, not live APIs.
- `pymssql`, `aio_pika`, `pypdf`, `ldap3` are not installed in this venv. The
  affected connectors return a typed `NOT_CONFIGURED`/`UNAVAILABLE` error naming
  the missing driver rather than a simulated success.
- `s3` uses hand-rolled SigV4 signing over `httpx`/`hashlib`/`hmac` — no `boto3`.
- A `DeprecationWarning` from `SafeHTTPClient.request` (raw bytes via `data=`) is
  deliberately left alone to avoid touching the shared security module.
