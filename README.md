# Flowsmith

Source-available iPaaS (Integration Platform as a Service) — design, run, and monitor automation workflows on a visual canvas, with 76 native connectors, 17 OpenAPI-generated connectors, a catalog of 435 reference integrations, an embedded AI agent runtime, and a hardened execution engine.

**Stack**: FastAPI · PostgreSQL (pgvector) · Redis · React (Vite) · Docker

## Features

- **Visual workflow canvas** — drag-and-drop nodes, branching, sub-workflows, versioned history.
- **Connectors** - 76 native, 17 OpenAPI-generated, and 435 catalog-only reference entries. Catalog-only entries require an explicit `endpoint_url`; see [Connector Status](docs/CONNECTOR_STATUS.md). Admins can install [connector packs](docs/CONNECTOR_PACKS.md) that bundle an OpenAPI connector with starter templates; remote manifests and registry indexes support Ed25519 signatures, pack dependencies are enforced, changes propagate across API/worker processes, and packs can be upgraded or uninstalled.
- **Triggers** - webhooks, GitHub/Stripe/Shopify/Slack/Typeform signed inbound presets, automatic provider registration for GitHub/GitLab/Stripe/Shopify/Typeform, generic HTTP polling, schedules (cron), forms, chat, Salesforce, SFTP, error workflows, manual runs, environment promotion (dev → staging → production).
- **Templates** - 330 built-in, importable workflows across CRM, support, DevOps, data, storage, AI, and communication.
- **AI agent runtime** — multi-provider LLM gateway (OpenAI, Anthropic, Gemini, Ollama, …), ReAct tool-loop, MCP support, multi-tier memory, RAG over pgvector.
- **Execution engine** — step traces, retries, streaming over WebSocket, durable event log, secret redaction in traces.
- **Platform** — SAML 2.0, OIDC and LDAP authentication, TOTP MFA with recovery codes, WebAuthn/passkeys, and organization MFA policy, SCIM 2.0 user and group provisioning, RBAC + shares, environments, encrypted credentials, audit log, rate limiting, backup/restore.

## Quick start (Docker)

```bash
cp .env.example .env       # then edit secrets — see below
docker compose up -d --build
```

- App: http://localhost:8000 (API + built frontend)
- **Required in `.env`**: `GRAFANA_USER` and `GRAFANA_PASSWORD` (compose refuses default
  admin/admin credentials — the example file ships placeholders you must change).
- For local/production secrets set `JWT_SECRET` and `CREDENTIALS_ENCRYPTION_KEY` in `backend/.env`
  (production boot fails without them; see `docs/DEPLOYMENT.md`).
- Optional profiles: `--profile monitoring` (Prometheus + Grafana on loopback),
  `--profile s3` (MinIO).

Windows one-click: double-click `start.bat` (stop with `stop.bat`).

## Kubernetes (Helm)

A production-oriented chart is in `deploy/helm/flowsmith`. It includes the
API/UI, external workers, a migration hook, optional pgvector PostgreSQL and
Redis, ingress, HPA, and a PodDisruptionBudget.

```bash
helm upgrade --install flowsmith deploy/helm/flowsmith \
  --namespace flowsmith --create-namespace \
  --set secrets.jwtSecret="$(openssl rand -hex 32)" \
  --set secrets.credentialsEncryptionKey="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --set postgresql.password="$(openssl rand -hex 24)" \
  --set redis.password="$(openssl rand -hex 24)" \
  --set config.publicUrl="https://flowsmith.example.com"
```

For production, use a private values file or an existing Kubernetes Secret
(`secrets.create=false`, `secrets.existingSecret`) instead of command-line
secrets. See `deploy/helm/flowsmith/README.md` for external PostgreSQL/Redis,
scaling, and upgrade guidance.

## Local development

Backend (Python 3.12+, from `backend/`):

```bash
pip install -r requirements.txt
alembic upgrade head        # create/update schema
python -m app.serve         # API on :8000
```

Frontend (Node 20+, from `frontend/`):

```bash
npm install
npm run dev                 # Vite dev server on :5173 (proxies /api to :8000)
```

## Testing & quality

| Check | Command |
| :--- | :--- |
| Backend tests | `cd backend && pytest -q -m "not timing"` |
| Backend lint | `cd backend && ruff check app` |
| Backend types | `cd backend && pyright` |
| Schema parity (migrations == models) | `cd backend && python scripts/check_schema_parity.py` |
| Connector status (native/generated/catalog-only) | `cd backend && python scripts/connector_status.py` |
| Frontend unit tests | `cd frontend && npx vitest run` |
| Frontend lint | `cd frontend && npm run lint` (oxlint) |
| E2E tests | `cd frontend && npx playwright test` |

CI (`.github/workflows/ci.yml`) runs all of the above. It requires these repository
secrets: `CI_JWT_SECRET` and `CI_CREDENTIALS_ENCRYPTION_KEY`.

## Project structure

```
backend/            FastAPI app (app/api, app/engine, app/nodes, app/ai, …)
  alembic/          DB migrations
  scripts/          schema parity check, maintenance utilities
  tests/            pytest suites
frontend/           React app (src/components, src/stores, src/api, …)
deploy/             Helm chart, Prometheus + Grafana provisioning
docs/               Architecture, API, security, deployment guides
docker-compose.yml  app + worker + postgres + redis (+ optional profiles)
Jenkinsfile         staging rsync deploy
.github/workflows/  CI (lint, tests, parity, e2e, docker)
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [API guide](docs/API_GUIDE.md) · [Execution engine](docs/EXECUTION_ENGINE.md)
- [Deployment](docs/DEPLOYMENT.md) · [Database](docs/DATABASE_GUIDE.md) · [Security model](docs/SECURITY_MODEL.md) · [SAML](docs/SAML.md) · [SCIM](docs/SCIM.md), [MFA](docs/MFA.md), [WebAuthn](docs/WEBAUTHN.md), [LDAP](docs/LDAP.md), [Triggers](docs/TRIGGERS.md) · [Templates](docs/TEMPLATES.md) · [Connector Packs](docs/CONNECTOR_PACKS.md) · [Benchmark](docs/BENCHMARK.md)
- [User manual](USER_MANUAL.md) · [Changelog](CHANGELOG.md) · [Audit findings](PRODUCT_AUDIT.md)

## License

Business Source License 1.1 — see [LICENSE](LICENSE).
