# Flowsmith Enterprise Deployment Requirements & Specifications

**Document Version:** 1.0.0-Enterprise  
**Last Updated:** October 2026  
**Target Platform:** Flowsmith iPaaS & Autonomous Automation Platform  
**Target Environments:** Bare-Metal Linux, Cloud VMs (AWS EC2 / GCP Compute Engine / Azure VMs), Docker Compose, Kubernetes  

---

## 1. Executive Overview

Flowsmith is an enterprise-grade, self-hosted workflow automation, integration platform (iPaaS), and autonomous AI orchestration engine. The system is designed for high-throughput, low-latency execution with absolute data sovereignty.

This specification details the minimum, recommended, and enterprise-scale production requirements across hardware, networking, container runtimes, security configurations, database topologies, and operational disaster-recovery standards.

---

## 2. Hardware & Sizing Architecture Matrix

The platform is decomposed into stateless API gateways, distributed background queue workers, in-memory caching/messaging, and persistent relational/vector storage. Resource allocation scales with monthly execution volumes.

| Resource Dimension | Small / Pilot (<50,000 runs/mo) | Standard Production (50k – 500k runs/mo) | High-Scale Enterprise (>500k runs/mo) |
| :--- | :--- | :--- | :--- |
| **Compute (vCPUs)** | 4 vCPUs (2.4 GHz+) | 8 – 16 vCPUs | 32+ vCPUs (Distributed Cluster) |
| **System Memory (RAM)**| 8 GB | 16 – 32 GB | 64 – 128 GB |
| **Storage Capacity** | 50 GB SSD | 200 – 500 GB NVMe | 1 TB+ Enterprise NVMe (RAID-10) |
| **Storage IOPS** | 1,500 IOPS | 5,000+ IOPS | 15,000+ Provisioned IOPS |
| **Network Throughput** | 1 Gbps NIC | 2.5 – 5 Gbps NIC | 10 Gbps Redundant NICs |
| **API Server Replicas** | 1 instance | 2 instances (Load-balanced) | 4+ instances behind ALB / Traefik |
| **Queue Worker Replicas** | 1 worker | 2 – 4 workers | 8 – 16 autoscaled workers |
| **Recommended Cloud SKU** | AWS `t4g.xlarge` / GCP `e2-standard-4` | AWS `c7g.2xlarge` / GCP `c3-standard-8` | AWS `c7g.4xlarge` / GCP `c3-standard-16` |

---

## 3. Operating System & Base Software Prerequisites

### 3.1 Supported Operating Systems
- **Linux (Recommended):**
  - Ubuntu Server 22.04 LTS or 24.04 LTS (`amd64` / `arm64`)
  - Red Hat Enterprise Linux (RHEL) 9.x / Rocky Linux 9.x
  - Debian 12 ("Bookworm")
- **Windows Server (Development / Hybrid Staging):**
  - Windows Server 2022 / Windows 11 Enterprise with WSL2 & Docker Desktop

### 3.2 Core Container & Runtime Engines
- **Docker Engine:** Version `24.0.0` or higher (Version `26.0+` recommended)
- **Docker Compose:** Version `v2.20.0` or higher
- **Alternative Orchestration:** Kubernetes `1.28+` / OpenShift `4.14+`
- **Host Time Sync:** NTP (`chrony` or `systemd-timesyncd`) synchronized within 50ms (critical for OAuth2 token validation and cron triggers).

### 3.3 Database & Storage Subsystems
- **Relational & Vector Database:**
  - **PostgreSQL 16.x** (Mandatory)
  - **`pgvector` Extension:** Version `0.7.0+` installed and enabled in database (`CREATE EXTENSION IF NOT EXISTS vector;`)
  - **Database Driver:** `psycopg[binary]>=3.2,<4` (Psycopg 3 native)
- **Queue & Cache Subsystem:**
  - **Redis 7.2+** with AOF persistence or snapshotting (`maxmemory-policy: allkeys-lru`)
- **Object Storage (File Uploads & Binary Artifacts):**
  - **Default:** Local filesystem storage mounted to persistent volumes (`/app/backend/data/objects`)
  - **Enterprise S3-Compatible:** AWS S3, Cloudflare R2, MinIO, or Google Cloud Storage

---

## 4. Network, Firewall & Port Specifications

