# Flowsmith

> **Designed, architected, and engineered from the ground up by [Gaurav](https://github.com/gauravsahoo-ops) as an original work.**

[![CI](https://github.com/gauravsahoo-ops/Flowsmith/actions/workflows/ci.yml/badge.svg)](https://github.com/gauravsahoo-ops/Flowsmith/actions/workflows/ci.yml)
[![Backend Tests](https://img.shields.io/badge/backend%20tests-1800%2B%20passing-brightgreen)](#backend-testing-1800-tests)
[![Frontend Tests](https://img.shields.io/badge/frontend%20tests-324%20passing-brightgreen)](#frontend-testing-324-vitest-tests--e2e-specs)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.115-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/react-19-61dafb)](https://react.dev/)
[![Vite](https://img.shields.io/badge/vite-8-646cff)](https://vitejs.dev/)
[![License](https://img.shields.io/badge/license-BSL--1.1-blue)](./LICENSE)

**Flowsmith** is an enterprise-grade, self-hosted, source-available workflow automation and orchestration suite engineered for complete data sovereignty, zero per-run fees, and deep enterprise integrations. It combines a state-of-the-art interactive visual DAG canvas, sandboxed code execution, autonomous AI agents, RAG vector retrieval, native relational Data Tables, an AES-256-GCM v2 encrypted credential vault, and 86 registered enterprise connectors across 8 categories governed by an authoritative 5-tier certification state machine (including deep Salesforce and Dynamics 365 OAuth2 CRM synchronization with seamless single-click zero-config reconnection).

---

## Motto & Mission

> **"Orchestrate complex business logic with absolute visual clarity, enterprise-grade security, and zero vendor lock-in."**

### Core Purpose & Target Audience
- **Target Audience**: DevOps engineers, enterprise architects, backend developers, automation specialists, and IT teams requiring secure on-premise or private-cloud orchestration.
- **Problem It Solves**: Eliminates exorbitant per-task SaaS subscription fees and execution quotas while eliminating compliance risks associated with transmitting sensitive enterprise credentials and customer records to third-party multi-tenant clouds.
- **Enterprise Grade**: Full OAuth2 + PKCE support, 100% Fernet (AES-128-CBC) and AES-256-GCM encrypted credential vault at rest, SSRF prevention, multi-tenant organization workspaces, immutable audit logging, and custom white-label branding.

---

## Table of Contents

- [Super-Premium UI/UX & Mobile Experience](#super-premium-uiux--mobile-experience)
- [Architecture](#architecture)
- [Key Features](#key-features)
  - [1. Robust Visual Workflow DAG Engine](#1-robust-visual-workflow-dag-engine)
  - [2. Live Publishing & Lifecycle Control](#2-live-publishing--lifecycle-control)
  - [3. Frictionless OAuth & Single-Click Reconnect (Zero-Config)](#3-frictionless-oauth--single-click-reconnect-zero-config)
  - [4. Universal Token Management (`Token Manager`)](#4-universal-token-management-token-manager)
  - [5. 100% Encrypted Credential Vault at Rest](#5-100-encrypted-credential-vault-at-rest)
  - [6. Native AI & RAG Subsystem](#6-native-ai--rag-subsystem)
  - [7. Embedded Relational Data Tables](#7-embedded-relational-data-tables)
  - [8. Human-in-the-Loop & Interactive Approvals](#8-human-in-the-loop--interactive-approvals)
  - [9. Complete White-Labeling & Client Custom Branding](#9-complete-white-labeling--client-custom-branding)
  - [10. Data Pinning & Mocking Engine](#10-data-pinning--mocking-engine)
  - [11. Model Context Protocol (MCP) AI Server](#11-model-context-protocol-mcp-ai-server)
  - [12. OpenAPI Importer & Custom Connector Engine](#12-openapi-importer--custom-connector-engine)
  - [13. Single-Node Execution ("Test Step") & Context-Aware Debugging](#13-single-node-execution-test-step--context-aware-debugging)
  - [14. High-Performance Architecture & Route Code-Splitting](#14-high-performance-architecture--route-code-splitting)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [User Manual (Beginner's Guide)](./USER_MANUAL.md)
- [Competitive Capability Matrix (Flowsmith vs Zapier vs n8n vs Cyclr)](./docs/COMPETITIVE_CAPABILITY_MATRIX.md)
- [How to Use Flowsmith](#how-to-use-flowsmith)
- [Project Structure](#project-structure)
- [Built-in Node Types](#built-in-node-types)
- [First-Party Connectors](#first-party-connectors)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security & Compliance](#security--compliance)
- [Monitoring & Telemetry](#monitoring--telemetry)
- [CI/CD](#cicd)
- [Developed By](#developed-by)
- [License](#license)

---

## Super-Premium UI/UX & Mobile Experience

Flowsmith is designed from the ground up to provide a frictionless, world-class developer experience across both desktop and mobile viewports:

- **Frosted Glassmorphism Design System**: Tailored dark-mode palette (`#0b0e14` background with radial luminescence) layered with multi-tier frosted glass surfaces (`backdrop-filter: blur(20px)`), luminous 1px top-highlight borders, and deep ambient drop shadows.
- **Interactive Login & Auth Showcase**: Ambient background glowing orbs with breathing animations, an interactive live pipeline preview displaying real-time execution stats (`14ms`, `AES-128 Fernet`, `Async SSE`), show/hide password toggle, and SSO connectivity.
- **Fluid Micro-Animations**: Smooth card hover lifts (`translateY(-3px)`), button shimmer states, and pulsing live indicators (`● Active`, `● Encrypted`, `● Success`).
- **Tactile Visual Canvas**: 78px beveled glass node cards with category-colored glows (Triggers: Amber, Connectors: Blue, Logic: Indigo/Purple, AI: Cyan), custom input/output port handles, and instant node context menus.
- **Clamped 3-Panel Node Editor Modal**: Precision centered modal with safe viewport containment (`max-width: 1480px; max-height: 920px`) and 16px overlay padding, preventing edge clipping and guaranteeing persistent visibility of modal action controls (`✨ AI Auto-Repair`, `▶ Previous`, `▶ Execute Step`, and `✕ Close`).
- **Responsive Panel Switcher**: Below `1150px`, the 3-panel layout automatically adapts into clean single-panel tab views (`Input`, `Parameters`, `Output`) with real-time status badges, allowing comfortable node editing on laptops, tablets, and split-screen windows without content squishing.
- **Full DAG Ancestor Inspection**: The Input Panel traverses the execution graph backwards, presenting upstream ancestor outputs as collapsible cards with auto-expanded direct parents, schema/table/JSON views, visual expression copy helpers, and zero-overlap card accordions.
- **Full Android & iOS Mobile Optimization**:
  - **Safe-Area Insets**: Seamless layout alignment around iPhone notches and Dynamic Island (`env(safe-area-inset-top)` / `env(safe-area-inset-bottom)`).
  - **iOS Safari Auto-Zoom Fix**: All form inputs maintain `16px` font size on mobile screens to eliminate disruptive auto-zoom behavior.
  - **Canvas Touch Controls**: Multi-touch canvas panning (`panOnDrag={[1, 2]}`) and pinch-to-zoom (`zoomOnPinch={true}`).
  - **Fluid Responsive Layouts**: Non-wrapping headers, collapsible sidebars with explicit mobile dismiss triggers (`✕`), and horizontally scrollable data tables.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                Flowsmith Architecture                                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Frontend Client (React 19 + React Flow v12 + Zustand + Vite 8)             :5173 / :8000│
│  ├── Visual Canvas: Drag & drop node creation, fluid edge routing, auto-layout, undo/redo│
│  ├── Node Editor Modal: 3-panel inspector (Inputs preview, Parameters, Output inspector)│
│  ├── Single-Click Reconnect: Zero-config popup pre-opening (immune to browser blockers)│
│  ├── Debugger Drawer: Execution timeline, per-step input/output payloads, retry actions│
│  ├── Control Panels: Credentials, Environment Variables, Templates, Approvals, RAG    │
│  └── Client Customization: White-labeling engine, logo upload, color presets, CSS theme │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Backend API & Orchestration (FastAPI + SQLAlchemy 2.0 + Pydantic v2)           :8000  │
│  ├── REST API: 30 modular routers with 170+ endpoints (OpenAPI / Swagger documentation)│
│  ├── Real-time Streams: WebSocket execution event broadcasting and log streaming       │
│  ├── Workflow Engine: Cycle detection, DAG topological resolution, branch merging      │
│  ├── Expression Evaluator: Sandboxed interpolation ({{ $json.* }}, $node, $cred, $env) │
│  ├── Sandboxed Code Runtimes: JavaScript (DukPy engine) & Python execution sandboxes   │
│  ├── Credential Vault: AES-256-GCM v2 & Fernet encryption with multi-key rotation      │
│  ├── Native Connectors: 86 registered connectors with OAuth2 PKCE & 5-tier certification│
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

## Key Features

### 1. Robust Visual Workflow DAG Engine
- **Topological Execution**: Nodes execute strictly based on dependency resolution.
- **Cycle & Graph Validation**: Automatic validation prevents infinite loops and deadlocks before saving.
- **Dynamic Expression Engine**: Reference any upstream node:
  - `{{ $json.fieldName }}` — current item payload
  - `{{ $('Node Name').item.json.field }}` — named upstream node output
  - `{{ $cred.apiKey }}` — secure credentials (never stored in plain text)
  - `{{ $env.VAR_NAME }}` — workspace-scoped environment variables
- **Branching & Merging**: Multi-parent branching, IF-conditions, multi-way Switch, and flexible Merge strategies.
- **Resilience & Fault Tolerance**: Per-node retry with exponential backoff, custom node timeouts, and cooperative execution cancellation.
- **Global Error Workflows**: Bind an automated error handler (`on_error_workflow_id`). The dedicated **Error Trigger** receives structured failure context (`error`, `failed_execution_id`, `failed_workflow_id`) to orchestrate incident alerts across Slack, email, or PagerDuty.

### 2. Live Publishing & Lifecycle Control
- **Draft vs. Active**: Workflows start in `Draft` (Inactive) mode for risk-free editing.
- **1-Click Publishing**: Toggling **Active** immediately arms background triggers (cron schedules, public webhooks, Salesforce Outbound Messages).
- **Template Gallery**: Publish any custom workflow as a workspace template with one click.
- **Version History & Rollback**: Every save generates an immutable snapshot (`WorkflowVersionRecord`), allowing single-click rollback to any prior release.
- **Synchronous Webhook Responses**: `POST /api/webhooks/{path}?respond=true` waits for the run and returns the `respond_to_webhook` node's output with its status code (async 202 by default).

### 3. Frictionless OAuth & Single-Click Reconnect (Zero-Config)
- **Frictionless 1-Click Connect**: Users simply choose an OAuth service (Salesforce, Google Sheets, Gmail, HubSpot, etc.) and click `Connect <Service>`. Flowsmith automatically opens the OAuth popup, completes authorization, and encrypts the tokens. No technical modals, no confusing manual username/password forms, and no setup friction for end users.
- **Dynamic Session Health Status**: The credentials table displays real-time connection status (`● Connected` in green vs. `● Session Expired` in amber) evaluated dynamically by verifying token freshness and expiration windows.
- **Single-Click Reconnect**: When an account session expires, users simply click **`🔄 Reconnect`**. Flowsmith immediately pre-opens an in-browser popup on the direct click gesture (immune to browser popup blockers) with a smooth progress indicator (*"Reconnecting Account..."*).
- **Silent Background Renewal**: If the provider's refresh token is still valid, Flowsmith automatically renews the session in the background without prompting for a login, closes the popup, and updates the credential in place.
- **Seamless Interactive Fallback**: If the session expired or was revoked by Salesforce/Google, the open popup immediately navigates to the authorization URL, the user approves with a single click, and the window self-closes, updating the credential without breaking downstream workflows.
- **Database Credential Storage**: All client IDs, client secrets, access tokens, and refresh tokens are encrypted at rest with AES-256 Fernet directly inside PostgreSQL. Nothing is stored in plain text or hardcoded.

### 4. Universal Token Management (`Token Manager`)
- **Unified Lifecycle Node**: Merges token retrieval, persistence, and auto-refresh into a single node (`token_manager`).
- **Native Dual Output Handles**:
  - `🟢 valid` (upper handle): Emits stored credentials directly to downstream steps, skipping the Login API when active.
  - `🟠 login` (lower handle): Emits to the Login API only on the initial run or when credentials are missing or expired.
- **Zero Redundant Logins**: Never invokes external authentication APIs if valid credentials already exist in the database.
- **Atomic Concurrency Protection**: PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) prevents concurrent execution stampedes during token refresh.
- **Auto-Extraction & Storage**: Automatically parses, normalizes, and AES-GCM encrypts tokens from upstream HTTP/Login responses into `WorkflowAuthState`.
- **Self-Healing 401 Recovery**: Downstream HTTP Request nodes automatically force-refresh expired tokens under lock and retry once with strict infinite-loop prevention.

### 5. 100% Encrypted Credential Vault at Rest
- **Strong Encryption**: All secrets, passwords, database connection strings, access tokens, refresh tokens, and OAuth keys stored in the PostgreSQL `credentials` table (`bytea` column) are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256) with key versioning (`k0:...`) or AES-256-GCM.
- **Zero Credentials in `.env` or Code**: User credentials, database connection strings, and OAuth tokens are never stored in `.env` and are never hardcoded. The `.env` file only holds server-level configuration and the master symmetric encryption key (`CREDENTIALS_ENCRYPTION_KEY`).
- **Zero-Exposure REST API**: `GET /api/credentials` returns only sanitized metadata (`id`, `name`, `type`, `expired`). Ciphertexts are never sent over the wire to the frontend.
- **Multi-Key Keyring**: Supports seamless rotation using comma-separated encryption keys in `CREDENTIALS_ENCRYPTION_KEY`.

### 6. Native AI & RAG Subsystem
- **AI Chat & ReAct Agents**: Autonomous tool-calling loops executing web queries, database lookups, and API calls.
- **RAG Knowledge Base**: Ingest files, split into chunks, generate embeddings, and retrieve relevant context via `pgvector`.
- **Natural Language Workflow Generation**: Create complete multi-step automation workflows directly from plain English prompts.
- **AI Error Assistant**: Click "Explain Error" in the debugger to instantly diagnose stack traces and receive actionable remediation suggestions.
- **Autonomous Node Self-Healing**: Inside the node editor, click `✨ AI Auto-Repair` to inspect root causes, view side-by-side parameter diffs, and click `✨ Apply Fix & Re-test` to auto-heal steps.

### 7. Embedded Relational Data Tables
- **In-App Spreadsheet Database**: Built-in relational data store designed for persistent tabular data without spinning up an external database.
- **Custom Column Schemas**: Define custom columns with strict types (`string`, `number`, `boolean`, `date`, `datetime`, `json`).
- **Spreadsheet Row Editor**: Full search, multi-column sorting, operators (`contains`, `eq`, `ne`, `gt`, `lt`), inline row editing, and bulk deletion.

### 8. Human-in-the-Loop & Interactive Approvals
- **Pausable Execution Graphs**: The `human_approval` node halts workflow execution at critical junctions (financial transactions, sensitive CRM deletions, deployment triggers).
- **Approval Drawer**: Authorized reviewers inspect pending execution state, view item payloads, and click **Approve** or **Reject** to resume the DAG.
- **Audit Logging**: Every approval and rejection action records reviewer identity, timestamp, and decision notes in the immutable audit log.

### 9. Complete White-Labeling & Client Custom Branding
- **100% Brand Customization**: Any client, enterprise team, or reseller can rebrand Flowsmith into their own proprietary platform.
- **Configurable Attributes**: Custom application name, tagline, brand logo image upload, custom favicon, primary & accent color palettes, documentation URL, support email, and custom copyright notice.
- **Dynamic CSS Injection**: Inject custom CSS rules dynamically into the client application DOM for complete style theming and custom typography.
- **Dynamic UI Syncing**: Changes immediately propagate to the TopBar, navigation header, login screen, browser title, and themes via `/api/branding`.

### 10. Data Pinning & Mocking Engine
- **Instant Output Mocking**: Pin output data (`pinned_data`) on any canvas node with a single click (📌 badge).
- **Zero API Quota Consumption**: When pinned, the execution engine completely bypasses live external calls (HTTP, database mutations, CRM updates) and directly feeds mock payloads downstream.

### 11. Model Context Protocol (MCP) AI Server
- **External AI Integration**: Flowsmith acts as a native Model Context Protocol (MCP) server, allowing external AI coding assistants (Claude Desktop, Cursor, Antigravity, LLM agents) to interact with workflows.
- **MCP Tools (`/api/mcp/tools`)**: External agents can programmatically trigger workflows, query Data Tables, list active connectors, and inspect execution results.
- **MCP Resources (`/api/mcp/resources`)**: Exposes workflow graph schemas, execution traces, and operational metadata directly into the model's context window.

### 12. OpenAPI Importer & Custom Connector Engine
- **OpenAPI 3.0 / Swagger 2.0 Importer**: Instantly transform any third-party or internal REST API into first-class Flowsmith connector nodes. Paste an OpenAPI specification URL or raw JSON/YAML to preview base URLs, authentication schemes, and endpoints, then generate native connector nodes with one click.
- **cURL Request Importer**: Inside the HTTP Request node, paste any standard `curl` command to auto-extract the HTTP method, endpoint URL, query parameters, authorization headers, and request body.
- **cURL & Code Snippet Generator**: The Webhook trigger node generates ready-to-run `curl`, JavaScript `fetch`, and Python `requests` commands to trigger workflows from external systems.

### 13. Single-Node Execution ("Test Step") & Context-Aware Debugging
- **Isolated Node Testing**: Right-click any node on the canvas to select **"Test Step"** (or click **"▶ Execute Step"** inside the Node Editor modal) to execute only that single node without running the full DAG.
- **Upstream Context Inheritance**: Flowsmith automatically discovers the latest workflow execution and feeds authentic upstream outputs directly into the target node. You test live transformations, API requests, and conditional rules against real data rather than empty placeholder objects.
- **Preserved Canvas Traces**: Testing a single step merges upstream trace history, node statuses, and output tables, maintaining visual clarity across all predecessor steps.
- **Full Input / Output Transparency**: The 3-panel Node Editor immediately renders the upstream inputs (`$input`, `$json`) in structured Table and JSON trees, alongside the exact outputs and execution timing generated by the test.

### 14. High-Performance Architecture & Route Code-Splitting
- **64.4% Lighter Frontend Initial Bundle**: Implements route-level code-splitting with `React.lazy()` and Vite Rollup chunk optimization. The primary `index.js` chunk drops from **318 kB to 113 kB** (29 kB gzipped), delivering instantaneous page loads and fast First Contentful Paint.
- **Deferred Query Deserialization**: The execution listing endpoint (`GET /api/executions`) utilizes SQLAlchemy column deferrals (`defer(Execution.trace)`, `defer(Execution.results)`, `defer(Execution.workflow_data)`), avoiding the deserialization of megabytes of JSON blobs and slashing query latency and memory usage by ~80%.
- **Adaptive WebSocket Event Streaming**: Consolidates database connection scopes and adopts intelligent idle backoff intervals, reducing database polling from 40 queries/sec down to 5 queries/sec per connected client during idle periods while maintaining sub-50ms latency during active DAG executions.
- **Encrypted OAuth Session Vault**: Transient OAuth2 PKCE states, authorization URLs, and custom client credentials are encrypted at rest with AES-128 Fernet in PostgreSQL (`oauth_states`), ensuring sensitive third-party secrets never leak in database dumps.

---

## Tech Stack

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
| **Database Migrations**| **Alembic** | Automated version-controlled database schema evolution with automatic missing column migration. |
| **Security & Cryptography** | **Cryptography (Fernet)** | AES-128-CBC + HMAC-SHA256 authenticated encryption for customer credentials and tokens at rest. |
| **Authentication** | **PyJWT + Passlib (PBKDF2)** | Stateless JSON Web Token authentication with secure salt password hashing. |
| **HTTP Client** | **HTTPX (Async)** | Non-blocking HTTP client powering the `http_request` node with custom SSRF security filters. |
| **Sandboxed Code Execution** | **DukPy** | Embedded JavaScript interpreter executing custom script transforms safely. |
| **Cron Scheduling** | **croniter** | Standard Unix 5-field cron parsing powering scheduled background automation triggers. |
| **Caching & Pub/Sub**| **Redis 7 (Optional)** | Low-latency job queue, real-time event distribution, and external message caching. |
| **Background Queue** | **Flowsmith Queue Worker** | Dedicated background daemon process (`app.queue.worker`) for parallel execution consumption. |
| **Testing Frameworks** | **Pytest + Vitest + Playwright** | 1800+ backend tests, 324 frontend unit tests, and end-to-end browser specs. |
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
git clone https://bitbucket.org/ids-team/flowsmith.git
cd flowsmith
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
  (set `API_DOCS_ENABLED=true` in `backend/.env` to enable interactive docs).

### 4. Start the Background Worker (In a New Terminal)

```bash
cd backend
.venv\Scripts\activate       # On Windows
# source .venv/bin/activate  # On Linux/macOS
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
- Open `http://localhost:5173`.
- The first user to register automatically receives the **Admin** role with organization configuration privileges.

### Step 2: Create or Clone a Workflow
- **From Scratch**: Click **"＋ Create workflow"** on the `/workflows` page to open a blank canvas.
- **From AI**: Click **"From AI ✨"** and type a plain-English prompt (e.g. *"When a Salesforce contact is updated, verify with AI and send a Slack notification"*).
- **From Templates**: Browse **"/templates"** and click **"Use template →"** on pre-built starter flows.

### Step 3: Design the Graph
- **Add Nodes**: Open the left sidebar palette and drag nodes onto the canvas, or press `Ctrl+K` for the Command Palette.
- **Connect Ports**: Drag from output handles to input handles to establish execution dependencies.
- **Configure Parameters**: Double-click any node to open the 3-panel configuration modal (Inputs preview, Parameters, Outputs). Use expressions like `{{ $json.field }}` or pick upstream fields using the visual expression helper.

### Step 4: Add Credentials
- Navigate to `/credentials` to register API keys, database connection strings, or initiate OAuth2 consent for Salesforce, Google, HubSpot, Slack, etc.
- When connecting Salesforce, authorization is seamless. If tokens expire later, click **Reconnect** for instant 1-click renewal with zero configuration needed.

### Step 5: Test & Debug
- Click **"Run"** in the top bar to execute a test run.
- Open **"Console"** to view live step execution runtimes, inspect full JSON inputs/outputs, or retry failed steps.

### Step 6: Publish & Arm Triggers
- Toggle the switch in the top bar from **"Inactive"** to **"Active"**.
- Your webhook URLs, cron schedules, and external listeners are now armed and running live in production!

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
│   │   ├── oauth_providers.py  # Central OAuth provider registry & token exchange specs
│   │   ├── runner.py           # In-process asynchronous task execution manager
│   │   ├── importexport.py     # Workflow import/export and cross-platform converter
│   │   ├── api/                # 30 REST API modules (170+ endpoints)
│   │   │   ├── auth.py         # Login, register, JWT token refresh, password resets
│   │   │   ├── oauth.py        # Generic OAuth connect & callback router (PKCE, state, inheritance)
│   │   │   ├── workflows.py    # Workflow CRUD, active toggling, imports/exports
│   │   │   ├── executions.py   # Execution history, traces, manual execution & retry
│   │   │   ├── credentials.py  # Credential management, type definitions, health checks
│   │   │   ├── environments.py # Workspace-level encrypted environment variables
│   │   │   ├── salesforce.py   # Dedicated Salesforce OAuth2 & resource router
│   │   │   ├── ai.py           # Natural language generation, RAG, error explainers
│   │   │   ├── data_tables.py  # Native database tables (columns, rows, queries)
│   │   │   ├── webhooks.py     # Public webhook trigger endpoints
│   │   │   ├── branding.py     # White-labeling & corporate branding API
│   │   │   └── ws.py           # Real-time WebSocket execution log streams
│   │   ├── engine/             # Core workflow execution engine
│   │   │   ├── executor.py     # execute_workflow() DAG traversal algorithm
│   │   │   ├── graph.py        # Topological sorting, cycle detection, edge validation
│   │   │   ├── expressions.py  # Sandboxed {{ }} expression evaluation engine
│   │   │   └── node_base.py    # BaseNode, NodeContext, and NodeResult interfaces
│   │   ├── nodes/              # 50+ built-in node type implementations
│   │   ├── connectors/         # 86 registered enterprise connectors (+ OpenAPI catalog)
│   │   ├── providers/          # Low-level external integration clients
│   │   ├── queue/              # Asynchronous job queue & worker processes
│   │   ├── models/             # 20 SQLAlchemy ORM model files (30 relational tables)
│   │   └── security/           # Safe HTTP clients, SSRF filters, Fernet encryption
│   ├── tests/                  # 1800+ automated backend pytest tests
│   ├── alembic/                # Database migrations (schema evolution)
│   └── requirements.txt        # Backend dependencies
├── frontend/
│   ├── src/
│   │   ├── components/         # 75+ Modular React UI components
│   │   │   ├── Canvas.jsx      # Interactive React Flow workspace
│   │   │   ├── CustomNode.jsx  # Beveled glass node renderer with badges & handles
│   │   │   ├── TopBar.jsx      # Navigation, run trigger, debugger toggle, publish switch
│   │   │   ├── ExecutionInspector.jsx # Debugger drawer & timeline inspector
│   │   │   └── NodeEditorModal.jsx # 3-panel node configuration modal
│   │   ├── pages/              # 19 Application pages (Workflows, Templates, RAG, Data Tables, etc.)
│   │   ├── stores/             # Zustand state management (workflowStore, executionStore, etc.)
│   │   ├── api.js              # Comprehensive REST client with interceptors
│   │   └── index.css           # Master design system with glassmorphic tokens & animations
│   ├── tests/                  # Frontend unit tests (Vitest: 285+ passing across suites) & E2E specs
│   ├── package.json            # Node.js dependencies and scripts
│   └── vite.config.js          # Vite configuration
├── deploy/                     # Production configs (Prometheus, Grafana, setup scripts)
├── docker-compose.yml          # Multi-container production deployment manifest
├── docker-compose.staging.yml  # Staging environment deployment manifest
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
| | `webhook` | Public HTTP endpoint with dedicated editor, live URL copier, cURL/Fetch/Python code generator, test dispatcher, and synchronous `?respond=true` mode. |
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
| | `respond_to_webhook` | Returns a synchronous HTTP response to the triggering webhook (`?respond=true`). |
| | `git` | Read-only Git inspection: status, log, branches. |
| | `ftp` | List, download, upload, and delete files on FTP/FTPS servers. |
| | `ssh` | Run remote commands and move files over SSH/SFTP. |
| **Data & Code** | `code` | Executes custom JavaScript (via DukPy) or Python script blocks with built-in Snippet Templates (Group by, Deduplicate, Flatten, Filter, Map). |
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

## First-Party Connectors

Flowsmith includes **86 registered enterprise connectors** (69 native SDK connectors, 17 OpenAPI-generated) organized across 8 distinct categories, governed by an authoritative 5-tier certification state machine:

### Authoritative Certification State Machine
$$\text{STATIC\_VALIDATED} \longrightarrow \text{MOCK\_VALIDATED} \longrightarrow \text{CONTRACT\_VALIDATED} \longrightarrow \text{LIVE\_API\_VALIDATED} \longrightarrow \text{PRODUCTION\_CERTIFIED}$$

- **Live API Validated (1)**: Real HTTP remote execution against live sandboxes (`http`).
- **Contract Validated (12)**: Strict end-to-end protocol and schema suites (`salesforce`, `github`, `slack`, `stripe`, `sendgrid`, `jira`, `hubspot`, `postgres`, `snowflake`, `openai`, `anthropic`, `gemini`).
- **Mock Validated (73)**: Full operation dispatch, parameter validation, and mock API suites.
- **Promotion Gate & Integrity Guards**: 12 negative validation checks preventing false promotions (schema hash drift detection, 90-day evidence expiration, automated disposable write cleanup verification).

### Connector Catalog Highlights

| Connector | Category | Supported Operations & Resources | Authentication |
|---|---|---|---|
| **Salesforce** | CRM | 13 Resources (Account, Contact, Lead, Opportunity, Case, Task, CustomObject, Attachment, Document, User, Flow, Search, CustomApiCall) × full CRUD & SOQL | OAuth2 (PKCE) / Single-Click Reconnect |
| **Microsoft Dynamics 365** | CRM | Dataverse entities (Accounts, Contacts, Leads, Opportunities), custom entities, OData queries | OAuth2 / S2S Service Principal |
| **HubSpot** | CRM | Contacts, Companies, Deals, Tickets (search, get, create, update) | OAuth2 |
| **Pipedrive** | CRM | Deals, Persons, Organizations, Activities, Notes | API Token |
| **Google Calendar** | Productivity | Events CRUD, attendee coordination, calendar lookups | OAuth2 |
| **Google Sheets** | Productivity | Sheet values read, append row, update ranges, batch operations | OAuth2 |
| **Google Drive** | Productivity | File upload, folder traversal, permissions, download | OAuth2 |
| **Google Docs** | Productivity | Documents read, create, append via shared Google OAuth app | OAuth2 |
| **Gmail** | Communication | Send rich HTML/MIME emails, draft creation | OAuth2 |
| **PostgreSQL** | Database | Direct raw SQL queries, transactions, parameterized execution | Connection String |
| **MySQL** | Database | Direct raw SQL queries, batch inserts | Connection String |
| **Snowflake** | Database | Cloud data warehouse queries, table inspection, batch execution | Key Pair / Credentials |
| **MongoDB** | Database | Collections CRUD, aggregation pipelines | Connection URI |
| **Redis** | Database | Key get/set/delete, counters (incr), channel publish | Connection URI |
| **Supabase** | Database | PostgreSQL client, REST data queries, auth admin | API Key / URL |
| **Pinecone** | AI | Vector upsert, query, delete, namespace indexing | API Key |
| **OpenAI** | AI | Chat completions, embeddings, fine-tuning, moderation | API Key |
| **Anthropic** | AI | Claude 3.5 Sonnet / Haiku messages, tool calling | API Key |
| **Google Gemini** | AI | Gemini 1.5 Pro / Flash completions, multimodal tokens | API Key |
| **Slack** | Communication | Channel messaging, ephemeral responses, user lookup | Bot Token |
| **MS Teams** | Communication | Channel messages, webhook web-alerts, adaptive cards | OAuth2 / Webhook |
| **Outlook** | Communication | Email dispatch, calendar schedule lookups | OAuth2 |
| **Discord** | Communication | Webhook and bot channel notifications | Bot Token |
| **Twilio** | Communication | SMS send, message history and lookup | Account SID / Auth Token |
| **WhatsApp** | Communication | Text and template messages via Meta Cloud API | Access Token |
| **SendGrid** | Communication | Transactional email dispatch, template delivery | API Key |
| **Resend** | Communication | Modern developer transactional email API | API Key |
| **GitHub** | Dev | Repository stats, issue creation, pull request management | Personal Access Token |
| **GitLab** | Dev | Issues, merge requests, notes (list, get, create) | Personal Access Token |
| **Bitbucket** | Dev | Repositories, pull requests, comments | Access Token |
| **Jira** | Dev | Issue lifecycle CRUD, transition management | API Token |
| **Linear** | Dev | Issues and comments (list, get, create, update) | API Key |
| **Sentry** | Dev | Issue retrieval, project events, alert resolution | Auth Token |
| **ServiceNow** | Dev | Enterprise IT service tickets, incidents, change requests | Basic / OAuth2 |
| **AWS S3** | Utilities | Bucket browse, object upload/download, presigned URLs | AWS Access Key / Secret |
| **Stripe** | Finance | Customer creation, charge intents, subscription queries | API Secret Key |
| **QuickBooks** | Finance | Company, customers, invoices, raw queries (sandbox/production) | OAuth2 Token |
| **Shopify** | Finance | Product management, customer lookup, order lifecycle | OAuth2 / Admin Token |
| **Airtable** | Productivity | Base record queries, row inserts, table updates | Personal Access Token |
| **Notion** | Productivity | Database queries, page creation, block manipulation | Internal Integration Token |
| **Asana** | Productivity | Tasks and comments (list, get, create, update) | Personal Access Token |
| **Trello** | Productivity | Boards, cards, and comments (list, get, create) | API Key + Token |
| **ClickUp** | Productivity | Lists, tasks, and comments (list, get, create, update) | API Token |
| **Monday.com** | Productivity | Boards, items, and updates (list, get, create) | API Token |
| **Calendly** | Productivity | Event types and scheduled events (list, get, cancel) | Personal Access Token |
| **Zoom** | Productivity | Meetings (list, get, create, delete) | Access Token |
| **Dropbox** | Productivity | Folder browse, metadata, upload, delete | Access Token |
| **Mailchimp** | Marketing | Audiences and contacts (lists, members, tags) | API Key |
| **Brevo** | Marketing | Transactional email + contacts (lists, members) | API Key |
| **PagerDuty** | Utilities | Incidents and notes (list, trigger, update, resolve) | API Token |
| **Zendesk** | Utilities | Support tickets and replies (list, get, create, update) | Email + API Token |
| **Freshdesk** | Utilities | Support tickets and notes (list, get, create, update) | Email + API Key |
| **Todoist** | Utilities | Tasks and comments (list, get, create, close) | API Token |

---

## API Reference

Flowsmith exposes a comprehensive RESTful API documented automatically with Swagger/OpenAPI at `http://127.0.0.1:8000/docs`.

### Authentication & Users
- `POST /api/auth/register` — Register a new account (first user becomes Admin)
- `POST /api/auth/login` — Authenticate and receive JWT access token
- `POST /api/auth/forgot-password` — Generate password reset token
- `POST /api/auth/reset-password` — Set new password with reset token
- `GET /api/auth/me` — Retrieve current authenticated profile

### OAuth & Reconnection
- `POST /api/auth/{provider}/connect` — Start OAuth flow with state, PKCE verifier, and optional credential inheritance
- `GET /api/auth/{provider}/callback` — OAuth callback: exchange authorization code, update encrypted credential in DB, and redirect
- `POST /api/credentials/{id}/reconnect` — Automated background renewal or trigger interactive re-authorization

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
- `POST /api/workflows/import` — Import workflow (Flowsmith native or standard workflow JSON format)
- `POST /api/workflows/{id}/preview-expression` — Live evaluate visual expressions against upstream node context

### Executions & Live Traces
- `GET /api/executions` — List execution history with status and duration filters
- `POST /api/workflows/{id}/run` — Execute workflow manually
- `GET /api/executions/{id}` — Fetch detailed execution results per node
- `GET /api/executions/{id}/export?format=json|csv` — Export execution trace and step records as structured JSON or CSV audit records
- `POST /api/executions/{id}/retry` — Retry a failed execution
- `POST /api/executions/{id}/cancel` — Cancel an in-flight execution
- `POST /api/executions/{id}/approve` — Approve a pending human-approval step
- `POST /api/executions/{id}/reject` — Reject a pending human-approval step
- `WS /api/ws/executions/{id}` — Real-time WebSocket execution event stream

### Credentials & Security
- `GET /api/credentials` — List user's encrypted credentials (metadata only)
- `POST /api/credentials` — Store credential (automatically encrypted with Fernet)
- `POST /api/credentials/{id}/test` — Verify credential connectivity (auto-refreshes expired OAuth tokens once and re-probes)
- `POST /api/credentials/{id}/reconnect` — Background token renewal without interactive login
- `DELETE /api/credentials/{id}` — Delete credential
- `GET /api/credentials/types` — Discover supported credential schemas (63 types)

### White-Labeling & Custom Branding
- `GET /api/branding` — Fetch active public branding settings (logo, app name, colors, custom CSS, documentation URL, support email, copyright)
- `PUT /api/branding` — Update corporate branding, white-labeling configurations, and custom CSS injection
- `POST /api/branding/reset` — Reset to default Flowsmith branding

### OpenAPI Connector Importer
- `POST /api/connectors/preview-openapi` — Preview and parse OpenAPI 3.0/3.1 or Swagger 2.0 specification
- `POST /api/connectors/import-openapi` — Generate and register a custom first-class connector node from an OpenAPI spec

### Model Context Protocol (MCP) Server
- `GET /api/mcp/tools` — List available automation tools for external AI models
- `POST /api/mcp/tools/call` — Execute Flowsmith automation tool via external AI agent
- `GET /api/mcp/resources` — Read workflow schemas and execution resources

### Data Tables
- `GET /api/data-tables` — List workspace Data Tables
- `POST /api/data-tables` — Create new Data Table with custom column schema
- `GET /api/data-tables/{id}/rows` — Query and filter rows with pagination
- `POST /api/data-tables/{id}/rows` — Insert new rows into table

---

## Database Schema

Flowsmith stores relational metadata in **30 normalized PostgreSQL tables** managed by Alembic (14 revision scripts; verified by `backend/scripts/check_schema_parity.py`):

| Table Name | Description |
|---|---|
| `users` | User accounts, credentials, role authorizations, and timestamps. |
| `workflows` | Workflow definitions (JSON graph, version, active status, workspace). |
| `workflow_versions` | Immutable snapshots created on every workflow update. |
| `workflow_auth_state` | Encrypted authentication tokens, refresh tokens, and lifecycle cache per `(workflow_id, provider)`. |
| `executions` | High-level execution records (status, duration, error summary). |
| `execution_events` | Granular event audit stream (per-node input/output/error). |
| `credentials` | Fernet-encrypted customer secrets and OAuth tokens at rest (`bytea`). |
| `jobs` | Background task queue storage for distributed asynchronous workers. |
| `organizations` | Top-level tenant boundaries for enterprise multi-tenancy. |
| `organization_members`| User association and roles within an organization. |
| `workspaces` | Logical project environments within organizations. |
| `workspace_members` | Workspace-level permissions and access controls. |
| `workflow_shares` | Explicit read/write sharing permissions across users. |
| `subscriptions` | Stripe subscription and billing plan records. |
| `audit_events` | Immutable security log tracking all mutations and administrative actions. |
| `branding_settings` | Dynamic client white-labeling, brand identity, logos, color themes, and custom CSS injection. |
| `webhooks` | Registered public webhook trigger paths. |
| `schedule_triggers` | Cron schedule trigger rules and last-fired records. |
| `webhook_deliveries`| History of inbound webhook HTTP requests and payloads. |
| `oauth_states` | Temporary tokens safeguarding OAuth2 PKCE handshakes and client credentials. |
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

### Backend Testing (1800+ Tests)

```bash
cd backend

# Run the complete test suite
pytest -q

# Run fast unit tests (skip slow integration tests)
pytest -m "not timing" -q

# Test specific subsystems
pytest tests/test_api/test_executions.py -q                # Workflow execution DAG, cancellation & status
pytest tests/test_security_audit.py -q                     # Full enterprise security & access audit
pytest tests/test_redis_live_audit.py -q                   # Live Redis job queue lifecycle & backoff
pytest tests/test_api/test_oauth.py -q                     # Generic OAuth & single-click reconnect
pytest tests/test_api/test_credential_auto_reconnect.py -q # OAuth auto-reconnect & renewal sweep
pytest tests/test_api/test_token_manager.py -q             # Universal Token Manager & dual handles
pytest tests/test_api/test_workflows.py -q                 # Workflow CRUD & active toggle
pytest tests/test_api/test_templates.py -q                 # Template cloning & import
pytest tests/test_security/ -q                             # SSRF, auth, and encryption audits

# Note: Automated test runs utilize dedicated isolated databases (automate_test)
# and isolated Redis instances (db 15), preventing collision with production workers.
```

### Frontend Testing (324 Vitest Tests & E2E Specs)

```bash
cd frontend

# Run Vitest unit tests (324 passing across 23 test files)
npx vitest run

# Run specific suite
npx vitest run src/utils/userProfile.test.js
npx vitest run src/pages/CredentialsPage.test.jsx

# Run Playwright end-to-end browser tests
npx playwright install chromium
npm test

# Run code linter (Oxlint: 0 warnings, 0 errors across 133 files)
npx oxlint --deny-warnings src

# TypeScript type validation
npx tsc --noEmit

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

### 3. Configuration & Environment Variables

| Variable | Default / Example | Required | Description |
|---|---|:---:|---|
| `JWT_SECRET` | `openssl rand -hex 32` | **Yes** | Cryptographic secret for signing user session tokens. |
| `CREDENTIALS_ENCRYPTION_KEY` | `Fernet.generate_key()` | **Yes** | Key for encrypting stored credentials at rest (supports multi-key rotation). |
| `DATABASE_URL` | `postgresql://automate:automate@postgres:5432/automate` | **Yes** | PostgreSQL connection string (PostgreSQL 16 with pgvector). |
| `REDIS_URL` | `redis://redis:6379/0` | Dev only | Redis connection string for the job queue and caching. |
| `REDIS_PASSWORD` | *(empty in dev)* | Prod | Password for Redis authentication in production. |
| `PUBLIC_URL` | `https://yourdomain.com` | Prod | Public-facing base URL of the Flowsmith web application. |
| `APP_ENV` | `development` / `production` | **Yes** | Runtime mode; enforces strict security checks when set to `production`. |
| `CORS_ORIGINS` | `https://yourdomain.com` | Prod | Allowed CORS origins (comma-separated; wildcards prohibited in production). |
| `SMTP_HOST` | `smtp.office365.com` | Optional | Outbound SMTP server host for system password resets and alerts. |
| `SMTP_PORT` | `587` | Optional | SMTP port (e.g. `587` for STARTTLS, `465` for SSL, `25` for relay). |
| `SMTP_USER` | `noreply@yourdomain.com` | Optional | SMTP username / service account email address. |
| `SMTP_PASSWORD` | `your_smtp_password` | Optional | SMTP password or app-specific password. |
| `MAIL_FROM` | `"Flowsmith <noreply@yourdomain.com>"` | Optional | Sender address displayed in outgoing system emails. |
| `SMTP_USE_TLS` | `false` | Optional | Enable implicit TLS/SSL (standard for port 465). |
| `SMTP_STARTTLS` | `true` | Optional | Upgrade connection with STARTTLS (standard for port 587). |
| `SALESFORCE_CLIENT_ID` | *(OAuth Connected App)* | Optional | Salesforce OAuth Client ID (or store encrypted in DB). |
| `SALESFORCE_CLIENT_SECRET` | *(OAuth Connected App)* | Optional | Salesforce OAuth Client Secret (or store encrypted in DB). |

---

### 4. SMTP & Mail Delivery Setup

Flowsmith supports enterprise email delivery through two complementary channels:

1. **System & Security Emails (Platform-Level)**:
   - Configured via environment variables (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`).
   - Powers self-service user password resets (`/api/auth/forgot-password`), security audit alerts, and critical system health notifications.
   - Compatible with Microsoft 365, Google Workspace, AWS SES, SendGrid, Brevo, and internal unauthenticated SMTP relays.

2. **Workflow Transactional Emails (`Send Email` Node)**:
   - Configured directly by users in the web interface under **Credentials -> + Add Credential -> SMTP**.
   - Supports arbitrary sender addresses, custom ports, STARTTLS/SSL, and automatic retry on MTA backoff.
   - All credentials entered in the UI are immediately encrypted at rest using AES-128 Fernet before database commit.

---

## Security & Compliance

Flowsmith is built from the ground up for strict enterprise environments:

- **100% Credential Encryption at Rest**: All sensitive credential secrets, API keys, OAuth tokens, and passwords stored in PostgreSQL (`credentials.data` of type `bytea`) are encrypted at rest using Fernet (AES-128-CBC with HMAC-SHA256) or AES-256-GCM. Plaintext secrets are never persisted to disk.
- **Zero-Leak API Architecture**: The REST API (`GET /api/credentials`) strictly returns safe metadata (`{id, name, type}`). Decrypted secrets are never returned in HTTP responses or exposed to the client browser.
- **Deferred Worker Decryption**: Secrets are decrypted strictly in worker memory immediately prior to node execution, and isolated per execution lifecycle.
- **Multi-Key Keyring & Rotation**: Secrets support zero-downtime multi-key rotation via the credential keyring (`CREDENTIALS_ENCRYPTION_KEY` accepts a comma-separated list of keys, decrypting with candidate keys and re-encrypting with the newest primary key).
- **SSRF Attack Mitigation**: The `SafeHTTPClient` inspects destination IPs and rejects queries to loopback, link-local, private LAN, or cloud metadata endpoints (`169.254.169.254`).
- **High-Entropy Trigger Validation**: Webhook endpoints enforce 24+ character high-entropy tokens to prevent brute-force discovery.
- **Sensitive Key Redaction**: Credentials, authorization headers, and bearer tokens are automatically scrubbed from execution logs, error messages, and database traces before storage.
- **Production Secret Guard**: The application halts on startup if default insecure secrets or wildcard CORS origins are detected when `APP_ENV=production`.

---

## Monitoring & Telemetry

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

**Flowsmith was designed, architected, and developed from scratch by [Gaurav](https://github.com/gauravsahoo-ops)** — every layer, from the visual DAG canvas and workflow execution engine to the OAuth framework, credential vault, AI subsystem, and deployment stack, is original work.

Please retain this attribution when self-hosting or redistributing, as required by the [Business Source License 1.1 (BSL 1.1)](./LICENSE).

---

## License

Flowsmith is source-available software licensed under the [Business Source License 1.1 (BSL 1.1)](./LICENSE). It is free for internal business, development, and personal use, and automatically converts to the permissive MIT License on January 1, 2030. Commercial licensing is required only for providing Flowsmith as a competing hosted or managed cloud SaaS to third parties.
