# Phase 2 — Node Library Expansion (M2)

> **Milestone:** 8 built-in nodes, adding webhook trigger, schedule
> trigger, send email (SMTP), and database query to the M1 set.
> **Status:** 73 tests passing, pyright 0 errors.

## 1. What Phase 2 delivers

The node library grows from 4 (M1) to 8 types. Four new nodes cover the
two "trigger" primitives and the two most common actions in the spec
(§7 node list): outgoing email and SQL.

```text
triggers:  manual_trigger, webhook, schedule
actions:   http_request, set_data, if_condition, send_email, database_query
```

## 2. New nodes

### webhook
- Params: `path` (regex `^[a-zA-Z0-9_-]+$`), `method` (GET/POST/PUT/PATCH/DELETE), `respond_with`.
- Payload is normalized to `{"body", "headers", "query", "params"}` per item.
- A raw JSON array body is expanded into one output item per element.
- HTTP endpoint registration arrives in M7 (API layer); the node defines the contract.

### schedule
- Params: `cron` expression, optional `timezone` (default UTC) and `limit`.
- Cron validated with `croniter` at param-validation time; timezone with `zoneinfo`.
- Outputs one item per scheduled fire: `{"timestamp": iso8601}`.
- Note: requires the `tzdata` package on Windows (no system tz database).
- The actual scheduler/daemon arrives in M7; the node declares the contract.

### send_email
- Params: `to`, `subject`, `body` (all `{{ }}`-aware), optional `from_address`, plain-text only for now.
- Uses `smtplib` in a worker thread (`asyncio.to_thread`); SMTP_SSL and STARTTLS both supported.
- Credentials (`host`, `port`, `username`, `password`, `starttls`) come from the `smtp` credential type (engine injects at execution; M6 wires the real store).
- Errors: missing credential -> `CREDENTIALS_REQUIRED` (permanent); SMTP failure -> `SMTP_ERROR` (retryable).

### database_query
- Params: `sql`, optional `params` (bound parameters via SQLAlchemy `text()`).
- Connection string comes from the `database` credential (`dsn`), so no driver is hard-coded.
- SELECT-like statements -> one output item per row; others -> `{"affected_rows": n}`.
- Errors: missing credential -> `CREDENTIALS_REQUIRED`; connection loss (invalidated connection, "unable to open", refused, reset, timeout, gone away, etc.) -> `DB_CONNECTION_ERROR` (retryable); everything else -> `SQL_ERROR` (permanent).

## 3. SDK additions

- `NodeContext` gained a `credentials: dict` parameter (empty in M2; the executor fills it from the credentials store in M6).
- `DatabaseQueryNode` and `SendEmailNode` declare `credential_types` for the future API to expose.
- All nodes self-register via `@register`; `list_nodes()` now returns 8 entries with JSON schemas.

## 4. Verification

```text
73 passed (engine 44 + new node tests 29)
pyright: 0 errors, 0 warnings
```

## 5. Known limitations (deferred deliberately)

- Webhook endpoint + schedule daemon come with the API server (M7).
- Email HTML bodies, attachments, and OAuth/SMTP bundles later.
- Credential management UI + secure storage is M6.