### 4.1 Ingress Ports (External Traffic)
| Port | Protocol | Source | Destination | Purpose |
| :---: | :---: | :---: | :---: | :--- |
| **443** | TCP / HTTPS | Public Internet / Corporate WAN | Reverse Proxy (Caddy / NGINX) | Secure web UI, REST API, Webhook ingestion, SSE streaming |
| **80** | TCP / HTTP | Public Internet / Corporate WAN | Reverse Proxy | Automated ACME Let's Encrypt challenge & HTTP-to-HTTPS redirect |

### 4.2 Internal Cluster Ports (Must NOT be exposed publicly)
| Port | Protocol | Binding | Purpose | Security Rule |
| :---: | :---: | :---: | :---: | :--- |
| **8000** | TCP / HTTP | `127.0.0.1` / Docker Network | FastAPI Backend Application | Reverse proxy upstream only |
| **5432** | TCP | `127.0.0.1` / Docker Network | PostgreSQL 16 (pgvector) | Block external access; bind to private subnet |
| **6379** | TCP | `127.0.0.1` / Docker Network | Redis 7 (Broker & Cache) | Require password authentication; private network only |
| **11434**| TCP | `127.0.0.1` / Host Localhost | Ollama Local LLM (Optional) | Internal API access only for zero-egress neural inference |

### 4.3 Egress Firewall Requirements (Outbound Connections)
The execution worker and API processes must be allowed outbound TCP access on:
- **Port 443 (HTTPS):** Outbound REST/GraphQL APIs for registered SaaS connectors (Salesforce, Stripe, GitHub, HubSpot, Slack, Google Workspace, AWS, etc.).
- **Port 587 / 465 (SMTP):** Outbound email dispatch for notification and password reset nodes.
- **SSRF Hardening & Private Network Protection:**
  - By default, Flowsmith enforces Server-Side Request Forgery (SSRF) guards blocking requests targeting loopback (`127.0.0.1`, `localhost`) and link-local cloud metadata addresses (`169.254.169.254`).
  - Internal subnet access can be explicitly whitelisted using `SAFE_HTTP_ALLOWED_HOSTS` and `SAFE_HTTP_ALLOWED_PORTS`.

---

## 5. Production Environment Variables & Security Secrets

In production mode (`APP_ENV=production`), Flowsmith executes mandatory fail-fast startup checks. The server will **refuse to boot** if development defaults or insecure configurations are detected.

### 5.1 Mandatory Security Settings
```ini
# Operating Mode
APP_ENV=production

# Application Base URLs
PUBLIC_URL=https://flowsmith.yourdomain.com
HOST=0.0.0.0
PORT=8000

# CORS Whitelist (STRICT: Wildcard '*' is strictly prohibited in production)
CORS_ORIGINS=https://flowsmith.yourdomain.com

# Cryptographic Keys (Must be generated via cryptographically secure random generators)
# 1. JWT Session Signing Key:
# Generation: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=YOUR_GENERATED_64_CHAR_HEX_OR_URLSAFE_STRING

# 2. Field-Level AES-256-GCM Envelope Encryption Key:
# Generation: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CREDENTIALS_ENCRYPTION_KEY=YOUR_GENERATED_32_BYTE_BASE64_KEY

# PostgreSQL Connection (Psycopg 3 native)
DATABASE_URL=postgresql+psycopg://automate:SECURE_DB_PASSWORD@postgres:5432/automate
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_PRE_PING=true

# Redis Connection
REDIS_URL=redis://:SECURE_REDIS_PASSWORD@redis:6379/0
REDIS_PASSWORD=SECURE_REDIS_PASSWORD

# Distributed Queue Settings
QUEUE_BACKEND=redis
QUEUE_EMBEDDED_CONSUMER=false
```

### 5.2 Storage & File Artifact Configuration
```ini
# Local or S3
OBJECT_STORE_BACKEND=local
OBJECT_STORE_LOCAL_PATH=/app/backend/data/objects

# If S3-compatible backend is used:
# OBJECT_STORE_BACKEND=s3
# OBJECT_STORE_BUCKET=flowsmith-production-artifacts
# OBJECT_STORE_REGION=us-east-1
# OBJECT_STORE_ACCESS_KEY=AKIA...
# OBJECT_STORE_SECRET_KEY=...
```

