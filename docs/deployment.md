# Deployment guide

One image serves the whole product: built UI, REST API, public
webhooks and the live WebSocket stream (`python -m app.serve`) — plus
a **queue worker** that executes jobs (Phase 15). In the Docker stack
the API only enqueues; `worker` runs the jobs.

## 1. Quick start (Docker)

```bash
# one-time image build
docker compose build

# generate secrets and export them
export JWT_SECRET=$(openssl rand -hex 32)
export CREDENTIALS_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export PUBLIC_URL=https://automate.example.com

docker compose up -d
curl -s http://127.0.0.1:8000/api/health
```

Secrets are passed straight through (`JWT_SECRET` /
`CREDENTIALS_ENCRYPTION_KEY`). The stack runs **PostgreSQL** (`postgres`)
and **Redis** (`redis`) plus `app` and `worker` services; the API only
enqueues, workers execute. Database files live in the `mat-app-data`
volume (shared by `app` and `worker`); backups must be taken separately
(below).

The container stack runs with `APP_ENV=production`, and the **app
refuses to start** if the encryption key is missing, `JWT_SECRET` is
empty or the dev default, or `DATABASE_URL` is not PostgreSQL — a
missing secret surfaces as a clear boot-time error from `app`/`worker`,
never a silent misconfiguration. (Optional connectors like Salesforce
may stay unconfigured.) Infrastructure alone needs no secrets:
`docker compose up -d postgres redis`.

## 1a. Local Postgres + Redis validation (no full stack)

To run the live integration suites against real PostgreSQL and Redis
(the `tests/integration/` tests skip automatically when the services are
down):

```bash
docker compose up -d postgres redis
cd backend && .venv/bin/pytest tests/integration -q
# postgres_live: DDL + model CRUD, Fernet credential round-trip,
#                full engine execution on Postgres
# redis_queue_live: atomic LMOVE claim, heartbeat, stale recovery
```

## 1b. Queue workers

Runs flow through the job queue (Phase 15): the API creates the
`jobs` row and a **worker** claims it, executes and persists the
outcome.

- **Two worker modes:**
  - `QUEUE_EMBEDDED_CONSUMER=true` (dev default) — a consumer runs
    inside the API process; zero extra moving parts.
  - `QUEUE_EMBEDDED_CONSUMER=false` — the API only enqueues; external
    workers execute. This is what `docker-compose.yml` sets.
- **Scaling** — workers are stateless; add replicas freely:

  ```bash
  docker compose up -d --scale worker=3
  ```

  Claims are atomic (`UPDATE … RETURNING id` on the `jobs` table), so
  each job runs exactly once no matter how many workers compete.
- **Worker failures** — each claim is heartbeated; a claim whose
  heartbeat goes stale (default 60s) is re-queued by any worker's idle
  sweep, so a crashed worker's job continues elsewhere. `jobs.attempts`
  records how many times a job was claimed. Job-level timeouts are the
  workflow's business (`timeout_seconds`), never the worker's.
- **Queue backend** — default is the shared database (`QUEUE_BACKEND=
  db`, zero infra). For many replicas across hosts, either share
  PostgreSQL (`DATABASE_URL`) or switch to `QUEUE_BACKEND=redis` +
  `REDIS_URL` (Redis lists). With Postgres/Redis, workers can be
  separate machines / process managers.
- **Systemd (bare metal)** — each worker is its own unit:

  ```ini
  [Service]
  WorkingDirectory=/opt/my-automation-tool/backend
  ExecStart=/opt/my-automation-tool/backend/.venv/bin/python -m app.queue.worker
  EnvironmentFile=/etc/automate.env
  User=automate
  Restart=on-failure
  ```

  Run one unit per core if you want concurrency (or `--scale worker=N`
  on Docker).

## 2. Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `JWT_SECRET` | dev-only | signs auth tokens — **required in production** |
| `CREDENTIALS_ENCRYPTION_KEY` | derived from JWT_SECRET | Fernet key; **set it** so stored credentials survive a secret rotation |
| `PUBLIC_URL` | `""` | advertised by `GET /api/health` for external tooling |
| `CORS_ORIGINS` | `*` | comma-separated allowed origins |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | bind address/port for `app.serve` |
| `SERVE_FRONTEND` | `true` | serve the built UI from the same port |
| `FRONTEND_DIST` | `../frontend/dist` (image default `/app/frontend/dist`) | where the built UI lives |
| `DATABASE_URL` | `postgresql://automate:automate@localhost:5432/automate` | SQLAlchemy URL (PostgreSQL required in production) |
| `APP_ENV` | `development` | `production` enables the fail-fast config guard (2c) |
| `QUEUE_EMBEDDED_CONSUMER` | `true` | `false` → the API only enqueues; external `python -m app.queue.worker` processes execute (see 1b) |
| `QUEUE_BACKEND` | `db` | `db` (jobs table) or `redis` (+ `REDIS_URL`) |
| `REDIS_URL` | `""` | Redis URL when `QUEUE_BACKEND=redis` |

`.env.example` in `backend/` documents these for bare-metal runs.

