# Flowsmith

> Developed by **Gaurav** — designed, architected, and built from the ground up as an original work.

[![CI](https://github.com/gauravsahoo-ops/Flowsmith/actions/workflows/ci.yml/badge.svg)](https://github.com/gauravsahoo-ops/Flowsmith/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-1700%2B%20passing-brightgreen)](#testing)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Node](https://img.shields.io/badge/node-22-blue)](https://nodejs.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

**Flowsmith** is an enterprise-grade, self-hosted, open-source workflow automation platform designed to deliver n8n and Zapier-class automation with complete data sovereignty, zero per-run fees, and native enterprise integrations. It combines an interactive visual DAG canvas, sandboxed code execution, AI agents, RAG vector search, and 30 first-party connectors (including deep Salesforce OAuth2 CRM synchronization).

---

## Motto & Mission

> **"Orchestrate complex business logic with absolute visual clarity, enterprise-level security, and zero vendor lock-in."**

### Core Purpose & Target Audience
- **Target Audience**: DevOps engineers, enterprise backend developers, automation specialists, and IT teams requiring secure on-premise or private-cloud orchestration.
- **Problem It Solves**: Eliminates exorbitant per-task SaaS subscription fees (Zapier, Workato, Make) while avoiding the compliance risks of sending sensitive enterprise credentials and customer records to third-party clouds.
- **Enterprise Ready**: Full OAuth2 + PKCE support, Fernet-encrypted credential storage at rest, SSRF prevention, audit trails, and multi-tenant organization workspaces.

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [How to Use Flowsmith](#how-to-use-flowsmith)
- [Project Structure](#project-structure)
- [Built-in Node Types](#built-in-node-types)
- [Connectors](#connectors)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security](#security)
- [Monitoring](#monitoring)
- [CI/CD](#cicd)
- [Developed By](#developed-by)
- [License](#license)

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                Flowsmith Architecture                                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Frontend Client (React 19 + React Flow v12 + Zustand + Vite 8)             :5173 / :8000│
│  ├── Visual Canvas: Drag & drop node creation, fluid edge routing, auto-layout, undo/redo│
│  ├── Node Config Modal: Multi-tab editor (Input preview, Parameters, Output inspector) │
│  ├── Debugger Drawer: Execution timeline, per-step input/output payloads, retry actions│
│  └── Control Panels: Credentials, Environment Variables, Templates, Approvals, RAG    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Backend API & Orchestration (FastAPI + SQLAlchemy 2.0 + Pydantic v2)           :8000  │
│  ├── REST API: 30 modular routers with 160+ endpoints (OpenAPI / Swagger documentation)│
│  ├── Real-time Streams: WebSocket execution event broadcasting and log streaming       │
│  ├── Workflow Engine: Cycle detection, DAG topological resolution, branch merging      │
│  ├── Expression Evaluator: Sandboxed interpolation ({{ $json.* }}, $node, $cred, $env) │
│  ├── Sandboxed Code Runtimes: JavaScript (DukPy engine) & Python execution sandboxes   │
│  ├── Credential Vault: AES-128-CBC Fernet encryption with multi-key rotation keyring   │
│  ├── Native Connectors: 30 first-party connectors with OAuth2 PKCE flows               │
│  └── AI Subsystem: Natural-language workflow generator, error assistant, ReAct agents   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Distributed Execution & Asynchronous Worker                                           │
│  ├── Background Worker (`app.queue.worker`): Scalable background task runner           │
│  └── Dual Queue Backend: Native PostgreSQL transactional queue or high-throughput Redis│
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Data Layer & Infrastructure                                                           │
│  ├── PostgreSQL 16: Primary relational database + pgvector semantic vector search     │
│  ├── Redis 7 (Optional): High-speed event pub/sub and distributed caching              │
│  ├── MinIO (Optional): S3-compatible blob storage for file read/write operations       │
│  └── Prometheus & Grafana: Pre-configured metrics scrapers and monitoring dashboards   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Features

### 1. Robust Workflow DAG Engine
- **Topological Execution**: Nodes execute strictly based on dependency resolution.
- **Cycle & Graph Validation**: Automatic validation prevents infinite loops and deadlocks before saving.
- **Dynamic Expression Engine**: Reference any upstream node:
  - `{{ $json.fieldName }}` — current item payload
  - `{{ $('Node Name').item.json.field }}` — named upstream node output
  - `{{ $cred.apiKey }}` — secure credentials (never stored in plain text)
  - `{{ $env.VAR_NAME }}` — workspace-scoped environment variables
- **Branching & Merging**: True multi-parent branching, IF-conditions, multi-way Switch, and flexible Merge strategies.
- **Resilience & Fault Tolerance**: Per-node retry with exponential backoff, custom node timeouts, and cooperative execution cancellation.

### 2. Live Publishing & Lifecycle Control
- **Draft vs. Active**: Workflows start in `Draft` (Inactive) mode for risk-free editing.
- **1-Click Publishing**: Toggling **Active** immediately arms background triggers (cron schedules, public webhooks, Salesforce Outbound Messages).
- **Template Gallery**: Publish any custom workflow as a workspace template with one click.
- **Version History & Rollback**: Every save generates an immutable snapshot (`WorkflowVersionRecord`), allowing single-click rollback to any prior release.

### 3. Universal Token Management (`Token Manager`)
- **Unified Lifecycle Node**: Merges token retrieval, persistence, and auto-refresh into a single node (`token_manager`).
- **Native Dual Output Handles**:
  - `🟢 valid` (upper handle): Emits stored credentials directly to downstream steps, completely skipping the Login API when active.
  - `🟠 login` (lower handle): Emits to the Login API only on the initial run or when credentials are missing or expired.
- **Zero Redundant Logins**: Never invokes external authentication APIs if valid credentials already exist in the database.
- **Atomic Concurrency Protection**: PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) prevents concurrent execution stampedes during token refresh.
- **Auto-Extraction & Storage**: Automatically parses, normalizes, and AES-GCM encrypts tokens from upstream HTTP/Login responses into `WorkflowAuthState`.
- **Self-Healing 401 Recovery**: Downstream HTTP Request nodes automatically force-refresh expired tokens under lock and retry once with strict infinite-loop prevention.

### 4. Credential Auto-Reconnect & Background Renewal
- **Smart Reconnect**: `POST /api/credentials/{id}/reconnect` refreshes any OAuth credential from its stored refresh token (or Salesforce password flow) without interactive browser login; the UI falls back to OAuth only when background renewal is impossible.
- **Proactive Renewal Sweep**: A maintenance daemon re-checks expiring credentials every 10 minutes (bounded batches, `FOR UPDATE SKIP LOCKED` across replicas) and persists rotated tokens automatically.
- **Auto-Healing Probes**: `POST /api/credentials/{id}/test` refreshes an expired credential once and re-probes before reporting, so transient expiry never pages anyone.
- **Audited**: Every user-initiated reconnect logs `credential.reconnect`; sweeps write one throttled `credential.auto_refresh_sweep` summary row.

### 5. Native AI & RAG Subsystem
- **AI Chat & ReAct Agents**: Autonomous tool-calling loops executing web queries, database lookups, and API calls.
- **RAG Knowledge Base**: Ingest files, split into chunks, generate embeddings, and retrieve relevant context via `pgvector`.
- **Natural Language Workflow Generation**: Create complete multi-step automation workflows directly from plain English prompts.
- **AI Error Assistant**: Click "Explain Error" in the debugger to instantly diagnose stack traces and receive actionable remediation suggestions.

### 6. Interactive Debugger Drawer
- Slide-in side drawer directly within the canvas.
- Step-by-step visual timeline tracking execution duration, status, and failures.
- Raw JSON inspections of incoming and outgoing data for each individual node.
- Live rerun and manual retry capabilities without leaving the workflow view.

---

## Tech Stack

### Detailed Tech Stack Breakdown & Purpose

| Layer | Technology | Primary Purpose & Usage in Project |
|---|---|---|
| **Frontend Framework** | **React 19** | Reactive component architecture powering the responsive single-page web app. |
| **Canvas Engine** | **@xyflow/react (React Flow v12)** | Interactive node graph rendering, drag-and-drop wiring, custom ports, and auto-layout. |
| **State Management** | **Zustand** | Lightweight, reactive state stores for workflow graphs, execution feeds, credentials, and UI panels. |
| **Code Editor** | **Monaco Editor** | In-browser VS Code editing experience for JavaScript and Python `code` nodes. |
| **Frontend Build Tool** | **Vite 8** | High-performance build tool, ESM development server, and optimized production packager. |
| **Backend Framework** | **FastAPI (Python 3.12)** | Asynchronous, OpenAPI-compliant REST and WebSocket backend with automatic Swagger docs. |
| **Database ORM** | **SQLAlchemy 2.0** | Modern `mapped_column` type-safe object-relational mapping and database abstraction. |
| **Schema Validation** | **Pydantic v2** | High-speed data serialization, strict payload validation, and typed workflow contracts. |
| **Primary Database** | **PostgreSQL 16 + pgvector**| ACID-compliant transactional persistence + vector database for RAG document embeddings. |
| **Database Migrations**| **Alembic** | Automated version-controlled database schema evolution (12 revision scripts). |
| **Security & Cryptography** | **Cryptography (Fernet)** | AES-128-CBC encryption for customer credentials, tokens, and secrets at rest. |
| **Authentication** | **PyJWT + Passlib (PBKDF2)** | Stateless JSON Web Token authentication with secure salt password hashing. |
| **HTTP Client** | **HTTPX (Async)** | Non-blocking HTTP client powering the `http_request` node with custom SSRF security filters. |
| **Sandboxed Code Execution** | **DukPy** | Embedded JavaScript interpreter executing custom script transforms safely without node daemon overhead. |
| **Cron Scheduling** | **croniter** | Standard Unix 5-field cron parsing powering scheduled background automation triggers. |
| **Caching & Pub/Sub**| **Redis 7 (Optional)** | Low-latency job queue, real-time event distribution, and external message caching. |
| **Background Queue** | **Flowsmith Queue Worker** | Dedicated background daemon process (`app.queue.worker`) for parallel execution consumption. |
| **Testing Frameworks** | **Pytest + Vitest + Playwright** | 1700+ backend tests, 173 frontend unit tests, and 9 end-to-end browser specs. |
| **Monitoring** | **Prometheus + Grafana** | Built-in `/api/metrics` instrumentation endpoint and pre-packaged visual Grafana dashboard. |
| **Containerization** | **Docker & Docker Compose** | Multi-stage production container packaging (Node 22 + Python 3.12) with multi-service orchestrator. |

---

## Prerequisites

Before running Flowsmith locally or in production, ensure your machine has:

- **Python**: Version `3.12+` (with `pip` and `venv`)
- **Node.js**: Version `20.x` or `22.x+` (with `npm`)
- **Docker & Docker Compose**: (Required for PostgreSQL + pgvector, Redis, and MinIO)
- **Git**: Version `2.x+`

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/gauravsahoo-ops/Flowsmith.git
cd Flowsmith
```

### 2. Start Supporting Infrastructure (PostgreSQL & Redis)

```bash
docker compose up -d postgres redis
```
* PostgreSQL will start on `127.0.0.1:5432` (db: `automate`, user: `automate`, password: `automate`).
* Redis will start on `127.0.0.1:6379`.

### 3. Set Up & Start the Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # On Windows (PowerShell/CMD)
# source .venv/bin/activate  # On Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
copy .env.example .env       # On Windows
# cp .env.example .env       # On Linux/macOS

# Generate the two mandatory secrets and put them in backend/.env:
#   JWT_SECRET (e.g. openssl rand -hex 32)
#   CREDENTIALS_ENCRYPTION_KEY (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Apply database migrations
alembic upgrade head

# Start backend server
python -m app.serve
```
* The API and Swagger documentation will be live at: **http://127.0.0.1:8000/docs**
  (interactive docs are off by default — set `API_DOCS_ENABLED=true` in `backend/.env` to enable them).

### 4. Start the Background Worker (In a New Terminal)

```bash
cd backend
.venv\Scripts\activate       # On Windows
python -m app.queue.worker
```

### 5. Set Up & Start the Frontend (In a New Terminal)

```bash
cd frontend
npm install
npm run dev
```
* Open your browser and navigate to: **http://localhost:5173**

---

### Windows One-Click Quick Start

For Windows users, convenient batch scripts manage all services automatically:

```bash
start.bat      # Launches PostgreSQL, Redis, Backend, Worker, and Frontend
stop.bat       # Gracefully terminates all background services and processes
restart.bat    # Restarts all components cleanly
```

---

## How to Use Flowsmith

### Step 1: Account Creation & Login
- Navigate to `http://localhost:5173`.
- The first user to register automatically receives the **Admin** role with organization configuration privileges.

### Step 2: Create or Clone a Workflow
- **From Scratch**: Click **"+ New Workflow"** on the `/workflows` page to open a blank canvas.
- **From Templates**: Go to **"/templates"** and click **"Use template"** on pre-built flows (e.g. *Webhook to Slack & Teams Notification*, *Salesforce Lead Routing & Sync*, *Daily Scheduled Data Table Report*).

### Step 3: Design the Graph
- **Add Nodes**: Open the left sidebar node catalog and drag nodes onto the canvas, or press `Ctrl+K` to open the Command Palette.
- **Connect Ports**: Drag output handles to input handles to establish execution dependencies.
- **Configure Parameters**: Double-click any node to open the configuration modal. Use expressions like `{{ $json.field }}` or pick upstream fields using the visual expression helper.

### Step 4: Add Credentials
- Go to `/credentials` to register API keys, database connection strings, or initiate OAuth2 consent for Salesforce, Google, HubSpot, Slack, etc.
- Assign the credential to your node. Credentials are encrypted with Fernet and automatically injected at runtime.

### Step 5: Test & Debug
- Click **"Execute Workflow"** in the top bar to run a test execution.
- Click **"Debugger"** to open the side drawer, inspect live step runtimes, view full JSON inputs/outputs, or trigger a re-run.

### Step 6: Publish & Arm Triggers
- When satisfied with your workflow, toggle the switch in the top bar from **"Inactive"** to **"Active"**.
- Your webhook URLs, schedule timers, and external listeners are now armed and running live in production!

---

## Project Structure

```
Flowsmith/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI entry point & middleware stack
│   │   ├── serve.py            # Consolidated single-port production server (:8000)
│   │   ├── config.py           # Typed environment configurations (Pydantic Settings)
│   │   ├── db.py               # SQLAlchemy engine, session maker, connection pool
│   │   ├── runner.py           # In-process asynchronous task execution manager
│   │   ├── importexport.py     # Native & n8n workflow import/export converter
│   │   ├── api/                # 30 REST API modules (160+ endpoints)
│   │   │   ├── auth.py         # Login, register, JWT token refresh, password resets
│   │   │   ├── workflows.py    # Workflow CRUD, active toggling, imports/exports
│   │   │   ├── executions.py   # Execution history, traces, manual execution & retry
│   │   │   ├── credentials.py  # Credential management, type definitions, health checks
│   │   │   ├── environments.py # Workspace-level encrypted environment variables & templates
│   │   │   ├── salesforce.py   # Dedicated Salesforce OAuth2 & resource router
│   │   │   ├── ai.py           # Natural language generation, RAG, error explainers
│   │   │   ├── data_tables.py  # Native database tables (columns, rows, queries)
│   │   │   ├── webhooks.py     # Public unauthenticated webhook trigger endpoints
│   │   │   └── ws.py           # Real-time WebSocket execution log streams
│   │   ├── engine/             # Core workflow execution engine
│   │   │   ├── executor.py     # execute_workflow() DAG traversal algorithm
│   │   │   ├── graph.py        # Topological sorting, cycle detection, edge validation
│   │   │   ├── expressions.py  # Sandboxed {{ }} expression evaluation engine
│   │   │   └── node_base.py    # BaseNode, NodeContext, and NodeResult interfaces
│   │   ├── nodes/              # 50+ built-in node type implementations
│   │   ├── connectors/         # 30 first-party enterprise connectors (+ generated OpenAPI catalog)
│   │   ├── providers/          # Low-level external integration clients
│   │   ├── queue/              # Asynchronous job queue & worker processes
│   │   ├── models/             # 19 SQLAlchemy ORM model files (29 tables)
│   │   └── security/           # Safe HTTP clients, SSRF filters, Fernet encryption
│   ├── tests/                  # 1700+ automated backend pytest tests (664 API + engine/unit suites)
│   ├── alembic/                # Database migrations (schema evolution)
│   └── requirements.txt        # Backend dependencies
├── frontend/
│   ├── src/
│   │   ├── components/         # 70+ Modular React UI components
│   │   │   ├── Canvas.jsx      # Interactive React Flow workspace
│   │   │   ├── CustomNode.jsx  # Rich node renderer with badges & context menus
│   │   │   ├── TopBar.jsx      # Navigation, run trigger, debugger toggle, publish switch
│   │   │   ├── ExecutionInspector.jsx # Debugger drawer & timeline inspector
│   │   │   └── NodeEditorModal.jsx # Multi-tab node configuration modal
│   │   ├── pages/              # 19 Full application pages (Workflows, Templates, RAG, etc.)
│   │   ├── stores/             # Zustand state management (workflowStore, executionStore, etc.)
│   │   ├── api.js              # Comprehensive REST client with interceptors
│   │   └── index.css           # Modern dark-mode styling with glassmorphic tokens
│   ├── tests/                  # Frontend unit tests (Vitest) & E2E specs (Playwright)
│   ├── package.json            # Node.js dependencies and scripts
│   └── vite.config.js          # Vite configuration
├── deploy/                     # Production configs (Prometheus, Grafana, setup scripts)
├── docker-compose.yml          # Multi-container production deployment manifest
├── Dockerfile                  # Multi-stage container build definition
├── start.bat                   # Windows one-click startup automation
├── stop.bat                    # Windows one-click shutdown automation
└── restart.bat                 # Windows one-click restart automation
```

---

## Built-in Node Types

Flowsmith provides **50+ built-in node types** organized across functional domains:

| Category | Node Type | Description |
|---|---|---|
| **Triggers** | `manual_trigger` | Starts workflow via manual UI click or API trigger call. |
| | `webhook` | Public HTTP endpoint accepting incoming JSON payloads. |
| | `schedule` | Time-based execution via standard 5-field cron syntax. |
| | `salesforce_trigger` | Listens for Salesforce Outbound Messages and CDC events. |
| | `chat_trigger` | Starts a workflow from an incoming chat widget message. |
| | `form_trigger` | Starts a workflow from a public form submission. |
| **Actions** | `http_request` | Dispatches HTTP requests (GET, POST, PUT, PATCH, DELETE) with auth & headers. |
| | `token_manager` | Universal authentication lifecycle manager: checks DB for valid tokens, auto-refreshes expired credentials under lock, auto-stores new logins, and provides dual-handle branching (`valid` vs `login`). |
| | `set_data` | Transforms, reshapes, and maps JSON fields dynamically. |
| | `send_email` | Sends transactional emails via SMTP or cloud relays. |
| | `slack` | Posts rich Slack blocks and messages to channels. |
| | `telegram` | Sends notifications and markdown messages to Telegram chats. |
| | `graphql` | Executes GraphQL queries and mutations against external schemas. |
| | `database_query` | Executes direct parameterized SQL queries against relational databases. |
| | `email_read` | Reads messages from a mailbox (IMAP) for processing. |
| | `rss_feed` | Polls RSS/Atom feeds and emits new entries as items. |
| **Logic** | `if_condition` | Evaluates boolean expressions; routes items to `true` or `false` handles. |
| | `switch` | Multi-way branching based on discrete matching rules. |
| | `merge` | Recombines multiple branches with configurable wait and merge rules. |
| | `filter` | Drops items that do not meet defined predicate criteria. |
| **Control** | `split` | Splits arrays or batches into discrete parallel items. |
| | `aggregate` | Collates individual stream items into a single consolidated list. |
| | `loop` | Generic loop construct over collections. |
| | `loop_over_items` | Iterates over each element in an array sequentially. |
| | `loop_while` | Executes repeatedly until a boolean condition is satisfied. |
| | `pagination` | Automatically pages through cursor or page-based APIs. |
| | `wait` | Suspends execution for a specified duration or until a timestamp. |
| | `human_approval` | Pauses execution awaiting manual approval via the UI. |
| | `sub_workflow` | Invokes another workflow and resumes when completed. |
| | `execute_workflow_trigger` | Entry point for runs triggered by another workflow. |
| | `stop_and_error` | Aborts the execution immediately with a custom error. |
| | `noop` | Passes input items through unchanged (placeholder / wiring anchor). |
| **Data & Code** | `code` | Executes custom JavaScript (via DukPy) or Python script blocks. |
| | `data_table` | Interacts with native Flowsmith Data Tables (insert, update, query). |
| | `csv_json_transform` | Converts CSV rows to JSON structures and vice versa. |
| | `file_io` | Reads and writes files to local or object storage. |
| | `websocket` | Connects to real-time WebSocket endpoints. |
| | `compare_datasets` | Diffs two datasets and emits added/removed/changed items. |
| | `crypto_tools` | Hashing, HMAC signing/verification, and symmetric crypto helpers. |
| | `date_time` | Parses, formats, and computes with dates and timestamps. |
| | `html_extract` | Extracts structured fields from HTML documents. |
| | `item_lists` | Sorts, dedupes, limits, and reshapes item lists. |
| | `markdown_text` | Renders Markdown content to HTML or plain text. |
| | `xml_ops` | Parses XML documents and builds XML from JSON. |
| **AI & RAG** | `ai` | OpenAI-compatible chat model with custom tool-calling loop. |
| | `ai_agent` | Autonomous ReAct agent solving tasks with dynamically invoked tools. |
| | `rag_pipeline` | Semantic RAG: ingests, embeds, and queries document chunks via pgvector. |
| | `embeddings` | Generates vector embeddings for text via the configured provider. |
| | `memory` | Conversation memory buffer for AI agents across runs. |
| | `output_parser` | Parses raw LLM output into validated structured data. |
| | `text_splitter` | Splits documents into overlapping chunks for embedding. |

---

## Connectors

Flowsmith includes **30 first-party connectors** with pre-configured schemas and authentication handlers, plus an auto-generated OpenAPI catalog (weather, finance, placeholder APIs) for keyless public endpoints:

| Connector | Supported Operations & Resources | Authentication |
|---|---|---|
| **Salesforce** | 13 Resources (Account, Contact, Lead, Opportunity, Case, Task, CustomObject, Attachment, Document, User, Flow, Search, CustomApiCall) × full CRUD & SOQL | OAuth2 (PKCE) |
| **HubSpot** | Contacts, Companies, Deals, Tickets (search, get, create, update) | OAuth2 |
| **Google Calendar**| Events CRUD, attendee coordination, calendar lookups | OAuth2 |
| **Google Sheets** | Sheet values read, append row, update ranges, batch operations | OAuth2 |
| **Google Drive** | File upload, folder traversal, permissions, download | OAuth2 |
| **Gmail** | Send rich HTML/MIME emails, draft creation | OAuth2 |
| **PostgreSQL** | Direct raw SQL queries, transactions, parameterized execution | Connection String |
| **MySQL** | Direct raw SQL queries, batch inserts | Connection String |
| **MongoDB** | Collections CRUD, aggregation pipelines | Connection URI |
| **Redis** | Key get/set/delete, counters (incr), and channel publish | Connection URI |
| **Slack** | Channel messaging, ephemeral responses, user lookup | Bot Token |
| **MS Teams** | Channel messages, webhook web-alerts, adaptive cards | OAuth2 / Webhook |
| **Outlook** | Email dispatch, calendar schedule lookups | OAuth2 |
| **GitHub** | Repository stats, issue creation, pull request management | Personal Access Token |
| **GitLab** | Issues, merge requests, notes (list, get, create) | Personal Access Token |
| **Bitbucket** | Repositories, pull requests, comments | Access Token |
| **Linear** | Issues and comments (list, get, create, update) | API Key |
| **Notion** | Database queries, page creation, block manipulation | Internal Integration Token |
| **Jira** | Issue lifecycle CRUD, transition management | API Token |
| **Discord** | Webhook and bot channel notifications | Bot Token |
| **Stripe** | Customer creation, charge intents, subscription queries | API Secret Key |
| **Airtable** | Base record queries, row inserts, table updates | Personal Access Token |
| **Shopify** | Product management, customer lookup, order lifecycle | OAuth2 / Admin Token |
| **Asana** | Tasks and comments (list, get, create, update) | Personal Access Token |
| **Trello** | Boards, cards, and comments (list, get, create) | API Key + Token |
| **Calendly** | Event types and scheduled events (list, get, cancel) | Personal Access Token |
| **Zoom** | Meetings (list, get, create, delete) | Access Token |
| **Twilio** | SMS send, message history and lookup | Account SID / Auth Token |
| **WhatsApp** | Text and template messages via Meta Cloud API | Access Token |
| **ClickUp** | Lists, tasks, and comments (list, get, create, update) | API Token |

---

## API Reference

Flowsmith exposes a comprehensive RESTful API documented automatically with Swagger/OpenAPI at `http://127.0.0.1:8000/docs`.

### Authentication & Users
- `POST /api/auth/register` — Register a new account (first user becomes Admin)
- `POST /api/auth/login` — Authenticate and receive JWT access token
- `POST /api/auth/forgot-password` — Generate password reset token
- `POST /api/auth/reset-password` — Set new password with reset token
- `GET /api/auth/me` — Retrieve current authenticated profile

### Workflows
- `GET /api/workflows` — List workflows accessible to the user
- `POST /api/workflows` — Create a new workflow document
- `GET /api/workflows/{id}` — Fetch complete workflow definition and settings
- `PUT /api/workflows/{id}` — Save and snapshot updated workflow definition
- `DELETE /api/workflows/{id}` — Delete workflow
- `PATCH /api/workflows/{id}/active` — Toggle workflow active state (arms/disarms triggers)
- `GET /api/workflows/{id}/versions` — List immutable version snapshots
- `POST /api/workflows/{id}/rollback` — Rollback to a specific snapshot
- `GET /api/workflows/{id}/export` — Export workflow JSON
- `POST /api/workflows/import` — Import workflow (Flowsmith native or n8n JSON format)

### Executions & Live Traces
- `GET /api/executions` — List execution history with status and duration filters
- `POST /api/workflows/{id}/run` — Execute workflow manually
- `GET /api/executions/{id}` — Fetch detailed execution results per node
- `POST /api/executions/{id}/retry` — Retry a failed execution
- `POST /api/executions/{id}/cancel` — Cancel an in-flight execution
- `WS /api/ws/executions/{id}` — Real-time WebSocket execution event stream

### Credentials & Security
- `GET /api/credentials` — List user's encrypted credentials
- `POST /api/credentials` — Store credential (automatically encrypted with Fernet)
- `POST /api/credentials/{id}/test` — Verify credential connectivity (auto-refreshes expired OAuth tokens once and re-probes)
- `POST /api/credentials/{id}/reconnect` — Background token renewal without interactive login
- `DELETE /api/credentials/{id}` — Delete credential
- `GET /api/credentials/types` — Discover supported credential schemas (49 types)

### AI & Assistant
- `POST /api/ai/generate-workflow` — Generate full workflow from natural language
- `POST /api/ai/explain` — Explain execution error and recommend fixes
- `POST /api/ai/suggest-node-config` — Suggest node parameters from user prompt
- `GET /api/ai/status` — Check LLM provider availability

---

## Database Schema

Flowsmith stores relational metadata in **29 normalized PostgreSQL tables** managed by Alembic (12 revision scripts; verified by `backend/scripts/check_schema_parity.py`):

| Table Name | Description |
|---|---|
| `users` | User accounts, credentials, role authorizations, and timestamps. |
| `workflows` | Workflow definitions (JSON graph, version, active status, workspace). |
| `workflow_versions` | Immutable snapshots created on every workflow update. |
| `workflow_auth_state` | Encrypted authentication tokens, refresh tokens, and lifecycle cache per `(workflow_id, provider)`. |
| `executions` | High-level execution records (status, duration, error summary). |
| `execution_events` | Granular event audit stream (per-node input/output/error). |
| `credentials` | Fernet-encrypted customer secrets and OAuth tokens at rest. |
| `jobs` | Background task queue storage for distributed asynchronous workers. |
| `organizations` | Top-level tenant boundaries for enterprise multi-tenancy. |
| `organization_members`| User association and roles within an organization. |
| `workspaces` | Logical project environments within organizations. |
| `workspace_members` | Workspace-level permissions and access controls. |
| `workflow_shares` | Explicit read/write sharing permissions across users. |
| `subscriptions` | Stripe subscription and billing plan records. |
| `audit_events` | Immutable security log tracking all mutations and administrative actions. |
| `webhooks` | Registered public webhook trigger paths. |
| `schedule_triggers` | Cron schedule trigger rules and last-fired records. |
| `webhook_deliveries`| History of inbound webhook HTTP requests and payloads. |
| `oauth_states` | Temporary tokens safeguarding OAuth2 PKCE handshakes. |
| `password_reset_tokens`| Cryptographic tokens for secure password recovery. |
| `rag_collections` | Knowledge bases with vector embedding metadata. |
| `environments` | Workspace-scoped encrypted environment variables. |
| `user_api_keys` | Personal API access tokens for programmatic workflow invocation. |
| `workflow_templates`| Public and workspace template gallery entries. |
| `files` | Uploaded assets and local file metadata. |
| `workflow_tests` | Saved first-class workflow tests (mock rules, assertions, expected outputs). |
| `data_tables` / `data_table_columns` / `data_table_rows` | Embedded relational Data Tables allowing spreadsheet-like storage. |

---

## Testing

Flowsmith maintains a rigorous test suite spanning unit, integration, and security tests:

### Backend Testing (1700+ Tests)

```bash
cd backend

# Run the complete test suite
pytest -q

# Run fast unit tests (skip slow integration tests)
pytest -m "not timing" -q

# Test specific subsystems
pytest tests/test_api/test_token_manager.py -q    # Universal Token Manager & dual handles
pytest tests/test_api/test_workflows.py -q         # Workflow CRUD & active toggle
pytest tests/test_api/test_templates.py -q         # Template cloning & import
pytest tests/test_api/test_credential_auto_reconnect.py -q  # OAuth auto-reconnect & renewal sweep
pytest tests/test_security/ -q                     # SSRF, auth, and encryption audits
```

### Frontend Testing (173 Unit Tests & 9 E2E Specs)

```bash
cd frontend

# Run Vitest unit tests
npx vitest run

# Run Playwright end-to-end browser tests
npx playwright install chromium
npm test

# Run code linter
npm run lint

# Validate production build bundle
npm run build
```

---

## Deployment

### 1. Docker Compose (Full Production Stack)

Deploy the complete stack including Prometheus and Grafana with one command:

```bash
# Prepare production environment variables
copy .env.production .env

# Launch core services with monitoring profile
docker compose --profile monitoring up -d
```

| Service | Container Image | Port | Description |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | `5432` | Relational DB + vector search |
| `redis` | `redis:7-alpine` | `6379` | Cache and distributed job broker |
| `app` | `flowsmith:latest` | `8000` | FastAPI backend & single-port web server |
| `worker` | `flowsmith:latest` | — | Background queue worker |
| `minio` | `minio/minio` | `9000/9001` | Optional S3 object storage |
| `prometheus` | `prom/prometheus` | `9090` | Time-series metrics collection |
| `grafana` | `grafana/grafana` | `3000` | Pre-built monitoring dashboards |

### 2. Single-Port Embedded Deployment

For lightweight single-server deployments, Flowsmith can serve the built frontend SPA, API, and WebSockets through a single unified process on port `8000`:

```bash
# Build frontend static bundle
cd frontend && npm run build

# Start unified server
cd ../backend
python -m app.serve
```

---

## Security

Flowsmith is built from the ground up for strict enterprise environments:

- **Credential Encryption at Rest**: All external tokens, passwords, and private keys are encrypted using Fernet (AES-128-CBC) with HMAC-SHA256 integrity verification.
- **Multi-Key Keyring & Rotation**: Secrets support multi-key rotation with zero downtime via the credential keyring (`CREDENTIALS_ENCRYPTION_KEY` accepts a comma-separated key list with the newest key first).
- **SSRF Attack Mitigation**: The `SafeHTTPClient` inspects destination IPs and rejects queries to loopback, link-local, private LAN, or cloud metadata endpoints (`169.254.169.254`).
- **High-Entropy Trigger Validation**: Webhook endpoints enforce 24+ character high-entropy tokens to prevent brute-force discovery.
- **Sensitive Key Redaction**: Credentials and authorization headers are scrubbed from execution logs, error messages, and database traces before storage.
- **Production Secret Guard**: The application halts on startup if default insecure secrets are detected when `APP_ENV=production`.

---

## Monitoring

- **Prometheus Metrics**: Available out-of-the-box at `GET /api/metrics` (tracks execution durations, active workflows, queue depth, and HTTP error rates).
- **Health Probes**: 
  - `GET /api/health` — Liveness probe
  - `GET /api/readyz` — Readiness probe (validates database and worker connectivity)
- **Structured JSON Logging**: Set `LOG_FORMAT=json` for compatibility with Datadog, Grafana Loki, or ELK Stack.
- **Pre-packaged Grafana Dashboard**: Pre-built dashboard located at `deploy/grafana/dashboards/flowsmith.json`.

---

## CI/CD

Automated GitHub Actions pipelines validate every commit:

- **Continuous Integration (`ci.yml`)**: Executes Pyright static analysis, pytest test suites, schema-parity check (migrations == models), frontend Oxlint, Vite build, and Playwright E2E smoke tests.
- **PostgreSQL Integration (`ci-postgres.yml`)**: Runs full integration test matrices against live PostgreSQL 16 containers with the `pgvector` extension.
- **Nightly Performance Gate (`loadtest.yml`)**: Runs 100 concurrent workflow executions at 03:00 UTC, enforcing a strict $p95 \le 8\text{s}$ latency SLA.

---

## Developed By

**Flowsmith was designed, architected, and developed from scratch by Gaurav** ([gauravsahoo-ops](https://github.com/gauravsahoo-ops)) — every layer, from the visual DAG canvas and workflow execution engine to the OAuth framework, credential vault, AI subsystem, and deployment stack, is original work.

Please retain this attribution when self-hosting or redistributing, as required by the [MIT License](./LICENSE).

---

## License

Flowsmith is open-source software licensed under the [MIT License](./LICENSE).
