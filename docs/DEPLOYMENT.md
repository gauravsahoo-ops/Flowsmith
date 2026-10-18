# Flowsmith Enterprise Production Deployment & Hardening Guide

**Version:** 1.6.0 Enterprise  
**Target Environments:** Docker Compose, Kubernetes, AWS/GCP/Azure VPC, Air-Gapped Enterprise Private Cloud  
**Core Stack:** FastAPI, PostgreSQL 16 (pgvector), Redis 7 (AOF + noeviction), Prometheus, Grafana, Docker  
**Status:** Hardened, Empirically Audited, and SRE-Verified  

---

## 1. Production Architecture & Network Topologies

Flowsmith is designed for zero-trust, multi-tenant enterprise orchestration. All background workloads flow through a durable Redis queue with stateless execution workers.

```
                                  [ Ingress / TLS Reverse Proxy ]
                                    (Caddy / NGINX / Cloud ALB)
                                                 |
                                                 v :8000
                               +-----------------------------------+
                               |     Flowsmith Application Pod     |
                               |    (FastAPI + Vite Static UI)     |
                               |  - unprivileged appuser (UID 1000)|
                               |  - cap_drop: [ALL], no-new-priv   |
                               |  - memory: 1G, pre_ping pool: 10  |
                               +-----------------------------------+
                                       |                   |
                     (127.0.0.1:5432)  |                   |  (127.0.0.1:6379)
                                       v                   v
                     +-----------------------+   +-----------------------+
                     | PostgreSQL (pgvector) |   | Redis 7 Broker/Queue  |
                     | - mat-postgres-data   |   | - mat-redis-data      |
                     | - pgvector/pgvector   |   | - appendonly yes      |
                     | - memory: 1G          |   | - maxmemory-policy:   |
                     | - loopback/private net|   |     noeviction        |
                     +-----------------------+   +-----------------------+
                                       ^                   ^
                                       |                   |
                               +-----------------------------------+
                               |    Stateless Execution Workers    |
                               |  - python -m app.queue.worker     |
                               |  - Atomic LMOVE Claiming          |
                               |  - Heartbeat & Poison Reclaim     |
                               |  - Memory: 1G, cap_drop: [ALL]    |
                               +-----------------------------------+
```

### Network Isolation Invariants:
1. **Loopback-Only Infrastructure Binding:** PostgreSQL (`5432`), Redis (`6379`), Prometheus (`9090`), Grafana (`3000`), and MinIO (`9000/9001`) must bind strictly to `127.0.0.1` on the host, or remain purely internal to the Docker bridge network (`backend`).
2. **Reverse Proxy TLS Termination:** The application port (`8000`) should be fronted by a reverse proxy (e.g. Caddy, NGINX, Cloudflare, or AWS ALB) enforcing HTTPS and HTTP/2.
3. **No Wildcard CORS with Credentials:** In production (`APP_ENV=production`), `CORS_ORIGINS` must list explicit domains (e.g. `https://flowsmith.company.com`). Wildcards (`*`) are rejected at startup.

---

## 2. Hardware & Operating System Prerequisites

| Component | Staging / Small Team | Enterprise Production Baseline | High-Throughput Scale (10k+ execs/hr) |
| :--- | :--- | :--- | :--- |
| **CPU Architecture** | x86_64 / amd64 (4 vCPUs) | x86_64 / amd64 (8–16 vCPUs) | 16–32 vCPUs |
| **System Memory** | 8 GB RAM | 16–32 GB RAM | 64 GB+ RAM |
| **Storage Subsystem** | 50 GB SSD | 250 GB+ NVMe SSD | 1 TB+ High-IOPS NVMe |
| **Host OS** | Ubuntu 22.04 LTS / Debian 12 | Ubuntu 24.04 LTS / RHEL 9 | Enterprise Linux / CoreOS |
| **Container Engine** | Docker 24.0+ & Compose v2.20+ | Docker 26.0+ / Containerd | Kubernetes 1.28+ |

---

## 3. Production Environment Configuration (`.env.production`)

Never commit production secrets to version control. Set strict file permissions on `.env.production` (`umask 077` / `chmod 600`).

### Automated Secret Generation
Generate high-entropy production secrets using the built-in generator script:
```bash
python scripts/generate_production_secrets.py --env-file .env.production
```

### Environment Variable Reference

```ini
# ── Core Application & Environment ──────────────────────────────
APP_ENV=production
PUBLIC_URL=https://flowsmith.yourcompany.com
APP_PORT=8000
APP_BIND=127.0.0.1

# ── Secrets & Encryption (MANDATORY) ────────────────────────────
# Must be at least 32 characters with high entropy
JWT_SECRET=tGlqp8VDXiLsrvWX98iULhPVm97JptQiqAipyXvqC_O1E2mFxr20L24eXm36ADDo

# Fernet 32-byte urlsafe base64 key (supports comma-separated list for zero-downtime rotation)
CREDENTIALS_ENCRYPTION_KEY=cbyk9Uiqr72zhiphtiCXEZqJjZslvJxvvScXrcT2hek=

# ── Database (PostgreSQL 16 with pgvector) ──────────────────────
POSTGRES_USER=flowsmith_admin
POSTGRES_PASSWORD=vRoSA8YfQaUeFQAB_ffl3b4YZjTC7d0V
POSTGRES_PORT=5432
DATABASE_URL=postgresql://flowsmith_admin:vRoSA8YfQaUeFQAB_ffl3b4YZjTC7d0V@postgres:5432/automate

# ── Queue Broker (Redis 7) ──────────────────────────────────────
QUEUE_BACKEND=redis
REDIS_PASSWORD=S14c0jhSGDNhy77ktDuAC0PsJN-xW4ma
REDIS_PORT=6379
REDIS_URL=redis://redis:6379/0

# ── CORS & Security ─────────────────────────────────────────────
# Comma-separated list of allowed origins. Wildcard '*' is strictly blocked in production.
CORS_ORIGINS=https://flowsmith.yourcompany.com

# ── Monitoring & Observability (Optional) ───────────────────────
GRAFANA_USER=admin
GRAFANA_PASSWORD=SrK_Yh0AQN4TVL5f2hLiWjUzjhg
GRAFANA_PORT=3000
PROMETHEUS_PORT=9090

# ── Email Delivery (Password Reset & Error Alerts) ──────────────
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=noreply@yourcompany.com
SMTP_PASSWORD=your_smtp_app_password
MAIL_FROM="Flowsmith Platform <noreply@yourcompany.com>"
SMTP_USE_TLS=false
SMTP_STARTTLS=true
```

