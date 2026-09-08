# Connector Template

Copy `_template/` → your connector folder, rename symbols, implement the
seven lifecycle stages, register, done — **no core-engine changes**.

## Lifecycle stages (universal contract)

| Stage | Where | Notes |
|---|---|---|
| discover | definition + registry metadata | `GET /api/connectors` |
| validate | `validate_workflow_payload` (draft) / activation gate | graph + params |
| configure | `ConnectorSDK.connect(config)` | reject bad config early |
| authenticate | `_auth_headers` / provider token resolution | CredentialResolver supplies secrets |
| execute | `op_execute(operation, payload, context)` | dispatch per operation |
| normalize | `normalize_output(op, payload, raw)` override | shape provider data once |
| report | engine: events + trace + metrics | automatic |

## Rules

1. All outbound HTTP goes through `SafeHTTPClient`.
2. Typed errors only: `make_connector_error(ConnectorErrorCode.*, msg, retryable=…)`.
3. Declare `credential_require` + `secret_fields`; secrets never appear
   in traces/logs/exports.
4. Declare `idempotency` truthfully per operation (drives retries).
5. Version bumps: connector-level for behavior, operation-level for wire changes.
