# Flowsmith

Open-source iPaaS (Integration Platform as a Service) — design, run, and monitor automation workflows on a visual canvas, with 100+ connectors, an embedded AI agent runtime, and a hardened execution engine.

**Stack**: FastAPI · PostgreSQL (pgvector) · Redis · React (Vite) · Docker

## Features

- **Visual workflow canvas** — drag-and-drop nodes, branching, sub-workflows, versioned history.
- **200+ connectors** — HTTP, databases, Salesforce, Slack, HubSpot, Google, Microsoft, and more, with an OpenAPI connector factory.
- **Triggers** — webhooks, schedules (cron), manual runs, environment promotion (dev → staging → production).
- **AI agent runtime** — multi-provider LLM gateway (OpenAI, Anthropic, Gemini, Ollama, …), ReAct tool-loop, MCP support, multi-tier memory, RAG over pgvector.
- **Execution engine** — step traces, retries, streaming over WebSocket, durable event log, secret redaction in traces.
- **Platform** — SSO/OAuth, RBAC + shares, environments, encrypted credentials, audit log, rate limiting, backup/restore.

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
deploy/             Prometheus + Grafana provisioning
docs/               Architecture, API, security, deployment guides
docker-compose.yml  app + worker + postgres + redis (+ optional profiles)
Jenkinsfile         staging rsync deploy
.github/workflows/  CI (lint, tests, parity, e2e, docker)
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [API guide](docs/API_GUIDE.md) · [Execution engine](docs/EXECUTION_ENGINE.md)
- [Deployment](docs/DEPLOYMENT.md) · [Database](docs/DATABASE_GUIDE.md) · [Security model](docs/SECURITY_MODEL.md)
- [User manual](USER_MANUAL.md) · [Changelog](CHANGELOG.md) · [Audit findings](PRODUCT_AUDIT.md)

## License

Business Source License 1.1 — see [LICENSE](LICENSE).
