# Connector SDK — universal contract

Salesforce is the reference implementation. Adding a connector = copying
`backend/app/connectors/_template/`, renaming symbols, implementing
stages, registering. **No core-engine modifications are ever required**
(enforced by `tests/test_api/test_connector_template.py`).

## Runtime lifecycle stages

| # | Stage | Where it lives |
|---|-------|----------------|
| 1 | discover | `ConnectorDefinitionV1` + ConnectorRegistry → `GET /api/connectors` |
| 2 | validate | `validate_workflow_payload` (draft) + activation gate |
| 3 | configure | `ConnectorSDK.connect(config)` |
| 4 | authenticate | CredentialResolver secrets → provider token machinery (`BaseProviderClient`) |
| 5 | execute | `ConnectorSDK.op_execute(operation, payload, context)` |
| 6 | normalize | `ConnectorSDK.normalize_output(op, payload, raw)` (override) |
| 7 | report | engine: events, trace steps, metrics (automatic) |

## Required pieces per connector

1. **ConnectorDefinitionV1** — key, version, lifecycle status,
   operations, triggers, credential types.
2. **CredentialTypeV1** (+ entry in `app.credentials.registry`) —
   validation schema for the UI form; `secret_fields` never logged.
3. **OperationDefinitionV1** ×N — JSON-schema input/output, legal
   idempotency (`idempotent|non_idempotent`), retryable flag.
4. **TriggerDefinitionV1** — only if the connector owns triggers.
5. **ProviderClient** — extend `providers/base.BaseProviderClient`
   (token cache, one-shot 401 refresh, status→error taxonomy) or match
   Salesforce's own implementation.
6. **Connector** class extending `ConnectorSDK` with `op_execute`.
7. **Tests** — OAuth flow (if any), provider unit via patched
   SafeHTTPClient seam, full-stack workflow run, secret-leak assertion,
   discovery inclusion.

## Hard rules

- Outbound HTTP **only** through `SafeHTTPClient`.
- Typed errors only via `make_connector_error(ConnectorErrorCode.*, …)`;
  retryability must reflect operation semantics.
- Secrets live in encrypted credentials; never in node params, traces,
  logs or exports.
- Idempotency declarations drive engine retries — declare truthfully.
