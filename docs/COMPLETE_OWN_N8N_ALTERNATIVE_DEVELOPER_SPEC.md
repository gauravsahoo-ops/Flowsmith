# Building Our Own Workflow Automation Tool (n8n Alternative)

### Complete Technical Documentation --- From Zero to Working Product

> **What this document is:** everything you need to design, build, test,
> and deploy your own workflow automation platform. It is written for a
> beginner but goes deep enough that you never have to guess "what
> should the code do here?"
>
> read its architecture for inspiration (don't copy its code; it's
> fair-code licensed).

------------------------------------------------------------------------

## Table of Contents

1.  [What We Are Building](#1-what-we-are-building)
2.  [Core Concepts](#2-core-concepts)
3.  [High-Level Architecture](#3-high-level-architecture)
4.  [Tech Stack & Why](#4-tech-stack--why)
5.  [Database Schema (Data Model)](#5-database-schema-data-model)
6.  [Workflow JSON Format (The
    Contract)](#6-workflow-json-format-the-contract)
7.  [Node Contract (How to Build a
    Node)](#7-node-contract-how-to-build-a-node)
8.  [The Execution Engine (Deep
    Dive)](#8-the-execution-engine-deep-dive)
9.  [REST API Design](#9-rest-api-design)
10. [Real-Time Updates (WebSockets)](#10-real-time-updates-websockets)
11. [Frontend Architecture (React + React
    Flow)](#11-frontend-architecture-react--react-flow)
12. [Credentials & Security](#12-credentials--security)
13. [Background Jobs & Workers
    (Celery/Redis)](#13-background-jobs--workers-celeryredis)
14. [Testing Strategy](#14-testing-strategy)
15. [Deployment (Docker →
    Production)](#15-deployment-docker--production)
16. [Performance & Scaling](#16-performance--scaling)
17. [Full Folder Structure](#17-full-folder-structure)
18. [Milestone Roadmap & Timeline](#18-milestone-roadmap--timeline)
19. [Common Pitfalls (Read Before
    Coding)](#19-common-pitfalls-read-before-coding)
20. [Your AI Differentiator (Why You Can Beat
    n8n)](#20-your-ai-differentiator-why-you-can-beat-n8n)
21. [Glossary](#21-glossary)
22. [Resources & References](#22-resources--references)

------------------------------------------------------------------------

## 1. What We Are Building

A **self-hostable workflow automation platform**: users drag building
blocks ("nodes") onto a visual canvas, connect them with lines, and the
system executes them in order --- passing data between them. Clicking
"Run" executes the workflow; triggers (webhook, schedule) execute it
automatically.

**The three pillars of the product:**

    ┌─────────────────────────────────────────────────────┐
    │  1. THE ENGINE (backend)                            │
    │     Reads workflow JSON, executes nodes in order,   │
    │     passes data between them, logs everything       │
    ├─────────────────────────────────────────────────────┤
    │  2. THE CANVAS (frontend)                           │
    │     Drag-and-drop UI where users build workflows    │
    ├─────────────────────────────────────────────────────┤
    │  3. THE NODES (plugins)                             │
    │     Individual building blocks: HTTP, Email, Slack, │
    │     Database, AI Chat, IF/conditions...             │
    └─────────────────────────────────────────────────────┘

**Target milestone example (what you're building toward):**

    [Webhook Trigger] → [IF: contains "urgent"] → [Send Slack Message]
                              │
                              └── (else) → [Save to Database]

### Product principles (decide these now)

  -----------------------------------------------------------------------
  Principle                           Decision
  ----------------------------------- -----------------------------------
  Who is it for?                      Small teams / AI builders first

  Self-hosted or cloud?               Both --- self-host first, offer
                                      cloud later

  Extensible?                         Yes --- third-party developers can
                                      build custom nodes (npm/PyPI
                                      packages)

  Data model                          Workflows are **JSON documents**
                                      (like n8n). Everything is derived
                                      from this

  AI-native                           AI nodes are first-class citizens,
                                      not add-ons
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 2. Core Concepts

  -------------------------------------------------------------------------
  Term                    Meaning                   Analogy
  ----------------------- ------------------------- -----------------------
  **Node**                One step/box in a         A single Lego block
                          workflow                  

  **Workflow**            A collection of connected The finished Lego model
                          nodes (a graph)           

  **Trigger node**        The node that starts a    The "on" switch
                          workflow (webhook,        
                          schedule, manual)         

  **Execution**           One single run of a       Pressing play once
                          workflow                  

  **Edge / Connection**   The line linking two      The wire between two
                          nodes                     blocks

  **Credential**          Saved login/API key used  Your keychain
                          by a node                 

  **DAG**                 Directed Acyclic Graph    A one-way flowchart
                          --- nodes with            
                          connections, no loops     

  **Item**                One unit of data flowing  One row of a
                          through a node            spreadsheet

  **Data flow**           Each node receives        Water through pipes
                          `items` (JSON objects)    
                          and outputs new ones      

  **Expression**          A template like           A formula cell in Excel
                          `{{ $input.data.url }}`   
                          that references previous  
                          node output               

  **Branching**           A node with multiple      A fork in the road
                          outputs (IF-node:         
                          true/false)               

  **Webhook**             A public URL that starts  A doorbell
                          a workflow when called    

  **Cron trigger**        A schedule rule           An alarm clock
                          (`*/5 * * * *`) that      
                          starts a workflow         
  -------------------------------------------------------------------------

------------------------------------------------------------------------

## 3. High-Level Architecture

    ┌──────────────────────────────────────────────────┐
    │                    FRONTEND                       │
    │   React + React Flow (drag-drop canvas)          │
    │   + Node config panel + Execution history UI     │
    └───────────────┬──────────────────────────────────┘
                    │  REST API (save/load/run) + WebSocket (live updates)
    ┌───────────────▼──────────────────────────────────┐
    │            BACKEND API SERVER (FastAPI)           │
    │   • Auth (JWT) & user management                 │
    │   • CRUD for workflows, credentials              │
    │   • Queue execution jobs                         │
    │   • Serve webhooks (public URLs)                 │
    └───────────────┬──────────────────────────────────┘
                    │  publishes jobs / reads results
    ┌───────────────▼──────────────────────────────────┐
    │          WORKFLOW EXECUTION ENGINE (worker)       │
    │   • Reads workflow JSON (the DAG)                │
    │   • Topologically sorts nodes                    │
    │   • Runs each node, passes data along            │
    │   • Writes per-node logs & status                │
    └───────┬─────────────────────────────┬────────────┘
            │                             │
    ┌───────▼────────┐        ┌───────────▼───────────┐
    │  Job Queue      │        │    NODE LIBRARY       │
    │  Redis + Celery │        │  http_request.py      │
    │  (or BullMQ)    │        │  send_email.py        │
    └───────┬────────┘        │  webhook.py           │
            │                 │  if_condition.py      │
    ┌───────▼────────────────▼───────────────────────┐
    │              DATABASE (PostgreSQL)              │
    │  users, workflows, executions, execution_items, │
    │  credentials (encrypted), webhooks              │
    └──────────────────────────────────────────────────┘

### Why a queue/worker at all?

Workflows can run for seconds or **hours** (waiting on API calls, human
approvals). If the API server executed them inline, one long workflow
would block everything. Instead:

-   API server **saves the job to Redis** (via Celery)
-   **Worker processes** pick up jobs and execute the engine
-   Progress is reported back through the database + WebSocket --- the
    UI updates live even while the workflow is still running

------------------------------------------------------------------------

## 4. Tech Stack & Why

Since you already know Python, this stack keeps your learning curve low:

  -----------------------------------------------------------------------
  Layer                   Technology              Why
  ----------------------- ----------------------- -----------------------
  Backend API             **Python + FastAPI**    Fast to build,
                                                  auto-generated API
                                                  docs, Pydantic
                                                  validation for free

  Execution Engine        **Python (custom, \~200 Graph traversal is
                          lines core)**           simple logic --- no
                                                  heavy framework needed

  Queue / Async jobs      **Redis + Celery**      Battle-tested, huge
                                                  community, perfect for
                                                  long-running workflows

  Database                **PostgreSQL**          Reliable, JSONB columns
                                                  fit our workflow-JSON
                                                  model perfectly

  ORM                     **SQLAlchemy 2.0** (+   The standard Python
                          Alembic migrations)     ORM, works great with
                                                  FastAPI

  Frontend                **React + React Flow**  React Flow gives
                                                  drag-drop canvas +
                                                  zoom + connections out
                                                  of the box

  Frontend state          **Zustand** (small)     Simpler than Redux for
                                                  a beginner, scales fine

  Auth                    **JWT + passlib         Simple and standard;
                          (bcrypt)**              OAuth2 later for
                                                  Google/Slack

  Credential encryption   **`cryptography`        Encrypt API keys at
                          (Fernet/AES)**          rest

  HTTP client (nodes)     **`httpx`**             Async + sync support,
                                                  clean API

  Scheduling              **APScheduler or Celery Cron triggers
                          beat**                  

  Containerization        **Docker + Docker       Consistent local dev
                          Compose**               and deployment

  Hosting                 **Render / Railway /    Start on Render or
                          AWS EC2**               Railway (simplest); AWS
                                                  when you need it
  -----------------------------------------------------------------------

**Beginner tip:** don't touch Kubernetes yet. One VM + Docker Compose is
enough for your first real users.

------------------------------------------------------------------------

## 5. Database Schema (Data Model)

This is the backbone. Design it once, carefully. All timestamps in UTC,
`id` as UUID strings (easier than ints for a distributed system later).

``` sql
-- 1. USERS: who can log in
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,              -- bcrypt hash, never plaintext
    name          TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- 2. WORKFLOWS: the graph. JSON stored in a JSONB column.
CREATE TABLE workflows (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    active      BOOLEAN DEFAULT FALSE,        -- is it "armed" to run on triggers?
    nodes       JSONB NOT NULL DEFAULT '[]',  -- [ {id,type,position,parameters} ]
    connections JSONB NOT NULL DEFAULT '[]',  -- [ {source, target, sourceHandle, targetHandle} ]
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_workflows_user ON workflows(user_id);

-- 3. EXECUTIONS: one row per run of a workflow
CREATE TABLE executions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id  UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'running',
                 -- 'running' | 'success' | 'error' | 'cancelled' | 'timeout'
    trigger      TEXT,                          -- 'manual' | 'webhook' | 'schedule'
    started_at   TIMESTAMPTZ DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    error        JSONB                          -- { message, node_id, stack? }
);
CREATE INDEX idx_executions_workflow ON executions(workflow_id, started_at DESC);

-- 4. EXECUTION ITEMS: per-node output snapshots (for the history UI)
CREATE TABLE execution_items (
    id           BIGSERIAL PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    node_id      TEXT NOT NULL,
    node_type    TEXT NOT NULL,
    status       TEXT NOT NULL,                -- 'success' | 'error' | 'skipped'
    input_data   JSONB,                        -- what the node received
    output_data  JSONB,                        -- what the node produced
    error        JSONB,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);
CREATE INDEX idx_exec_items_exec ON execution_items(execution_id);

-- 5. CREDENTIALS: stored ENCRYPTED (see section 12)
CREATE TABLE credentials (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,                  -- 'http', 'smtp', 'slack', ...
    data       BYTEA NOT NULL,                 -- AES-encrypted JSON blob
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_creds_user ON credentials(user_id);

-- 6. WEBHOOKS: public URLs registered by active workflows
CREATE TABLE webhooks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    path        TEXT UNIQUE NOT NULL,          -- e.g. '7f3e9a1c-...'
    method      TEXT NOT NULL DEFAULT 'POST',
    node_id     TEXT NOT NULL,                 -- which node in the workflow
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

> **Design note:** `nodes` and `connections` live as **JSONB inside the
> workflow row**. You don't need separate `nodes` and `edges` tables ---
> you always load/save the whole workflow as one document. This mirrors
> n8n and keeps versioning/snapshots trivial.

------------------------------------------------------------------------

## 6. Workflow JSON Format (The Contract)

Everything in the system revolves around this JSON shape. Both frontend
and backend must agree on it --- define it **once** as a Pydantic model
(backend) and TypeScript types (frontend), and never drift.

### 6.1 A single node

``` json
{
  "id": "node_2x9f",
  "type": "http_request",
  "position": { "x": 120, "y": 180 },
  "parameters": {
    "method": "GET",
    "url": "https://api.example.com/data",
    "headers": { "Authorization": "Bearer {{ $cred.http.apiKey }}" }
  }
}
```

### 6.2 Connections (edges)

``` json
{
  "source": "node_2x9f",
  "sourceHandle": "main",        // some nodes have multiple outputs: "true"/"false", "main"
  "target": "node_7bq1",
  "targetHandle": "main"
}
```

### 6.3 A full workflow

``` json
{
  "id": "wf_001",
  "name": "Alert me on urgent emails",
  "nodes": [
    { "id": "n1", "type": "webhook", "position": { "x": 0, "y": 0 }, "parameters": { "path": "incoming-email" } },
    { "id": "n2", "type": "if_condition", "position": { "x": 200, "y": 0 }, "parameters": { "condition": { "left": "{{ $json.subject }}", "operator": "contains", "right": "urgent" } } },
    { "id": "n3", "type": "slack", "position": { "x": 400, "y": -100 }, "parameters": { "channel": "#ops", "text": "URGENT: {{ $json.subject }}" } },
    { "id": "n4", "type": "database_query", "position": { "x": 400, "y": 100 }, "parameters": { "sql": "INSERT INTO alerts (subject) VALUES ('{{ $json.subject }}')" } }
  ],
  "connections": [
    { "source": "n1", "sourceHandle": "main", "target": "n2", "targetHandle": "main" },
    { "source": "n2", "sourceHandle": "true", "target": "n3", "targetHandle": "main" },
    { "source": "n2", "sourceHandle": "false", "target": "n4", "targetHandle": "main" }
  ]
}
```

### 6.4 Expression syntax (start small, grow later)

-   `{{ $json.field }}` --- value from the incoming data
-   `{{ $node.http_request.json.body }}` --- value from a specific
    node's output
-   `{{ $cred.http.apiKey }}` --- a credential value (encrypted,
    resolved server-side)
-   `{{ $now }}`, `{{ $workflow.id }}` --- built-in variables

> **Beginner version:** in phase 1--2, skip expressions entirely. Each
> node gets plain parameters. Add a tiny `{{ }}` evaluator in phase 3.
> It is a huge win later, don't over-engineer now.

------------------------------------------------------------------------

## 7. Node Contract (How to Build a Node)

Every node is just a Python class with three parts. This is your
**plugin SDK** --- third-party developers should be able to add nodes
without touching core code.

``` python
# backend/app/nodes/http_request.py
from pydantic import BaseModel
from app.engine.node_base import BaseNode, NodeContext, NodeResult

class HTTPRequestParams(BaseModel):
    method: str = "GET"
    url: str
    headers: dict = {}

class HTTPRequestNode(BaseNode):
    """Calls any REST API."""
    node_type = "http_request"
    display_name = "HTTP Request"
    icon = "🌐"

    @property
    def parameters_schema(self) -> type[BaseModel]:
        return HTTPRequestParams

    @property
    def input_types(self) -> list[str]:
        return ["main"]              # which input handles this node accepts

    @property
    def output_types(self) -> list[str]:
        return ["main"]              # branches: e.g. ["true", "false"] for IF nodes

    def run(self, ctx: NodeContext, params: HTTPRequestParams, input_items: list[dict]) -> NodeResult:
        # ctx carries: logger, credentials resolver, http client, execution_id
        response = ctx.http_client.request(params.method, params.url, headers=params.headers)
        return NodeResult(output_items=[response.json()])   # one item per output
```

**The `BaseNode` contract in pseudocode:**

    BaseNode
     ├── node_type          # unique string id used in workflow JSON
     ├── display_name       # shown in the UI sidebar
     ├── parameters_schema  # Pydantic model → auto-generates the config panel form!
     ├── input_types        # usually ["main"]
     ├── output_types       # ["main"] or ["true","false"] for branches
     ├── credentials        # optional: list of credential types this node can use
     └── run(ctx, params, input_items) -> NodeResult
          NodeResult = { output_items: list[dict] | dict, error?: str }

### Why Pydantic `parameters_schema` is genius

The same schema drives **three** things automatically:

1.  **Validation** --- bad input rejected before running
2.  **Frontend form** --- your backend can expose
    `GET /nodes/{type}/schema` and the React config panel renders the
    form from JSON schema (use `fastapi` → `schema()` →
    `react-jsonschema-form`)
3.  **Docs** --- your node library documentation generates itself

### The first 8 nodes to build (in this order)

  -----------------------------------------------------------------------
  \#                Node              Type              Why first
  ----------------- ----------------- ----------------- -----------------
  1                 **Manual          trigger           Lets you run any
                    Trigger**                           workflow from the
                                                        UI --- makes
                                                        testing possible

  2                 **HTTP Request**  action            80% of
                                                        automations
                                                        involve calling
                                                        an API

  3                 **Webhook         trigger           Lets other
                    Trigger**                           systems start
                                                        your workflows

  4                 **IF /            logic             Branching is what
                    Condition**                         makes workflows
                                                        "smart"

  5                 **Set / Edit      transform         Lets users
                    Data**                              reshape data
                                                        between nodes

  6                 **Send Email      action            The classic
                    (SMTP)**                            "notify me"
                                                        automation

  7                 **Database        action            Connect workflows
                    Query**                             to user data

  8                 **Schedule        trigger           Cron-based
                    Trigger**                           automatic runs
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 8. The Execution Engine (Deep Dive)

This is the heart of the product. Get this right and everything else is
easy.

### 8.1 Step-by-step algorithm

    1. LOAD      — fetch workflow JSON from DB (or receive from API)
    2. BUILD     — convert nodes + connections into a graph:
                   { node_id: { node, inputs: [parent_ids], outputs: [child_ids] } }
    3. VALIDATE  — every connection references existing nodes;
                   every trigger node has exactly one path; reject cyclic graphs
    4. ORDER     — topologically sort: every node comes after its parents
    5. EXECUTE   — for each node in order:
         a. Gather input: the output_items of its connected parents
         b. If multiple parents → merge their items (combine or error)
         c. Resolve expressions in parameters ({{ }} substitution)
         d. Resolve credentials (decrypt, inject)
         e. Call node.run()
         f. Store result + status in execution_items table
         g. On error → mark execution 'error', stop downstream nodes
                    (unless the node has error-handling configured)
    6. FINISH    — mark execution 'success' (or 'error'), record finished_at

### 8.2 Parallel branches (advanced, add in phase 2.5)

Nodes on **separate branches** can run in parallel (threads or asyncio).
Two branches merge at a node with two parents --- merge rules:

-   **combine**: concatenate items from both parents
-   **waitForAll**: run the downstream node only when both parents
    finished
-   **waitForOne**: run it when the first parent finishes (like n8n)

### 8.3 Error handling & retries

  -----------------------------------------------------------------------
  Situation               Default behavior        Configured option
  ----------------------- ----------------------- -----------------------
  Node throws             Execution fails, log    "continue on error" →
                          error, stop             pass a `$error` item
                                                  onward

  Network failure         Fail immediately        Retry policy:
  (timeout)                                       `max_retries`,
                                                  `backoff` (2s → 4s →
                                                  8s...)

  Workflow runs too long  No limit initially      Global timeout (e.g. 1
                                                  hour), then kill + mark
                                                  'timeout'

  Credential missing      Fail with clear         ---
                          message: "Node X needs  
                          credential Y"           
  -----------------------------------------------------------------------

### 8.4 Concurrency rules (very important)

-   **Never** run two executions of the same scheduled/webhook workflow
    at the same time (default: skip if one is running --- like n8n)
-   Allow parallel manual runs (users love clicking "Run" repeatedly)
-   Workers should be **stateless** --- any worker can run any workflow
    (that's what makes scaling easy)

### 8.5 Simplified core (this is the whole engine)

``` python
def execute_workflow(workflow: Workflow, trigger_data: list[dict], ctx) -> ExecutionResult:
    graph = build_graph(workflow.nodes, workflow.connections)
    validate_graph(graph)
    order = topological_sort(graph)          # list of node_ids

    results: dict[str, list[dict]] = {}      # node_id -> output items
    for node_id in order:
        node = graph[node_id].node
        parents = graph[node_id].inputs      # node_ids that feed this one
        input_items = merge_items([results[p] for p in parents if p in results])
        if not input_items and parents:
            continue                          # upstream failed/skipped -> skip
        try:
            params = resolve_expressions(node.parameters, input_items)
            creds  = resolve_credentials(node, ctx)     # decrypt & inject
            result = run_node(node, params, creds, input_items, ctx)
            results[node_id] = result.output_items
            save_exec_item(ctx, node_id, "success", input_items, result.output_items)
        except NodeExecutionError as e:
            save_exec_item(ctx, node_id, "error", input_items, None, str(e))
            if not node.settings.get("continue_on_error"):
                return ExecutionResult("error", error=e)
    return ExecutionResult("success", results)
```

------------------------------------------------------------------------

## 9. REST API Design

All endpoints return JSON. Auth via `Authorization: Bearer <jwt>` except
public webhooks.

  ------------------------------------------------------------------------------------
  Method                  Path                                 Purpose
  ----------------------- ------------------------------------ -----------------------
  POST                    `/api/auth/register`                 Create account

  POST                    `/api/auth/login`                    Get JWT

  GET                     `/api/workflows`                     List my workflows

  POST                    `/api/workflows`                     Create workflow

  GET                     `/api/workflows/{id}`                Get one workflow (full
                                                               JSON)

  PUT                     `/api/workflows/{id}`                Save/update workflow
                                                               (the canvas calls this
                                                               on every change ---
                                                               debounce!)

  PATCH                   `/api/workflows/{id}/active`         Arm/disarm triggers

  DELETE                  `/api/workflows/{id}`                Delete

  POST                    `/api/workflows/{id}/run`            Manual execution →
                                                               returns `execution_id`

  GET                     `/api/executions?workflow_id={id}`   List past runs

  GET                     `/api/executions/{id}`               Full run detail (all
                                                               node outputs)

  GET                     `/api/executions/{id}/items`         Paginated node
                                                               snapshots

  POST                    `/api/executions/{id}/retry`         Re-run a failed
                                                               execution

  POST                    `/api/executions/{id}/cancel`        Cancel a running
                                                               execution

  GET                     `/api/nodes`                         List all available node
                                                               types (for the sidebar)

  GET                     `/api/nodes/{type}/schema`           Parameters schema
                                                               (drives the config
                                                               panel)

  GET                     `/api/credentials`                   List credentials
                                                               (metadata only ---
                                                               **never data**)

  POST                    `/api/credentials`                   Create credential
                                                               (encrypt server-side)

  DELETE                  `/api/credentials/{id}`              Delete

  POST                    `/api/webhooks/{path}`               **Public** --- starts a
                                                               workflow (no auth)

  GET                     `/api/health`                        Liveness probe
  ------------------------------------------------------------------------------------

### Response shape convention (keep consistent everywhere)

``` json
{
  "data": { ... },
  "meta": { "page": 1, "pageSize": 50, "total": 321 }
}
```

------------------------------------------------------------------------

## 10. Real-Time Updates (WebSockets)

The "Run" button must show live progress: node turns green when done,
red on error --- *while the workflow is still running*.

**Design (simple + reliable):**

1.  Worker publishes events to Redis pub/sub:
    `{ execution_id, node_id, status, timestamp }`
2.  API server has a **WebSocket endpoint**
    `/ws/executions/{execution_id}`
3.  The API server subscribes to Redis and forwards events to connected
    clients
4.  Frontend opens one socket per visible execution, updates node colors
    on the canvas

```{=html}
<!-- -->
```
    Worker ──(Redis pub/sub)──► API server ──(WebSocket)──► Browser canvas

> **Fallback:** if WebSockets scare you initially, **poll**
> `GET /api/executions/{id}/items` every 1 second. Works fine for v1.
> Upgrade later.

------------------------------------------------------------------------

## 11. Frontend Architecture (React + React Flow)

### Component tree

    App
    ├── Sidebar              ← list of node types (from GET /api/nodes), draggable
    ├── Canvas (React Flow)  ← the drag-drop surface
    │   ├── CustomNode       ← renders per-type icon + status color
    │   └── CustomEdge       ← animated line when running
    ├── ConfigPanel          ← right side; form from node schema (react-jsonschema-form)
    ├── TopBar               ← Save, Run, activate/deactivate
    ├── ExecutionsPanel      ← past runs list
    └── ExecutionDetailView  ← per-node I/O inspector

### State management (Zustand stores)

  -----------------------------------------------------------------------
  Store                               Holds
  ----------------------------------- -----------------------------------
  `workflowStore`                     Current nodes + edges (synced with
                                      backend JSON)

  `executionStore`                    Active execution status, node
                                      statuses (from WebSocket)

  `credentialsStore`                  Credential metadata for dropdowns

  `uiStore`                           Selected node, panel open/closed,
                                      sidebar search
  -----------------------------------------------------------------------

### Sync strategy with backend

-   On every canvas change → **debounced (500ms)**
    `PUT /api/workflows/{id}`
-   "Run" → `POST .../run` → get `execution_id` → open WebSocket → live
    colors
-   Convert React Flow state ↔ workflow JSON with two small mapper
    functions:

``` js
// reactFlowNodes[] <-> workflow.nodes[]
// reactFlowEdges[] <-> workflow.connections[]   (map sourceHandle/targetHandle)
```

**Tip:** store React Flow nodes with a `data: { status }` field. The
WebSocket handler updates `node.data.status` → React Flow re-renders the
color automatically. Cheap and effective.

------------------------------------------------------------------------

## 12. Credentials & Security

### 12.1 Storing credentials (non-negotiable)

-   Encrypt with **Fernet (AES-128-CBC)** via the `cryptography` library
-   Encryption key lives in **environment variable**
    (`CREDENTIALS_ENCRYPTION_KEY`), not in the code or DB
-   Never return decrypted data in any API response
-   Frontend only ever sees: `{ id, name, type }` (metadata)

``` python
from cryptography.fernet import Fernet
key = os.environ["CREDENTIALS_ENCRYPTION_KEY"]   # generate: Fernet.generate_key()
cipher = Fernet(key.encode())
stored = cipher.encrypt(json.dumps(credential_data).encode())
```

### 12.2 Authentication (JWT)

  -----------------------------------------------------------------------
  Piece                               Implementation
  ----------------------------------- -----------------------------------
  Password storage                    `passlib` + bcrypt (never
                                      plaintext, never SHA-256)

  Access token                        JWT, 15--60 min expiry

  Refresh token                       Long-lived, stored in DB (or
                                      httpOnly cookie)

  Security headers                    FastAPI + `CORSMiddleware` with
                                      your frontend origin only

  Rate limiting                       On `/api/auth/login`
                                      (slowloris/brute-force protection)
  -----------------------------------------------------------------------

### 12.3 Webhook security

-   Webhook URLs are **unguessable UUIDs**
    (`/api/webhooks/7f3e9a1c-...`)
-   Optionally support a shared secret header check (phase 3)
-   Log every webhook hit; never log bodies with secrets

### 12.4 Node sandboxing (when you allow custom user code)

When users can write JavaScript/Python inside nodes, **assume they will
run malicious code**:

-   Execute in a separate OS-level process with memory/time limits
-   No network except via your controlled HTTP client
-   Isolated filesystem (temp dir only)
-   (n8n uses `isolated-vm`; Python equivalents: `subprocess` +
    `resource` limits, or `nsjail`/Docker-in-Docker later)

------------------------------------------------------------------------

## 13. Background Jobs & Workers (Celery/Redis)

### Topology

    FastAPI (API) ──► Redis ──► Celery Worker(s) ──► engine.execute_workflow()

### What gets queued

  Job type             Queue       Notes
  -------------------- ----------- ----------------------------------
  `execute_workflow`   `default`   Manual runs + webhook + schedule
  `schedule_check`     `beat`      Celery beat fires cron triggers

### Key settings

-   `task_acks_late = True` --- don't lose jobs if worker crashes
    mid-run
-   `worker_prefetch_multiplier = 1` --- one long job shouldn't hog the
    worker
-   Result backend = Redis, but **write authoritative execution data to
    PostgreSQL**
-   Scheduled workflows: use Celery Beat's `crontab` schedules, or a
    simpler alternative: a `cron` job that queries a `schedules` table
    every minute (easier to debug, and users' schedules are stored in
    the DB anyway --- this is what I'd recommend for v1)

### The "only one running at a time" rule

Before a scheduled run starts, worker checks:
`SELECT 1 FROM executions WHERE workflow_id=:id AND status='running'`.
If exists → skip (like n8n's default).

------------------------------------------------------------------------

## 14. Testing Strategy

You cannot ship a workflow engine without tests. Prioritize in this
order:

### Level 1 --- Unit tests (engine, most important)

``` python
# test_engine.py
def test_simple_chain():
    wf = make_workflow([manual_trigger, http_request])
    result = execute_workflow(wf, trigger_data=[{}])
    assert result.status == "success"
    assert result.results["http_request"][0]["url"] == "https://..."

def test_branching():
    wf = make_workflow([manual_trigger, if_node, slack, db])
    result = execute_workflow(wf, [{"subject": "urgent!"}])
    assert "slack" in result.results and "db" not in result.results
```

### Level 2 --- Node tests

Each node gets tests with `respx` (mock httpx): success, error, timeout,
empty input.

### Level 3 --- API tests

FastAPI's `TestClient`: auth flow, CRUD, run → execution appears,
webhook triggers execution.

### Level 4 --- E2E (later)

Playwright: load page → drag two nodes → connect → run → see green. One
happy path is enough for v1.

**Golden rule:** your test suite is a **workflow spec** --- every
behavior you want the product to have, write the test first.

------------------------------------------------------------------------

## 15. Deployment (Docker → Production)

### 15.1 Docker Compose (local dev + first server)

``` yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: automation
    volumes: [ "db-data:/var/lib/postgresql/data" ]

  redis:
    image: redis:7

  api:
    build: ./backend
    environment:
      DATABASE_URL: postgresql://app:${POSTGRES_PASSWORD}@db/automation
      REDIS_URL: redis://redis:6379/0
      CREDENTIALS_ENCRYPTION_KEY: ${CREDENTIALS_ENCRYPTION_KEY}
      JWT_SECRET: ${JWT_SECRET}
    ports: [ "8000:8000" ]
    depends_on: [ db, redis ]

  worker:
    build: ./backend
    command: celery -A app.worker worker --loglevel=info
    environment:
      DATABASE_URL: postgresql://app:${POSTGRES_PASSWORD}@db/automation
      REDIS_URL: redis://redis:6379/0
      CREDENTIALS_ENCRYPTION_KEY: ${CREDENTIALS_ENCRYPTION_KEY}
    depends_on: [ db, redis ]

  frontend:
    build: ./frontend
    ports: [ "3000:80" ]
    depends_on: [ api ]

volumes:
  db-data:
```

### 15.2 Production checklist

1.  Frontend built as static files, served by nginx (or Vercel/Netlify
    --- even easier)
2.  `CREDENTIALS_ENCRYPTION_KEY` + `JWT_SECRET` in a secrets manager (or
    env vars --- at minimum, never in git)
3.  Managed PostgreSQL (AWS RDS or Neon/Supabase) once real users arrive
4.  Redis on the same VM is fine at first; add auth + TLS later
5.  Backups: Postgres daily dumps + encrypted credential recovery plan
    (losing the encryption key = losing all credentials --- **back it
    up**)
6.  HTTPS everywhere (Caddy/nginx Let's Encrypt, or platform-managed)
7.  `healthcheck` endpoints for db, api, worker in compose

------------------------------------------------------------------------

## 16. Performance & Scaling

### Realistic scaling ladder

  -----------------------------------------------------------------------
  Stage                   Setup                   Handles
  ----------------------- ----------------------- -----------------------
  1                       1 VM + Docker Compose   Personal use, small
                                                  team

  2                       1 VM + managed          Dozens of active
                          Postgres/Redis          workflows

  3                       API + N workers (same   Hundreds --- just add
                          image, more replicas)   worker containers

  4                       Dedicated webhook       Thousands
                          handler + CDN, DB read  
                          replicas                
  -----------------------------------------------------------------------

### Performance rules of thumb

-   **Never** put heavy logic in the API server --- only queue jobs.
    Workers scale, API doesn't have to
-   Webhook trigger path must be \< 50ms overhead: `INSERT execution` →
    push to Redis → 202 response
-   Keep execution data prunable:
    `DELETE FROM execution_items WHERE started_at < now() - interval '30 days'`
    (scheduled task)
-   Index `executions(workflow_id, started_at desc)` and
    `execution_items(execution_id)` --- that's 90% of your read patterns
-   Node HTTP calls: use one shared `httpx.AsyncClient` with connection
    pooling, set sane timeouts (5--10s default)

------------------------------------------------------------------------

## 17. Full Folder Structure

    my-automation-tool/
    ├── docker-compose.yml
    ├── README.md
    ├── .env.example                  # all secrets documented, no real values
    ├── backend/
    │   ├── requirements.txt
    │   ├── alembic/                  # DB migrations
    │   ├── app/
    │   │   ├── main.py               # FastAPI app, routes mounting, CORS
    │   │   ├── config.py             # env config (pydantic-settings)
    │   │   ├── api/                  # route modules
    │   │   │   ├── auth.py
    │   │   │   ├── workflows.py
    │   │   │   ├── executions.py
    │   │   │   ├── credentials.py
    │   │   │   ├── nodes.py          # GET /nodes, GET /nodes/{type}/schema
    │   │   │   ├── webhooks.py
    │   │   │   └── ws.py             # WebSocket endpoint
    │   │   ├── engine/
    │   │   │   ├── graph.py          # build_graph, topological_sort, validate
    │   │   │   ├── executor.py       # execute_workflow (section 8.5)
    │   │   │   ├── expressions.py    # {{ }} evaluator
    │   │   │   ├── node_base.py      # BaseNode, NodeContext, NodeResult
    │   │   │   └── errors.py         # NodeExecutionError etc.
    │   │   ├── nodes/                # one file per node = one plugin
    │   │   │   ├── __init__.py       # NODE_REGISTRY = {type: class}
    │   │   │   ├── manual_trigger.py
    │   │   │   ├── http_request.py
    │   │   │   ├── webhook.py
    │   │   │   ├── if_condition.py
    │   │   │   ├── set_data.py
    │   │   │   ├── send_email.py
    │   │   │   ├── database_query.py
    │   │   │   └── schedule.py
    │   │   ├── models/               # SQLAlchemy models (section 5)
    │   │   │   ├── user.py
    │   │   │   ├── workflow.py
    │   │   │   ├── execution.py
    │   │   │   ├── credential.py
    │   │   │   └── webhook.py
    │   │   ├── schemas/              # Pydantic API schemas (workflow JSON contract)
    │   │   ├── security/
    │   │   │   ├── jwt.py
    │   │   │   └── crypto.py         # Fernet credential encryption
    │   │   └── worker.py             # Celery app + tasks
    │   └── tests/
    │       ├── test_engine.py        # THE most important file
    │       ├── test_nodes/
    │       └── test_api/
    ├── frontend/
    │   ├── package.json
    │   ├── vite.config.js
    │   ├── index.html
    │   └── src/
    │       ├── App.jsx
    │       ├── api.js                # tiny fetch wrapper (no heavy libs needed)
    │       ├── websocket.js
    │       ├── stores/
    │       │   ├── workflowStore.js
    │       │   ├── executionStore.js
    │       │   └── uiStore.js
    │       ├── components/
    │       │   ├── Sidebar.jsx
    │       │   ├── Canvas.jsx
    │       │   ├── ConfigPanel.jsx
    │       │   ├── ExecutionsPanel.jsx
    │       │   └── ExecutionDetail.jsx
    │       ├── mappers.js            # React Flow <-> workflow JSON
    │       └── styles.css
    └── docs/                         # your documentation lives here

------------------------------------------------------------------------

## 18. Milestone Roadmap & Timeline

  -----------------------------------------------------------------------
  Milestone               What "done" looks like  Time (solo, part-time)
  ----------------------- ----------------------- -----------------------
  **M1: Engine v1**       `execute_workflow` runs 2--3 weeks
                          a hardcoded JSON        
                          workflow: manual        
                          trigger → HTTP →        
                          set-data. Tests green   

  **M2: 5--8 nodes**      The node list from      1--2 weeks
                          section 7, all          
                          unit-tested             

  **M3: API**             Auth, workflow CRUD,    1--2 weeks
                          run/executions          
                          endpoints. TestClient   
                          tests pass              

  **M4: Canvas v1**       React Flow canvas: drag 2--3 weeks
                          nodes, connect, save,   
                          run, see result         

  **M5: Live status**     WebSocket (or 1s        1 week
                          polling): nodes light   
                          up green/red during     
                          runs                    

  **M6: Credentials**     Encrypted storage,      1 week
                          credential picker in    
                          config panel            

  **M7: Triggers**        Webhooks + schedule     1--2 weeks
                          triggers, "activate"    
                          toggle                  

  **M8: History UI**      Executions list +       1--2 weeks
                          per-node I/O            
                          inspector + retry       

  **M9: Hardening**       Error handling UX,      2 weeks
                          timeouts, pruning,      
                          docker-compose, deploy  

  **M10: AI               See section 20          ongoing
  differentiator**                                
  -----------------------------------------------------------------------

**Realistic totals:** first usable internal version in \~3--4 months;
"n8n-basics" parity in 6--9 months.

------------------------------------------------------------------------

## 19. Common Pitfalls (Read Before Coding)

1.  **Building UI first.** Build the engine, test with hardcoded JSON,
    then touch React Flow.
2.  **No tests on the engine.** A workflow engine without tests is a
    time bomb. Write `test_engine.py` first.
3.  **Blocking the API server.** Long workflows must never run inside
    the request handler --- always queue to a worker.
4.  **Storing credentials as plaintext.** Non-negotiable: encrypt +
    never log.
5.  **Losing the encryption key.** Back it up; losing it = users lose
    every credential.
6.  **Cyclic workflows.** Users will create loops. Validate DAG before
    running (topological sort fails → friendly error).
7.  **Not skipping duplicate scheduled runs.** Two workers fire the same
    cron → duplicate emails. Use the running-check from section 13.
8.  **Saving workflows on every drag.** Debounce `PUT /workflows` or
    you'll hammer the API with 50 requests per second.
9.  **Huge execution logs.** Store node outputs in `execution_items`,
    prune after 30 days, paginate the history UI.
10. **Regex-free expression parser.** Start with `{{ key }}` simple
    string replacement; add nested access later.
11. **Ignoring webhook body size limits.** Enforce a max request size
    (e.g. 5 MB) or users will stream GBs into your webhooks.
12. **Copying n8n code directly.** Read it for ideas (it's fair-code,
    not MIT --- check LICENSE). Build your own implementation.

------------------------------------------------------------------------

## 20. Your AI Differentiator (Why You Can Beat n8n)

This is where you genuinely win. n8n is an automation tool with AI
bolted on. You can build **AI-native** from day one:

  -----------------------------------------------------------------------
  Idea                    Difficulty              Impact
  ----------------------- ----------------------- -----------------------
  **AI Agent node** as a  Medium                  High
  first-class citizen                             
  (LLM decides tools to                           
  call)                                           

  **RAG pipeline node**   Medium                  High
  --- vector DB +                                 
  embeddings + LLM in one                         
  node                                            

  **Natural language →    High                    **Huge (this is the
  workflow generator**:                           killer feature)**
  user types "send me a                           
  Slack message when my                           
  boss emails me" → AI                            
  produces the workflow                           
  JSON → user sees it on                          
  the canvas                                      

  **AI error assistant**  Low                     Medium
  --- when a node fails,                          
  AI explains the error                           
  and suggests the fix                            

  **AI data mapper** ---  Medium                  High
  "map my CSV columns to                          
  the Slack fields"                               
  without clicking 20                             
  dropdowns                                       
  -----------------------------------------------------------------------

**Recommended sequence:** ship the basic product (M1--M9), then add the
**AI error assistant** (easiest win), then the **NL → workflow
generator** (biggest differentiator). n8n is actively working on these
too --- speed matters.

------------------------------------------------------------------------

## 21. Glossary

  -----------------------------------------------------------------------
  Term                                Definition
  ----------------------------------- -----------------------------------
  **API**                             Application Programming Interface
                                      --- how programs talk to each other

  **CRUD**                            Create, Read, Update, Delete ---
                                      the four basic data operations

  **DAG**                             Directed Acyclic Graph --- workflow
                                      structure with no loops

  **Webhook**                         An HTTP URL that triggers something
                                      when called

  **Cron**                            Time-based scheduler syntax
                                      (`*/5 * * * *` = every 5 minutes)

  **JWT**                             JSON Web Token --- a signed token
                                      proving who you are

  **JSONB**                           PostgreSQL column type storing JSON
                                      with indexing

  **ORM**                             Object-Relational Mapper --- write
                                      DB queries in Python instead of SQL

  **WebSocket**                       A persistent two-way connection for
                                      live updates

  **Debounce**                        Delay an action until the user
                                      stops changing input

  **Topological sort**                Ordering graph nodes so every node
                                      comes after its dependencies

  **Fair-code**                       License model: source visible,
                                      usage restricted in certain
                                      commercial cases

  **Single source of truth**          The one place the canonical version
                                      of data lives (here: the DB)
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 22. Resources & References

### From this repo (n8n --- your reference implementation)

-   `README.md` --- product overview
-   `AGENTS.md` --- architecture summary & engineering patterns
-   `PROJECT_DOCUMENTATION.md` --- beginner-oriented full project
    documentation
-   `packages/workflow/src/` --- workflow/node type definitions (the
    "contract")
-   `packages/core/src/` --- the execution engine (the "brain")
-   `packages/nodes-base/nodes/` --- 308 node implementations (inspect,
    don't copy)
-   `packages/frontend/editor-ui/` --- the Vue editor (your React Flow
    equivalent)
-   `packages/@n8n/api-types/` --- how n8n shares types between FE/BE
    (do the same with Pydantic + TS)

### External

  ------------------------------------------------------------------------------------
  Resource                                         Why
  ------------------------------------------------ -----------------------------------
  <https://reactflow.dev>                          The canvas library --- its docs are
                                                   excellent

  <https://fastapi.tiangolo.com>                   Your API framework docs

  <https://docs.celeryq.dev>                       Job queue docs

  <https://www.postgresql.org/docs>                Database

  <https://react-jsonschema-form.readthedocs.io>   Auto-generate config forms from
                                                   node schemas

  <https://dagster.io> / <https://temporal.io>     Study how serious workflow
                                                   orchestrators model state
                                                   (inspiration)

  n8n docs: <https://docs.n8n.io>                  Understand the UX your users expect
  ------------------------------------------------------------------------------------

------------------------------------------------------------------------

*End of documentation. Start with **M1 (the engine)** --- everything
else hangs off it. You have the reference implementation in this folder;
read it for patterns, build your own from scratch.*

------------------------------------------------------------------------

**By Gaurav**

------------------------------------------------------------------------

# 23. Developer Implementation Specification

This section converts the architecture above into implementation rules
that developers can follow without having to infer core behavior.

## 23.1 Source of truth

The system has four authoritative contracts:

1.  **Workflow contract** --- canonical workflow JSON/schema.
2.  **Node contract** --- canonical node metadata, parameter schema,
    inputs and outputs.
3.  **Execution contract** --- canonical execution states, events,
    retries and persistence rules.
4.  **API contract** --- canonical HTTP/WebSocket request and response
    schemas.

Frontend, backend, workers and node packages must not create
incompatible versions of these contracts.

### Rule

Any contract change must include:

-   schema change
-   migration/versioning strategy when required
-   backend implementation
-   frontend compatibility
-   tests
-   documentation

------------------------------------------------------------------------

# 24. Workflow Specification

## 24.1 Workflow identity

Every workflow must have:

-   `id`
-   `name`
-   `version`
-   `status`
-   `nodes`
-   `connections`
-   `settings`
-   `created_at`
-   `updated_at`

Recommended status values:

``` text
draft
active
inactive
archived
```

A workflow execution must always reference the exact workflow version
that was executed.

## 24.2 Workflow versioning

Never modify the historical definition of a workflow execution.

When a workflow is changed:

``` text
Workflow
   ↓
Version 1
Version 2
Version 3
```

An execution stores:

``` text
workflow_id
workflow_version_id
execution_id
```

This guarantees that an old execution can always be inspected against
the exact workflow definition that produced it.

## 24.3 Validation before activation

A workflow cannot be activated unless:

-   all node IDs are unique
-   all node types exist
-   every required node parameter is valid
-   every connection references an existing node
-   connection handles are valid
-   at least one trigger exists
-   there are no unsupported cycles
-   credentials referenced by nodes exist
-   webhook paths are valid
-   schedule configuration is valid
-   workflow size limits are respected

Validation errors must identify:

``` text
node
field
error code
human-readable message
```

Example:

``` json
{
  "code": "INVALID_PARAMETER",
  "node_id": "n4",
  "field": "url",
  "message": "URL is required."
}
```

------------------------------------------------------------------------

# 25. Execution State Machine

The execution engine must use explicit states.

``` text
                 ┌──────────┐
                 │  queued  │
                 └────┬─────┘
                      ↓
                 ┌──────────┐
                 │ running  │
                 └────┬─────┘
          ┌───────────┼────────────┐
          ↓           ↓            ↓
      waiting      retrying     cancelled
          │           │
          ↓           ↓
       running ←──────┘
          │
     ┌────┼─────────────┐
     ↓    ↓             ↓
 success failed       timeout
```

## 25.1 Required execution states

``` text
queued
running
waiting
retrying
success
failed
cancelled
timeout
```

## 25.2 State transition rules

Invalid transitions must be rejected.

Examples:

``` text
queued → running       valid
running → waiting      valid
waiting → running      valid
running → retrying     valid
retrying → running     valid
running → success      valid
running → failed       valid
running → cancelled    valid
running → timeout      valid
success → running      invalid
failed → running       invalid
```

## 25.3 Durable execution state

The database is the authoritative source for execution state.

Redis/Celery is the transport and job-processing layer.

Do not rely on Redis result state as the permanent execution record.

------------------------------------------------------------------------

# 26. Node SDK Specification

Every node must implement a stable interface.

Conceptually:

``` python
class BaseNode:
    node_type: str
    display_name: str
    version: str
    description: str

    def parameters_schema(self):
        ...

    def credentials(self):
        ...

    def input_types(self):
        ...

    def output_types(self):
        ...

    async def run(self, ctx, params, input_items):
        ...
```

## 26.1 Node metadata

Each node should expose:

``` text
type
version
display_name
description
category
icon
documentation_url
parameters_schema
credential_types
input_handles
output_handles
supports_binary
supports_batch
```

## 26.2 Node categories

Start with:

``` text
Triggers
Actions
Logic
Transform
AI
Database
Communication
Utilities
```

## 26.3 Node execution rules

A node must:

-   validate parameters
-   never leak credentials
-   respect cancellation
-   respect timeout
-   use the shared HTTP client where applicable
-   return structured output
-   raise typed errors
-   emit useful execution metadata
-   avoid writing directly to unrelated database tables

------------------------------------------------------------------------

# 27. Standard Node Result Contract

Every node returns a predictable result.

``` json
{
  "items": [
    {
      "json": {
        "key": "value"
      }
    }
  ],
  "metadata": {
    "duration_ms": 120
  }
}
```

Errors use a structured form:

``` json
{
  "code": "HTTP_TIMEOUT",
  "message": "The external API did not respond within 10 seconds.",
  "retryable": true,
  "details": {}
}
```

The UI must show the safe human-readable message while sensitive details
remain server-side.

------------------------------------------------------------------------

# 28. Data Model Expansion

For a company/team product, evolve the initial user-owned model into:

``` text
Organization
 ├── Users
 ├── Roles
 ├── Workspaces
 │    ├── Workflows
 │    ├── Credentials
 │    ├── Executions
 │    └── Webhooks
 └── Audit Logs
```

Recommended additional entities:

``` text
organizations
organization_members
roles
workspaces
workflow_versions
workflow_tags
execution_events
execution_steps
audit_logs
api_keys
refresh_tokens
schedules
webhook_deliveries
node_packages
```

## 28.1 Tenant isolation

Every organization-owned resource must be scoped by
organization/workspace.

Never trust a client-supplied resource ID alone.

Authorization must verify:

``` text
authenticated user
        ↓
organization membership
        ↓
workspace access
        ↓
resource ownership/access
```

------------------------------------------------------------------------

# 29. Credentials and Secrets

Credentials are never returned to the browser after creation.

The backend must:

1.  validate credential data
2.  encrypt it
3.  store ciphertext
4.  return metadata only
5.  decrypt only immediately before required node execution
6.  redact secrets from logs/errors/events

## 29.1 Production key management

The initial environment-variable encryption key is acceptable for
development.

Production should support:

-   secret manager/KMS
-   key rotation
-   key versioning
-   backup/recovery
-   controlled administrative access

Changing an encryption key must not silently make existing credentials
unusable.

------------------------------------------------------------------------

# 30. Expression System

Start simple, but define the expression system as a controlled
evaluator.

Supported initial expressions:

``` text
{{ $json.field }}
{{ $node.node_id.json.field }}
{{ $workflow.id }}
{{ $execution.id }}
{{ $now }}
```

## Security rules

Expressions must never become arbitrary Python execution.

Do not implement:

``` text
eval()
exec()
arbitrary imports
shell commands
filesystem access
```

The expression evaluator must use an allowlisted parser/runtime.

------------------------------------------------------------------------

# 31. HTTP and SSRF Protection

Because the platform can make outbound HTTP requests, the HTTP node is a
security boundary.

Production HTTP nodes must consider:

-   private IP blocking
-   localhost blocking
-   cloud metadata endpoint blocking
-   DNS rebinding protection
-   redirect validation
-   maximum response size
-   request timeout
-   connection timeout
-   maximum redirects
-   allowed protocols
-   rate limiting
-   response body limits

Never assume that an arbitrary URL is safe because the user entered it.

------------------------------------------------------------------------

# 32. Webhook Specification

Each active webhook must have:

``` text
workflow_id
workflow_version_id
path
method
status
created_at
```

Webhook processing:

``` text
HTTP request
   ↓
validate path
   ↓
validate method
   ↓
validate payload size
   ↓
authenticate if configured
   ↓
create execution
   ↓
queue execution
   ↓
return 202
```

The webhook endpoint should not execute a long workflow synchronously.

## Webhook reliability

Store a delivery record containing:

``` text
delivery_id
workflow_id
received_at
status
response_code
execution_id
```

Support idempotency keys where duplicate delivery is a concern.

------------------------------------------------------------------------

# 33. Scheduler Specification

Schedules must be persisted in PostgreSQL.

A scheduler creates execution jobs; it does not execute workflows
itself.

``` text
Schedule
   ↓
Scheduler
   ↓
Execution record
   ↓
Queue
   ↓
Worker
   ↓
Execution engine
```

The system must prevent duplicate scheduled executions when multiple
scheduler instances are running.

Use a database lock, unique execution key, or equivalent distributed
coordination mechanism.

------------------------------------------------------------------------

# 34. Queue and Worker Reliability

Workers must be stateless.

A worker may:

-   receive execution ID
-   load workflow version
-   load required credentials
-   execute
-   persist progress
-   emit events

A worker must not assume that another worker's in-memory state exists.

## 34.1 Worker failure

If a worker crashes:

``` text
job remains recoverable
        ↓
execution remains identifiable
        ↓
system detects stale execution
        ↓
execution is retried/recovered according to policy
```

Execution steps should be persisted frequently enough that a crash does
not require restarting unnecessarily expensive work when the product
supports resumability.

------------------------------------------------------------------------

# 35. Retry and Idempotency

Retries can duplicate external side effects.

Examples:

``` text
Send Email
Create Payment
Create Ticket
Send Slack Message
POST external API
```

Therefore every retry-capable node should document whether it is:

``` text
idempotent
conditionally idempotent
non-idempotent
```

Where possible, support idempotency keys.

Retry policy:

``` json
{
  "enabled": true,
  "max_attempts": 3,
  "backoff": "exponential",
  "initial_delay_seconds": 2,
  "max_delay_seconds": 60
}
```

Do not retry permanent errors such as invalid credentials or invalid
parameters.

------------------------------------------------------------------------

# 36. Cancellation and Timeouts

Cancellation must be cooperative.

The execution context should expose:

``` python
ctx.is_cancelled()
```

Long-running nodes must periodically check cancellation.

Every external operation must have a timeout.

Recommended layers:

``` text
HTTP timeout
Node timeout
Execution timeout
Worker/job timeout
```

The shortest applicable timeout wins.

------------------------------------------------------------------------

# 37. Execution Events

Create a structured event model.

Example:

``` json
{
  "event": "node.completed",
  "execution_id": "exec_123",
  "node_id": "n2",
  "status": "success",
  "timestamp": "2026-08-10T12:00:00Z"
}
```

Suggested events:

``` text
execution.queued
execution.started
node.started
node.completed
node.failed
node.retrying
execution.waiting
execution.completed
execution.failed
execution.cancelled
execution.timeout
```

The WebSocket layer consumes these events.

------------------------------------------------------------------------

# 38. API Implementation Rules

Every protected API request must derive the user identity from the
authentication token.

Never accept:

``` text
user_id
organization_id
owner_id
```

from the request body as the sole authorization mechanism.

## API error format

Use one consistent shape:

``` json
{
  "error": {
    "code": "WORKFLOW_NOT_FOUND",
    "message": "Workflow was not found.",
    "request_id": "req_123"
  }
}
```

Common status codes:

``` text
400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found
409 Conflict
422 Validation Error
429 Rate Limited
500 Internal Server Error
503 Service Unavailable
```

------------------------------------------------------------------------

# 39. API Idempotency

Creation and execution endpoints that may be retried should support
idempotency where appropriate.

Example:

``` http
Idempotency-Key: 8f1c...
```

The server stores the result associated with the key for a defined
period.

This is especially important for:

``` text
workflow activation
workflow execution
webhook delivery
credential creation
```

------------------------------------------------------------------------

# 40. Frontend Implementation Rules

The frontend must never contain business-critical execution logic.

Frontend responsibilities:

``` text
render
edit workflow
validate basic UI state
send API requests
display execution state
display safe errors
```

Backend responsibilities:

``` text
authorization
workflow validation
credential resolution
execution
security
persistence
scheduling
```

The backend remains authoritative.

------------------------------------------------------------------------

# 41. Autosave and Conflict Handling

Autosave must be debounced.

Use:

``` text
edit
 ↓
500ms debounce
 ↓
save
```

For collaborative/team use, add optimistic concurrency:

``` text
workflow_version = 12
```

If the client attempts to update version 12 but the server is already at
version 13:

``` text
409 CONFLICT
```

The UI must not silently overwrite newer work.

------------------------------------------------------------------------

# 42. Execution History and Data Retention

Execution data can become the largest storage consumer.

Implement:

``` text
retention policy
pruning job
pagination
optional output truncation
binary cleanup
```

Configurable example:

``` text
execution retention: 30 days
maximum output size: configurable
maximum execution payload: configurable
```

Never delete audit records merely because execution output is pruned.

------------------------------------------------------------------------

# 43. Observability

Production deployment must provide:

### Logs

Structured JSON logs containing:

``` text
timestamp
level
service
request_id
execution_id
workflow_id
node_id
message
```

Never log:

``` text
passwords
API keys
OAuth tokens
authorization headers
credential payloads
```

### Metrics

At minimum:

``` text
workflow executions
successful executions
failed executions
execution duration
queue depth
worker utilization
API latency
API error rate
webhook rate
node failure rate
database latency
```

### Health checks

Provide:

``` text
/api/health
/api/ready
```

Readiness should verify required dependencies.

------------------------------------------------------------------------

# 44. Audit Logging

Record security-sensitive actions:

``` text
login
logout
credential created
credential deleted
workflow created
workflow updated
workflow activated
workflow deleted
API key created
member added
member removed
role changed
```

Audit logs should contain:

``` text
actor
organization
action
resource
timestamp
request_id
metadata
```

Do not store secrets in audit metadata.

------------------------------------------------------------------------

# 45. File and Binary Data

The initial JSON-only engine can be extended with binary data.

Do not store large binary payloads directly inside PostgreSQL JSONB.

Use:

``` text
PostgreSQL → metadata
Object storage → binary content
```

Examples:

``` text
S3
MinIO
compatible object storage
```

Nodes should reference binary objects rather than copying large files
between every database row.

------------------------------------------------------------------------

# 46. AI Architecture

AI is a first-class capability but must remain compatible with the
normal node engine.

Example:

``` text
AI Agent
   ↓
Tool registry
   ├── HTTP
   ├── Database
   ├── Search
   ├── Email
   └── Custom tools
```

AI nodes must have:

-   provider configuration
-   model configuration
-   token limits
-   timeout
-   retry policy
-   tool permissions
-   structured output support
-   prompt/version tracking
-   usage metrics

## 46.1 Natural language workflow generation

Recommended flow:

``` text
User request
     ↓
AI planner
     ↓
structured workflow JSON
     ↓
schema validation
     ↓
security validation
     ↓
preview on canvas
     ↓
user approval
     ↓
save workflow
```

Never allow the AI to directly deploy arbitrary generated workflows
without validation and user/system authorization.

------------------------------------------------------------------------

# 47. Plugin and Custom Node Security

Third-party nodes are executable code.

Therefore:

``` text
trusted internal nodes
        ≠
untrusted third-party nodes
```

For future marketplace/community nodes, define:

-   package signing
-   version pinning
-   dependency scanning
-   permission model
-   review process
-   sandboxing policy
-   install/uninstall lifecycle
-   compatibility checks

Do not allow arbitrary packages to silently gain unrestricted access to
secrets or the host system.

------------------------------------------------------------------------

# 48. Production Deployment Architecture

Recommended first production topology:

``` text
                    Internet
                       │
                    HTTPS
                       │
                Reverse Proxy
                       │
             ┌─────────┴─────────┐
             ↓                   ↓
          Frontend             API
                                 │
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
                 Redis       PostgreSQL    Object Store
                    │
                    ↓
              Worker Pool
           ┌────────┼────────┐
           ↓        ↓        ↓
        Worker   Worker   Worker
```

The first production deployment does not require Kubernetes.

Start with Docker Compose or an equivalent simple deployment model, then
introduce orchestration when operational requirements justify it.

------------------------------------------------------------------------

# 49. Backup and Disaster Recovery

Minimum production backup policy:

``` text
PostgreSQL:
  automated daily backup
  point-in-time recovery where available

Redis:
  treated as recoverable queue state, not primary business storage

Object storage:
  versioning/backups where required

Secrets:
  encryption-key recovery procedure
```

Test restoration periodically.

A backup that has never been restored is not a verified backup.

------------------------------------------------------------------------

# 50. Security Checklist

Before production:

-   [ ] HTTPS enabled
-   [ ] secure password hashing
-   [ ] access-token expiration
-   [ ] refresh-token rotation
-   [ ] rate limiting
-   [ ] CORS restricted
-   [ ] CSRF strategy where applicable
-   [ ] credential encryption
-   [ ] secret redaction
-   [ ] tenant isolation
-   [ ] RBAC
-   [ ] webhook protection
-   [ ] SSRF protection
-   [ ] request size limits
-   [ ] file size limits
-   [ ] SQL injection protection through parameterized queries/ORM
-   [ ] XSS protection
-   [ ] dependency scanning
-   [ ] container image scanning
-   [ ] audit logging
-   [ ] backup verification
-   [ ] encryption-key recovery procedure
-   [ ] security incident procedure

------------------------------------------------------------------------

# 51. Testing and Acceptance Specification

Every feature must have acceptance criteria.

## 51.1 Engine acceptance

The engine passes when:

-   simple chains execute correctly
-   branching executes the correct branch
-   skipped nodes are recorded
-   node errors stop downstream execution according to policy
-   retries work
-   timeouts work
-   cancellation works
-   executions persist state
-   worker restart does not corrupt execution state

## 51.2 Workflow acceptance

The system must:

-   create workflow
-   edit workflow
-   save workflow
-   validate workflow
-   version workflow
-   activate workflow
-   deactivate workflow
-   execute exact saved version

## 51.3 Node acceptance

Every node must test:

``` text
valid input
invalid input
empty input
external success
external failure
timeout
credential failure
retry behavior
large input where applicable
```

## 51.4 API acceptance

Test:

``` text
authentication
authorization
CRUD
validation
pagination
rate limits
conflict handling
idempotency
error responses
```

## 51.5 E2E acceptance

Minimum complete flow:

``` text
Register
  ↓
Login
  ↓
Create workflow
  ↓
Drag trigger
  ↓
Add HTTP node
  ↓
Connect nodes
  ↓
Save
  ↓
Run
  ↓
Worker executes
  ↓
Execution history appears
  ↓
Node results visible
```

------------------------------------------------------------------------

# 52. Definition of Done

A feature is not complete when the code works locally.

It is complete only when:

-   implementation exists
-   API/schema is defined
-   validation exists
-   error behavior is defined
-   tests exist
-   security implications are addressed
-   logs/metrics are appropriate
-   documentation is updated
-   migration exists if needed
-   frontend behavior is implemented
-   CI passes

------------------------------------------------------------------------

# 53. Development Order

The team should follow this order unless a technical dependency requires
otherwise.

## Phase 1 --- Execution core

Build:

``` text
workflow schema
graph builder
graph validation
topological execution
node registry
execution persistence
```

## Phase 2 --- Initial nodes

Build:

``` text
manual trigger
HTTP request
IF
Set/Edit Data
Webhook
Email
Database
Schedule
```

## Phase 3 --- Backend

Build:

``` text
authentication
workflow CRUD
workflow versioning
execution API
node schema API
credential API
webhook API
```

## Phase 4 --- Frontend

Build:

``` text
canvas
node sidebar
node configuration
save/autosave
run
execution status
history
```

## Phase 5 --- Reliability

Build:

``` text
queue
workers
retry
timeout
cancellation
scheduler
webhook reliability
```

## Phase 6 --- Security

Build:

``` text
RBAC
tenant isolation
credential encryption
secret redaction
SSRF protection
rate limits
audit logs
```

## Phase 7 --- Production

Build:

``` text
Docker
HTTPS
backups
monitoring
metrics
logging
health checks
deployment
```

## Phase 8 --- AI

Build:

``` text
AI node
AI agent
tool calling
AI error assistant
natural-language workflow generation
```

------------------------------------------------------------------------

# 54. Team Responsibilities

A practical team split:

### Backend / Engine

Own:

``` text
workflow schema
execution engine
nodes
API
database
workers
credentials
triggers
```

### Frontend

Own:

``` text
React
React Flow
canvas
node configuration
workflow editing
execution UI
history
```

### DevOps

Own:

``` text
Docker
CI/CD
deployment
PostgreSQL
Redis
monitoring
backups
secrets
```

### QA

Own:

``` text
unit tests
integration tests
E2E
load tests
security tests
workflow acceptance tests
```

### AI Engineering

Own:

``` text
AI nodes
agent runtime
tool registry
workflow generation
AI error assistant
evaluation
```

------------------------------------------------------------------------

# 55. CI/CD Requirements

Every pull request should run:

``` text
format check
lint
type check
unit tests
integration tests
API tests
frontend tests
security/dependency checks
build
```

Main branch should only accept changes when required checks pass.

Production deployment should be versioned and rollback-capable.

------------------------------------------------------------------------

# 56. Performance Targets

Initial targets are engineering goals, not guarantees.

### API

``` text
normal CRUD: < 300ms target
health endpoint: < 100ms target
```

### Webhook

``` text
acceptance overhead: low enough to return quickly
long workflow execution: asynchronous
```

### Execution

Execution time depends on external services and node behavior.

Measure:

``` text
queue wait
execution startup
per-node duration
external API duration
database duration
total duration
```

Do not optimize based only on total execution time.

------------------------------------------------------------------------

# 57. Resource Limits

Every execution should have configurable limits.

Examples:

``` text
maximum execution duration
maximum nodes per workflow
maximum payload size
maximum output size
maximum recursion/sub-workflow depth
maximum concurrent executions
maximum retry attempts
maximum webhook body size
```

Limits prevent accidental or malicious workloads from exhausting
infrastructure.

------------------------------------------------------------------------

# 58. Multi-Worker Concurrency

The system must support:

``` text
1 API
1 worker
```

and later:

``` text
1 API
N workers
```

Workers must not rely on local filesystem state for workflow execution.

Shared state belongs in:

``` text
PostgreSQL
Redis
Object storage
```

where appropriate.

------------------------------------------------------------------------

# 59. Version Compatibility

Node definitions and workflow definitions must be version-aware.

Example:

``` json
{
  "type": "http_request",
  "version": 2
}
```

If a node changes behavior:

``` text
HTTP Request v1
HTTP Request v2
```

must remain interpretable for existing workflows where required.

Never silently change the meaning of an existing node parameter in a way
that changes old workflow behavior.

------------------------------------------------------------------------

# 60. Migration Strategy

Database changes must use migrations.

Never manually modify production schemas.

Every migration must be:

``` text
forward-compatible where possible
tested
reviewed
rollback-considered
```

Workflow schema migrations should be separate from database migrations
because workflow JSON is application data.

------------------------------------------------------------------------

# 61. Documentation Requirements for Every Node

Each node should document:

``` text
Name
Purpose
Inputs
Outputs
Parameters
Credentials
Examples
Errors
Retry behavior
Timeout behavior
Security considerations
Version
```

Example:

``` text
HTTP Request
-------------------------
Input:
  JSON items

Parameters:
  method
  url
  headers
  body

Output:
  status
  headers
  body

Retry:
  timeout/network errors only

Security:
  SSRF protections required
```

------------------------------------------------------------------------

# 62. MVP Scope

Do not attempt full parity with n8n in the first release.

### V1 must support

``` text
Manual workflows
Webhook workflows
Scheduled workflows
HTTP requests
IF conditions
Data transformation
Email
Database
Credentials
Execution history
Retries
Errors
Basic AI node
Docker deployment
Authentication
Basic RBAC
```

### Later releases

``` text
Loops
Sub-workflows
Human approval
Advanced expressions
Binary data
Object storage
Community nodes
Marketplace
Advanced AI agents
Enterprise SSO
Advanced audit
Horizontal scaling
Collaboration
```

------------------------------------------------------------------------

# 63. Final Product Architecture

The completed platform should conceptually look like:

``` text
                         USERS
                           │
                           ▼
                  ┌─────────────────┐
                  │  React Canvas   │
                  │  React Flow     │
                  └────────┬────────┘
                           │
                     REST/WebSocket
                           │
                           ▼
                  ┌─────────────────┐
                  │    FastAPI      │
                  │ API + Auth      │
                  └───────┬─────────┘
                          │
             ┌────────────┼────────────┐
             │            │            │
             ▼            ▼            ▼
        PostgreSQL      Redis      Object Store
             │            │
             │            ▼
             │       Celery Queue
             │            │
             │            ▼
             │      ┌─────────────┐
             └─────►│   Workers   │
                    └──────┬──────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Execution Engine│
                  └────────┬────────┘
                           │
                     Node Registry
                           │
        ┌──────────┬───────┼────────┬──────────┐
        ▼          ▼       ▼        ▼          ▼
      HTTP       Email     DB       AI       Logic
        │          │       │        │          │
        └──────────┴───────┴────────┴──────────┘
```

------------------------------------------------------------------------

# 64. Final Engineering Principles

1.  **Build the execution engine before the visual editor.**
2.  **Keep the workflow JSON contract stable and versioned.**
3.  **Keep workers stateless.**
4.  **Keep PostgreSQL authoritative for durable state.**
5.  **Never store plaintext credentials.**
6.  **Never execute arbitrary user code in the API process.**
7.  **Never trust client-supplied ownership IDs.**
8.  **Never allow AI-generated workflows to bypass validation.**
9.  **Never silently change the behavior of an existing node version.**
10. **Never ship execution-engine changes without tests.**
11. **Never make long-running workflows block API requests.**
12. **Never expose secrets through execution logs.**
13. **Treat webhooks and HTTP requests as security-sensitive surfaces.**
14. **Design for one worker first, but keep workers stateless so they
    can scale horizontally.**
15. **Build the MVP independently; add parity features only after the
    core engine is reliable.**

------------------------------------------------------------------------

# 65. Project Completion Criteria

The platform can be considered a successful internal replacement
candidate when the company can:

``` text
1. Create a workflow
2. Save and version it
3. Configure credentials securely
4. Activate it
5. Trigger it manually
6. Trigger it through webhook
7. Trigger it on schedule
8. Execute multiple nodes
9. Pass data between nodes
10. Branch conditionally
11. Retry recoverable failures
12. Cancel executions
13. Inspect execution history
14. Inspect node input/output safely
15. Add new nodes without changing the core engine
16. Run multiple workers
17. Recover from worker/API restart
18. Deploy with Docker
19. Back up and restore production data
20. Monitor failures and performance
21. Generate workflows with AI after validation
```

If these requirements are satisfied, the company has an independently
implemented workflow automation platform rather than a runtime
dependency on n8n.

------------------------------------------------------------------------

# 66. Important Positioning

This project should be described internally as:

> **An independent, n8n-inspired workflow automation platform built from
> scratch using our own implementation, architecture decisions, node
> SDK, execution engine, APIs and UI.**

n8n may be studied as a reference for concepts and product expectations,
but the implementation should remain independently developed.

The purpose is **not to clone n8n line-for-line**.

The purpose is to build a maintainable automation platform that provides
the capabilities the company actually needs and can evolve
independently.

------------------------------------------------------------------------

# 67. Final Developer Instruction

Before writing production code, every developer must read this document
completely.

The implementation sequence is:

``` text
Read specification
      ↓
Agree on contracts
      ↓
Create repository
      ↓
Create database migrations
      ↓
Implement workflow schema
      ↓
Implement node SDK
      ↓
Implement engine
      ↓
Write engine tests
      ↓
Implement initial nodes
      ↓
Implement API
      ↓
Implement worker/queue
      ↓
Implement frontend
      ↓
Implement security
      ↓
Implement triggers
      ↓
Implement execution history
      ↓
Implement observability
      ↓
Deploy staging
      ↓
Run E2E + load + security tests
      ↓
Production deployment
```

**Do not start by building the canvas.**

The execution engine is the core product.

If the engine is correct, the UI, API, triggers and integrations can be
built around it. If the engine is unreliable, a beautiful canvas will
not produce a reliable automation platform.

------------------------------------------------------------------------

# 68. Final Status

This document now serves two purposes:

1.  **Architecture Blueprint** --- explains what the platform is and how
    the major components fit together.
2.  **Developer Implementation Specification** --- defines the
    additional contracts, reliability rules, security requirements,
    testing requirements, production requirements and acceptance
    criteria needed to build it professionally.

The original M1--M10 roadmap remains the recommended development
sequence.

**Start with M1: the execution engine.**

Build it, test it heavily, and only then expand the platform.



By Gaurav
