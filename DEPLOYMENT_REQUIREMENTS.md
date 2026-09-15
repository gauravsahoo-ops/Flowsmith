# Flowsmith — Production Deployment Handover Specification

This document provides the complete infrastructure, security, networking, and deployment requirements for the IT / DevOps team to deploy **Flowsmith** to production.

---

## 1. System Overview & Architecture

Flowsmith is an enterprise workflow automation and orchestration platform packaged as containerized services:
* **App Service (`mat-app`)**: Multi-stage container hosting the FastAPI backend and bundled React single-page frontend on a single port (8000).
* **Worker Service (`mat-worker`)**: Dedicated asynchronous execution runner consuming background workflow execution jobs from the Redis queue.
* **Database (`mat-postgres`)**: PostgreSQL 16 with `pgvector` extension for relational data, execution traces, credentials, and vector embeddings.
* **Queue & Cache (`mat-redis`)**: Redis 7 for execution queuing, pub/sub, rate-limiting, and distributed locking.
* **Monitoring (`mat-prometheus` & `mat-grafana`)**: Optional telemetry and observability stack pre-configured with Flowsmith dashboards.

---

## 2. Infrastructure & Compute Sizing

| Sizing Tier | vCPU | RAM | Storage | Target Workload |
| :--- | :--- | :--- | :--- | :--- |
| **Minimum** | 2 vCPU | 4 GB | 20 GB SSD | Staging / Small Internal Deployments (<5 concurrent executions) |
| **Recommended (Prod)** | 4 vCPU | 8 GB | 50 GB NVMe | Active Production, Webhooks, Multi-tenant workloads |
| **High Throughput** | 8 vCPU | 16 GB | 100 GB+ NVMe | High-frequency polling, high-concurrency enterprise automations |

* **Host OS**: Ubuntu 22.04/24.04 LTS, Debian 12, RHEL 9, Rocky Linux, or Windows Server with Docker Desktop / WSL2.
* **Host Software Requirements**:
  * **Docker Engine** >= 24.0
  * **Docker Compose Plugin** >= 2.20

---

## 3. Network, Firewall & Port Specifications

| Port | Service | Scope / Accessibility | Notes |
| :--- | :--- | :--- | :--- |
| **80 / 443** | Reverse Proxy (Nginx / Caddy / Cloudflare / ALB) | **Public / Corporate LAN** | SSL/TLS termination, forwards to upstream port 8000 |
| **8000** | Flowsmith App (`mat-app`) | **Internal / Loopback (127.0.0.1)** | FastAPI + React UI + Webhook ingress |
| **5432** | PostgreSQL (`mat-postgres`) | **Private (Docker network only)** | Do **NOT** expose to public internet |
| **6379** | Redis (`mat-redis`) | **Private (Docker network only)** | Do **NOT** expose to public internet |
| **9090** | Prometheus *(optional)* | **Internal / VPN only** | Profile: `--profile monitoring` |
| **3000** | Grafana *(optional)* | **Internal / VPN only** | Profile: `--profile monitoring` |

---

## 4. Required Secrets & Environment Configuration (`.env.production`)

Create `.env.production` in the project root directory with the following variables. Do not commit `.env.production` to version control.

```bash
# ── Security Keys (MANDATORY) ────────────────────────────────────────────────
# 1. JWT signing key (64-char random URL-safe string):
#    Command: python3 -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=your_generated_jwt_secret_here

# 2. Fernet AES key for credential encryption at rest:
#    Command: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIALS_ENCRYPTION_KEY=your_generated_fernet_key_here

# 3. Database & Redis Passwords:
POSTGRES_PASSWORD=your_strong_db_password_here
REDIS_PASSWORD=your_strong_redis_password_here

# ── Application URLs ────────────────────────────────────────────────────────
PUBLIC_URL=https://flowsmith.yourdomain.com
APP_ENV=production
APP_PORT=8000

# ── CORS Settings (Strict origin, comma-separated, NO wildcards in prod) ────
CORS_ORIGINS=https://flowsmith.yourdomain.com

# ── Object Storage (Default: local filesystem, or S3/MinIO compatible) ──────
OBJECT_STORE_BACKEND=local
# For AWS S3 / Cloudflare R2 / MinIO:
# OBJECT_STORE_BACKEND=s3
# OBJECT_STORE_BUCKET=flowsmith-data
# OBJECT_STORE_ENDPOINT=
# OBJECT_STORE_REGION=us-east-1
# OBJECT_STORE_ACCESS_KEY=
# OBJECT_STORE_SECRET_KEY=

# ── Monitoring (Optional) ───────────────────────────────────────────────────
GRAFANA_USER=admin
GRAFANA_PASSWORD=your_grafana_password
```

