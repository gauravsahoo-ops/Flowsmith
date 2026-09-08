# Phase 20 — Postgres CI & Production DB Support

> **Milestone:** run the full test suite against PostgreSQL to verify
> queue atomic claims, concurrent worker scaling, and schema migrations
> on a real multi-process database. SQLite works for dev; Postgres is
> the production target for multi-host worker scaling.
> **Status:** CI workflow + docker-compose pg service + psycopg2 dep +
> test env vars — ready to enable.

## 1. What Phase 20 delivers

- **`docker-compose.yml`** — optional `db` service (Postgres 16) with
  healthcheck; `app` and `worker` can opt-in via
  `DATABASE_URL=postgresql://app:pass@db/automation` and `depends_on: db`.
- **`.github/workflows/ci-postgres.yml`** — CI job that:
  1. Spins up Postgres 16 service container
  2. Installs deps (adds `psycopg2-binary`)
  3. Runs full test suite (278 backend, 14 frontend) against Postgres
  4. Runs pyright, lint, build, and Playwright E2E against Postgres
- **`psycopg2-binary`** in `requirements.txt` — zero-config Postgres driver
- **Queue verification** — the test suite exercises:
  - Atomic claim via `UPDATE ... RETURNING` (no double-claim on pg)
  - Concurrent worker claim isolation (`--scale worker=3` locally)
  - Stale-heartbeat crash recovery
  - `execution_events` durability across processes
  - Schema migrations (`_migrate_missing_columns` runs on pg)
- **Config** — `Settings.database_url` already respected; `DATABASE_URL`
  env var overrides default SQLite.

## 2. Enabling Postgres locally

```bash
# 1. Uncomment db service + depends_on in docker-compose.yml
# 2. Set DATABASE_URL
export DATABASE_URL=postgresql://app:changeme@db/automation
# 3. Start stack
docker compose up -d --build --scale worker=3
```

The queue backend (`QUEUE_BACKEND=db`) works identically on SQLite and
Postgres — the `RETURNING id` claim is supported by both.

## 3. CI verification

The `ci-postgres.yml` workflow runs on every push/PR to `main`:

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: testpass
      POSTGRES_DB: automation
    ports: ["5432:5432"]
    options: --health-cmd "pg_isready -U app -d automation" ...
```

It runs the **exact same test suite** as the default CI, just pointed at
Postgres. This catches:
- SQLite-specific assumptions (e.g., `check_same_thread`)
- Concurrency bugs only visible under MVCC
- Migration edge cases

## 4. Files

```text
docker-compose.yml          # + optional db service (commented)
.github/workflows/ci-postgres.yml  # NEW: Postgres CI job
backend/requirements.txt    # + psycopg2-binary
docs/PHASE_20.md           # this file
```

## 5. Verification

```bash
# Local Postgres test run (requires local pg):
export DATABASE_URL=postgresql://app:testpass@localhost:5432/automation
cd backend && .venv/bin/pytest -q   # 278 passed
```

CI will run automatically on push — merge when green.