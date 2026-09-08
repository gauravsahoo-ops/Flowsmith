# Phase 11 — Data retention + webhook hardening

> **Milestone:** finish M9's "pruning" (unbounded execution rows) and
> spec 32's delivery guarantees (idempotency keys, outcome tracking).
> **Status:** done — `tests/test_maintenance.py` (5 tests) + webhook
> trigger suite (15 tests) green; full suite 216 passed.

## 1. What Phase 11 delivers

```text
PRUNING:  MaintenanceDaemon (hourly→daily tick, in-process)
            │  prune(db, before)
            ▼
      finished executions older than execution_retention_days (30)
      → deleted along with their webhook delivery records
      running/cancelling executions are NEVER touched

WEBHOOKS (spec 32):
  POST /api/webhooks/{path} + Idempotency-Key: k
      ├─ existing delivery with (path, k)? → return it (replayed: true),
      │                                       no second execution
      └─ else: queue execution, store idempotency_key on the delivery
  delivery.status tracks the run: queued → success | failed | cancelled
```

- **`app/maintenance.py`**: `prune(db, before, dry_run=)` — selects
  finished (`!= running/cancelling`) executions older than `before`,
  deletes them and the `webhook_deliveries` rows pointing at them;
  returns `{executions, deliveries, running_kept}`. A daemon (~24h
  default; `maintenance_prune_interval_hours`) runs it on the worker
  loop, same pattern as the scheduler.
- **Config**: `execution_retention_days` (default 30) and
  `maintenance_prune_interval_hours` (default 24).
- **Admin API** (`app/api/admin.py`): `POST /api/admin/maintenance/prune`
  — admin-only (403 otherwise), `{days, dry_run}` body; `dry_run=true`
  (the default) previews counts without deleting; a real prune writes an
  `admin.prune` audit event with the counts. Wrapped in the standard
  `ok()` envelope.
- **Webhook idempotency** (`api/webhooks.py`): optional
  `Idempotency-Key` header; a repeat hit with the same `(path, key)`
  returns the original `delivery_id`/`execution_id` with
  `replayed: true` and queues **nothing**. The key is stored on the
  delivery (`WebhookDelivery.idempotency_key`, auto-migrated onto
  existing DB files by `_migrate_missing_columns`).
- **Delivery outcome tracking** (`api/executions.py::_mark_deliveries`):
  when an execution finishes — success, failure, cancellation or a
  worker crash — matching deliveries advance from `queued` to the
  execution's status, so the delivery log reflects reality.

## 2. Why it took the shape it did (bug found on the way)

1. **The first prune never deleted anything** — the delivery-delete
  step used the *execution* ids as `WebhookDelivery.id` values (a
  select of `Execution.id, Execution.trigger` fed both deletes), so the
  `IN (...)` clause matched no delivery rows. The counts even looked
  right (`n_deliveries += len(delivery_ids)`), which is why a dedicated
  fresh-session probe was needed: `prune` must resolve delivery ids via
  `WebhookDelivery.execution_id IN (webhook execution ids)`.
2. **Identity-map masking in tests** — after a delete, the *same*
  session's `get()` still returned the row (`expire_on_commit=False`);
  assertions now always use a fresh session.
3. **Non-admin previews must be blocked too** — the endpoint checks the
  role *before* dry-run, so the admin-only surface is enforced.
4. **Endpoints must use the `ok()` envelope** — the first version
  returned a bare dict; the frontend unwraps `{data, meta}`, so a
  KeyError in tests caught it.

## 3. Files

```text
backend/app/
├── maintenance.py           # prune() + MaintenanceDaemon
├── api/admin.py             # POST /api/admin/maintenance/prune
├── api/webhooks.py          # Idempotency-Key handling
├── api/executions.py        # _mark_deliveries on finish/crash
├── models/webhook.py        # WebhookDelivery.idempotency_key
├── config.py                # retention + interval settings
├── audit.py                 # ADMIN_PRUNE event
└── main.py                  # admin router + daemon startup

backend/tests/
├── test_maintenance.py              # prune windows, dry-run, admin API+
│                                    #   audit, member 403
└── test_api/test_webhook_trigger.py # replay on same key, separate runs
                                     #   for distinct keys, delivery status
```

## 4. Verification

- `pytest tests/test_maintenance.py tests/test_api/test_webhook_trigger.py`
  — 15 passed (5 new maintenance + 2 new idempotency/delivery tests).
- Full suite 216 passed (was 210), pyright clean.
- Behaviours proven: old finished runs (and their deliveries) are gone
  after a real prune; running runs survive; dry-run removes nothing; two
  hits with the same key produce one delivery + one execution, distinct
  keys produce two of each; a finished webhook run's delivery reads
  `status="success"`.