### 2a. Secrets checklist (before first deployment)

- [ ] `JWT_SECRET` is a fresh random value (`openssl rand -hex 32`).
- [ ] `CREDENTIALS_ENCRYPTION_KEY` is a fresh Fernet key:
      `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
      Without it the app derives a key from `JWT_SECRET` (dev fallback,
      logged as a warning) — **never run production on the fallback**.
- [ ] If the dev fallback was ever in effect, rotate to a real key (below);
      otherwise every future `JWT_SECRET` rotation would silently change the
      encryption key and orphan stored credentials.
- [ ] The key (and a copy of the DB backup) is stored outside the app host;
      **losing the key means losing all stored credentials** (they cannot
      be decrypted).
- [ ] No real secrets in tracked files — `backend/.env` is git-ignored;
      verify with `git ls-files | findstr .env` and `git grep <secret>`.

### 2c. Production config guard

With `APP_ENV=production` the app **refuses to start** unless
`CREDENTIALS_ENCRYPTION_KEY` is set, `JWT_SECRET` is not the dev
default, and `DATABASE_URL` points at PostgreSQL. This turns the
secrets checklist above into a hard startup requirement instead of a
hope. Development (`APP_ENV=development`, the default) keeps the
convenient fallbacks (derived encryption key, SQLite).

### 2b. Credential key rotation

Stored credentials are Fernet tokens that record which key encrypted
them (`k0:` prefix), so keys can be rolled without re-entering any
credential:

```
1. Prepend the NEW key to CREDENTIALS_ENCRYPTION_KEY (comma-separated,
   new key first).
2. Run:  python -m app.scripts.rotate_credentials
         (re-encrypts every stored credential with the new first key)
3. Remove the OLD key from CREDENTIALS_ENCRYPTION_KEY and restart.
```

Verify after rotating: log in and run one workflow per credential type
before discarding the old key. See `app/security/crypto.py` for the
keyring format.

## 3. HTTPS

Terminate TLS in front with a reverse proxy; the app stays plain HTTP
behind it. Example with Caddy (automatic HTTPS):

```
automate.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Point `PUBLIC_URL` at the public `https://` origin. The UI reads
webhook URLs from `window.location.origin`, so no other change is
needed. WebSockets are proxied automatically (Caddy/nginx handle the
`Upgrade` headers for `/api/ws/*`).

## 4. Bare metal (no Docker)

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ../frontend && npm ci && npm run build && cd ../backend

# env: JWT_SECRET, CREDENTIALS_ENCRYPTION_KEY, PUBLIC_URL (see .env.example)
.venv/bin/python -m app.serve
```

systemd unit (`/etc/systemd/system/automate.service`):

```ini
[Unit]
Description=Automation tool
After=network.target

[Service]
WorkingDirectory=/opt/my-automation-tool/backend
ExecStart=/opt/my-automation-tool/backend/.venv/bin/python -m app.serve
EnvironmentFile=/etc/automate.env
User=automate
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## 5. Backups & restore

PostgreSQL is backed up using `pg_dump`:

```bash
# Backup
docker compose exec -T postgres pg_dump -U automate automate > backup.sql

# Restore
docker compose exec -T postgres psql -U automate automate < backup.sql
```

For production, schedule regular backups via cron:

```
0 2 * * * cd /opt/my-automation-tool && docker compose exec -T postgres pg_dump -U automate automate > backups/automate-$(date +\%Y\%m\%d-\%H\%M\%S).sql
```

Keep the last 7 copies. Backups should be stored outside the app host; losing the backup means losing all stored data (credentials, workflows, audit logs).

## 6. Upgrades

The app auto-migrates the schema on startup (adds missing tables and
columns), so upgrades are:

```bash
docker compose pull    # or: docker compose build
docker compose up -d
```

1. Back up first (section 5).
2. Deploy, then check `docker compose ps` (healthy) and `/api/health`.
3. Keep the previous image/volume around for an instant rollback.

## 7. Health checks & monitoring

- `GET /api/health` — liveness + version + public_url (used by the
  compose healthcheck and load balancers).
- Container logs carry uvicorn access logs and `logger` output
  (`api.executions`, `queue.worker`, `engine`, `db`); workers log
  claim/complete/recovery lines under `queue.worker`.
- The compose healthcheck fails after 5 failed checks in ~50s; the
  container restarts automatically (`restart: unless-stopped`).

## Schema & load acceptance (Phase 35)

- **Schema parity**: `cd backend && python scripts/check_schema_parity.py`
  builds the schema twice (alembic upgrade head vs create_all) into
  scratch databases and diffs tables/columns. Run it after every model
  change; release-blocking when it reports drift.
- **Load acceptance**: with a stack running (`python -m app.serve`),
  `python scripts/loadtest.py --iterations 100 --concurrency 10`
  drives real workflow runs end-to-end and gates on error rate and p95
  latency. Defaults are calibrated for one embedded consumer (~2 runs/s;
  latency at concurrency is queue-depth dominated). Scale workers
  (`docker compose up -d --scale worker=4`) and/or tighten thresholds to
  match your topology.