### 5.3 High-Entropy Webhook & API Security
- **Entropy Floor:** Webhook trigger endpoints require path tokens of at least 24 random characters (e.g. `hook-a1b2c3d4e5f67890abcdef123456`).
- **Signature Verification:** Outbound and inbound webhooks support HMAC-SHA256 (Stripe, GitHub) with replay drift verification windows (300 seconds).

---

## 6. High Availability & Distributed Worker Architecture

Flowsmith is decoupled into stateless web frontends and stateful worker queues:

```
                          [ Public Internet / Webhooks ]
                                        │
                                        ▼ (HTTPS :443)
                         [ Reverse Proxy (Caddy / NGINX) ]
                                        │
                   ┌────────────────────┴────────────────────┐
                   ▼ (Port 8000)                             ▼ (Port 8000)
        [ API Gateway Replica 1 ]                 [ API Gateway Replica 2 ]
                   │                                         │
                   └────────────────────┬────────────────────┘
                                        ▼
                         [ Redis 7 Cluster / Queue ]
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
    [ Worker Pod 1 ]           [ Worker Pod 2 ]           [ Worker Pod N ]
             │                          │                          │
             └──────────────────────────┴──────────────────────────┘
                                        │
                                        ▼ (Port 5432)
                       [ PostgreSQL 16 (Primary + pgvector) ]
```

### Scaling Rules
1. **API Instances (`app.serve`):** Stateless; horizontally scalable behind round-robin load balancers.
2. **Worker Instances (`app.queue.worker`):** Stateless task consumers; scale dynamically based on Redis queue depth (`LLEN queue:jobs`).
3. **Queue Deduplication & Heartbeats:** Workers maintain a 15-second heartbeat per running job. If a worker pod crashes, the master scheduler reclaims stale jobs within 60 seconds without data loss.

---

## 7. Disaster Recovery, Backups & Business Continuity

Flowsmith features automated database snapshotting and disaster recovery verification ([backend/app/dr/](file:///c:/Flowsmith/backend/app/dr/)):

- **Recovery Time Objective (RTO):** Measured at **< 3.0 seconds** (validated empirically at **2.44s** in staging drills).
- **Recovery Point Objective (RPO):** Defined by backup cron frequency (recommended: 1-hour incremental, 24-hour full).
- **Backup Command:**
  ```bash
  python backend/scripts/dr_drill.py
  ```
- **Backup Encryption Rule:** Backups contain encrypted credential rows. To restore onto a new server, the identical `CREDENTIALS_ENCRYPTION_KEY` must be configured in `.env.production`.

---

## 8. Pre-Flight Production Readiness Checklist

Before publishing DNS records or opening traffic to production users, verify each step:

- [ ] **1. Clean Python Environment:** Python 3.12 with `psycopg[binary]>=3.2,<4` installed from `requirements-lock.txt`.
- [ ] **2. Database Schema Migrations:** Alembic migrations applied to head (`alembic upgrade head`).
- [ ] **3. Schema Parity Audit:** Run `python backend/scripts/check_schema_parity.py` (Must report 32/32 tables in parity).
- [ ] **4. Core Test Suite:** Run `pytest backend/tests/test_vectorstores backend/tests/test_queue` (Must report 100% pass).
- [ ] **5. Production Settings Validation:** Verify `validate_production_settings()` passes without `ConfigError`.
- [ ] **6. No Wildcard CORS:** Ensure `CORS_ORIGINS` contains only trusted explicit domain origins.
- [ ] **7. Frontend Assets Built:** Verify `frontend/dist/index.html` exists and was compiled via `npm run build`.
- [ ] **8. TLS/SSL Termination:** Valid HTTPS certificate active with TLS 1.2 / 1.3 enforced.
- [ ] **9. Memory Limits Configured:** Container memory limits assigned in `docker-compose.yml` (Postgres: 1GB+, Redis: 512MB+, App: 1GB+).
- [ ] **10. Disaster Recovery Drill Tested:** Run `python backend/scripts/dr_drill.py` to confirm backup dump and restore cycle.
- [ ] **11. Queue Isolation:** Dedicated Redis DB index assigned for production (`/0`), keeping test runs isolated (`/14`, `/15`).
- [ ] **12. Health Endpoints Verified:**
  - `GET /api/health` returns HTTP 200 with `"database": "ok"`.
  - `GET /api/readyz` returns HTTP 200 with `"status": "ready"`.