---

## 5. Reverse Proxy Configuration (Nginx / Caddy)

> [!IMPORTANT]
> Flowsmith streams live node execution logs and trace outputs using **Server-Sent Events (SSE)**. The reverse proxy **must disable buffering** and support long-lived HTTP/1.1 connections.

### Nginx Configuration Template:
```nginx
server {
    listen 80;
    server_name flowsmith.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name flowsmith.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/flowsmith.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/flowsmith.yourdomain.com/privkey.pem;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Critical for Server-Sent Events (SSE) log streaming & WebSockets
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

### Caddy Configuration Template:
```caddy
flowsmith.yourdomain.com {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

---

## 6. Deployment Procedure

### Option A: Automated Script (Recommended)
On the target deployment server:
```bash
# 1. Clone or copy repository files to server
cd /opt/flowsmith

# 2. Ensure .env.production exists with secrets filled
cp .env.production .env.production.local # optional backup

# 3. Make deploy script executable and run
chmod +x deploy/setup.sh
./deploy/setup.sh

# To include Prometheus & Grafana monitoring:
./deploy/setup.sh --monitoring
```

### Option B: Direct Docker Compose
```bash
# Build and start all services in detached mode
docker compose --env-file .env.production up -d --build

# Or with monitoring profile:
docker compose --env-file .env.production --profile monitoring up -d --build
```

---

## 7. Verification & Healthcheck Endpoints

Verify platform readiness immediately after deployment:

| Endpoint | Method | Expected Output | Purpose |
| :--- | :--- | :--- | :--- |
| `/api/health` | `GET` | `{"status": "ok", ...}` | Basic container liveness |
| `/api/readyz` | `GET` | `{"data": {"status": "ready"}}` | Comprehensive readiness (Database, Redis, Disk) |
| `/api/metrics` | `GET` | Prometheus exposition text format | Application metrics for telemetry |

Example verification command:
```bash
curl -f https://flowsmith.yourdomain.com/api/readyz
```

---

## 8. Backup & Data Retention Strategy

The IT team must back up the following Docker named volumes:
1. **`mat-postgres-data`**: Contains all workflows, user accounts, encrypted credentials, execution history, and audit logs.
   * **Recommended Backup Strategy**: Daily scheduled `pg_dump` via cron:
     ```bash
     docker exec -t mat-postgres pg_dump -U automate automate | gzip > /backups/flowsmith_db_$(date +%F).sql.gz
     ```
2. **`mat-app-data`**: Contains locally stored binary files, execution artifacts, and attachments (`/app/backend/data`).
3. **`mat-redis-data`**: Persistent Redis queue state across container reboots.

---

## 9. Security & Hardening Checklist

- [ ] `JWT_SECRET` is generated randomly with at least 48-64 bytes of entropy.
- [ ] `CREDENTIALS_ENCRYPTION_KEY` is generated via `Fernet.generate_key()`.
- [ ] Database port `5432` and Redis port `6379` are bound to internal networks only, never exposed to public internet.
- [ ] `CORS_ORIGINS` is restricted to the specific frontend domain (`https://flowsmith.yourdomain.com`).
- [ ] Reverse proxy enforces HTTPS/TLS with modern cipher suites and HTTP-to-HTTPS redirection.
- [ ] Proxy buffering is disabled (`proxy_buffering off;`) to prevent truncated execution log streams.