---

## 4. Quickstart Deployment Guide

### Step 1: Deploy with Hardened Setup Script
The automated deploy script enforces file permissions, secret validation, container healthchecks, and migration verification:
```bash
chmod +x deploy/setup.sh
./deploy/setup.sh --monitoring
```

Or deploy manually via Docker Compose:
```bash
docker compose --env-file .env.production -f docker-compose.yml up -d --build
```

### Step 2: Run Alembic Database Migrations
Migrations are idempotent and apply automatically during container bootstrap, or can be verified manually:
```bash
docker exec -it mat-app alembic upgrade head
```

### Step 3: Verify Health and Readiness
```bash
# 1. Liveness check
curl -fsS http://127.0.0.1:8000/api/health

# 2. Deep readiness check (verifies PostgreSQL and Redis connectivity)
curl -fsS http://127.0.0.1:8000/api/readyz
# Expected: {"data":{"status":"ready","checks":{"postgres":"ok","redis":"ok"}}}

# 3. Check container status
docker compose ps
```

---

## 5. Zero-Downtime Encryption Key Rotation

Flowsmith supports multi-key keyring rotation without taking the application offline:

```bash
# 1. Simulate key rotation (DRY-RUN mode)
python scripts/rotate_encryption_key.py

# 2. Apply key rotation (re-encrypts all credentials and secrets in PostgreSQL)
python scripts/rotate_encryption_key.py --apply

# 3. Prepend the newly generated key to CREDENTIALS_ENCRYPTION_KEY in .env.production:
# CREDENTIALS_ENCRYPTION_KEY=NEW_PRIMARY_KEY,OLD_SECONDARY_KEY

# 4. Perform rolling restart
docker compose restart app worker
```

---

## 6. PostgreSQL Backup & Disaster Recovery Procedures

Flowsmith features a streaming `pg_dump` and `psql` disaster recovery utility that never loads full database dumps into memory.

### Create Automated Backup
```bash
# Create compressed gzip backup (stored in backups/backup_YYYYMMDD_HHMMSS.sql.gz)
python scripts/backup_db.py backup --keep 14
```

### List Existing Backups
```bash
python scripts/backup_db.py list
```

### Disaster Recovery: Restore Database
```bash
# Clean restore over damaged or corrupted database:
python scripts/backup_db.py restore --file backups/test_p7_backup.sql.gz --fresh
```

### Database Migration Rollback Strategy
If a deployment fails during schema migration:
```bash
# Downgrade by 1 revision
docker exec -it mat-app alembic downgrade -1

# Or downgrade to specific revision
docker exec -it mat-app alembic downgrade <revision_id>
```

---

## 7. Monitoring, Alerts & Observability

Enable the monitoring profile with Prometheus and Grafana:
```bash
docker compose --profile monitoring up -d
```

- **Prometheus Scrape Endpoint:** `http://127.0.0.1:8000/api/metrics` (requires authenticated metrics service token).
- **Grafana Dashboard:** Accessible at `http://127.0.0.1:3000` with pre-provisioned panels:
  - **Request Rate:** `rate(http_requests_total[5m])`
  - **Latency Percentiles:** `p50`, `p95`, `p99` histograms
  - **Error Rate:** 4xx and 5xx traffic splits
  - **Workflows Total:** Real-time workflow count
  - **Rate-Limited Requests:** Throttling saturation metrics
- **Alert Thresholds:**
  - `ErrorRate5xx > 1%` over 5 minutes -> P2 Warning
  - `ErrorRate5xx > 5%` over 2 minutes -> P1 Critical
  - `ExecutionQueueWaitTime > 30s` -> Scale worker pool
  - `WorkerHeartbeatMissing > 60s` -> Worker pod crash recovery

---

## 8. SRE Maintenance & Incident Response Playbook

### Worker Crash Recovery
Workers are completely stateless. If a worker container crashes:
1. Docker automatically restarts the container (`restart: unless-stopped`).
2. The stale heartbeat sweeper runs every 30 seconds (`worker_stale_sweep_s = 30.0`). Any job claimed by a dead worker (> 60s without heartbeat) is automatically released back to the queue.
3. Poison jobs exceeding 10 failed claim attempts are marked as `FAILED` to prevent retry storms.

### Memory & Log Bounds
- Containers are capped at 1GB RAM to prevent OOM cascade.
- Docker log files are strictly rotated (`max-size: 50m - 100m`, `max-file: 3 - 10`) to prevent disk exhaustion.
