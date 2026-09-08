# Phase 23 — Connector Framework (spec 37) + Salesforce connector

> **Status:** done — a full Connector Framework (SDK, registry, error
> taxonomy, discovery API, engine routing) ships with three built-in
> connectors (http/schedule/webhook) and a real first-party connector:
> **Salesforce** (OAuth2 password grant, SOQL query, record
> create/get/update/delete, describe, list objects). Connector-only
> node types are draggable on the canvas and run through
> `ConnectorSDK.op_execute()` end-to-end.

## 1. What Phase 23 delivers

- **`ConnectorSDK`** (`app/connectors/__init__.py`) — base class:
  `connect/disconnect`, `node_types`, `op_execute(operation, payload,
  context)`, `op_health_check`, metadata, `to_dict()`.
- **Typed errors** — `ConnectorError` + `ConnectorErrorCode`
  (AUTH_FAILED, RATE_LIMITED, TIMEOUT, BAD_REQUEST, UNAVAILABLE,
  NOT_FOUND, FORBIDDEN, VALIDATION_FAILED, NOT_CONFIGURED) with a
  `retryable` flag; `make_connector_error()` builds them consistently.
- **Versioned definitions** — `ConnectorDefinitionV1`,
  `ConnectorOperationV1`, `ConnectorTriggerV1`, `CredentialTypeV1`,
  `ConnectorLifecycle`, `ConnectorCategory`.
- **`ConnectorRegistry`** — register/unregister, duplicate + lifecycle
  validation, node-type indexing, `primary_for_node_type()`, health
  batch checks; module-level singleton via `get_registry()`.
- **Discovery API** — `GET /api/connectors`, `/{key}`, `/{key}/operations`,
  `/{key}/triggers`, `/{key}/credential-types` (auth-protected).
  Built-in connectors now register **populated** definitions
  (operations/triggers/credential_types) — previously empty.
- **Engine routing** (`executor.py:416`) — for node types with no
  built-in node class, the engine executes via the registered
  connector: resolved params become the payload, resolved credentials
  are passed in `context["credentials"]`, retries/timeouts/cancellation
  apply, and the trace records "Via connector '…'".
- **Node catalog integration** — `GET /api/nodes` merges connector-only
  node types (icon 🔌, connector params schema, `credential_types`), so
  they are draggable and configurable like any other node.
- **`SafeHTTPClient`** (`app/security/safe_http_client.py`) — SSRF
  protection, per-request timeouts, redacted headers, `data=` support
  for form-encoded POSTs; all connector HTTP goes through it.
- **Salesforce connector** (`app/connectors/salesforce_connector.py`):
  OAuth2 password grant against `{instance_url}/services/oauth2/token`
  (token cached 2h, org instance URL adopted from the token response),
  then `/services/data/v63.0/...` calls. Operations: `query` (SOQL),
  `get`, `create`, `update`, `delete`, `describe`, `list`. Uses the
  `salesforce` credential type (instance_url, client_id, client_secret,
  username, password, api_version).

## 2. Credential types

New `salesforce` credential in `app/credentials/registry.py` —
secret fields `client_secret` + `password`, encrypted at rest,
metadata-only API, resolved at run time like every other type.

## 3. Files

```text
backend/app/connectors/__init__.py            # SDK, errors, definitions, singleton, builtin registration
backend/app/connectors/registry.py            # ConnectorRegistry
backend/app/connectors/operations.py          # ConnectorOperations mixin + build_operations
backend/app/connectors/http_connector.py      # HTTP connector
backend/app/connectors/schedule_connector.py  # schedule connector (cron trigger)
backend/app/connectors/webhook_connector.py   # webhook connector (receive trigger)
backend/app/connectors/salesforce_connector.py# Salesforce connector (NEW)
backend/app/api/connectors.py                 # discovery endpoints
backend/app/api/nodes.py                      # connector-only node types in catalog (NEW)
backend/app/engine/executor.py                # connector routing, retries, timeout, trace
backend/app/engine/graph.py                   # validate connector-only node types
backend/app/credentials/registry.py           # salesforce credential type (NEW)
backend/app/security/safe_http_client.py      # SSRF-safe client + data= support
backend/tests/test_connector_integration.py   # engine<->connector routing tests
backend/tests/test_salesforce_connector.py    # Salesforce tests (NEW)
backend/tests/test_api/test_connectors.py     # discovery/catalog tests (NEW)
frontend/src/components/Sidebar.jsx           # "Connectors" section (NEW)
```

## 4. Verification

- `test_salesforce_connector.py` — token fetch + SOQL query,
  token caching (1 token for 2 calls), auth failure → AUTH_FAILED,
  rate limit → RATE_LIMITED/retryable, operation from payload,
  unknown operation rejected, missing credential → NOT_CONFIGURED,
  engine routes `salesforce` node via connector with credentials,
  engine retries a retryable error, populated definitions.
- `test_connector_integration.py` — routing, credentials, retry
  semantics, node-class precedence, trace note.
- Full suite **299 passed**; pyright clean; vitest 15 passed;
  frontend lint/build clean.