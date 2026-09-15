# Flowsmith — IT & DevOps Handover Package

This folder contains all configuration files, deployment scripts, environment templates, and architecture specifications required by the IT / DevOps team to deploy Flowsmith to production.

---

## Contents of This Package

| File / Folder | Purpose |
| :--- | :--- |
| **`DEPLOYMENT_REQUIREMENTS.md`** | **Master Handover Document** detailing hardware sizing, networking/ports, secrets, Nginx/Caddy reverse proxy configs, backups, and security checklists. |
| **`docker-compose.yml`** | Production Docker Compose orchestration for all core services (`app`, `worker`, `postgres` with pgvector, `redis`) and optional profiles (`monitoring` for Prometheus + Grafana, `s3` for MinIO). |
| **`Dockerfile`** | Multi-stage production container build (compiles the Vite/React frontend and packages the FastAPI backend into a single lean container). |
| **`.dockerignore`** | Build context exclusion rules to keep Docker images fast and lightweight. |
| **`.env.production`** | Production environment variable template (must be configured with production secrets and domain URLs). |
| **`deploy/setup.sh`** | Automated deployment bash script that validates dependencies, auto-generates missing cryptographic keys if needed, and performs healthchecks. |
| **`deploy/prometheus.yml`** | Prometheus metrics scraping configuration targeting `/api/metrics`. |
| **`deploy/grafana/`** | Pre-provisioned Grafana datasources and dashboard JSON (`flowsmith.json`). |

---

## Quick Start for IT / DevOps

### 1. Configure Environment Secrets
Copy `.env.production` and provide production secrets:
```bash
# Generate a secure JWT secret:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Generate a Fernet AES key for credential encryption:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Fill in `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and `PUBLIC_URL` / `CORS_ORIGINS`.

### 2. Deploy

#### Option A: Automated Script (Recommended)
```bash
chmod +x deploy/setup.sh
./deploy/setup.sh

# Or with Prometheus and Grafana monitoring:
./deploy/setup.sh --monitoring
```

#### Option B: Direct Docker Compose
```bash
docker compose --env-file .env.production up -d --build
```

### 3. Verify Health
- **Liveness:** `curl -f http://localhost:8000/api/health`
- **Readiness:** `curl -f http://localhost:8000/api/readyz`

For full details regarding Nginx reverse proxy buffering (required for SSE streaming), SSL termination, backup scripts, and hardware sizing, refer to **`DEPLOYMENT_REQUIREMENTS.md`**.
