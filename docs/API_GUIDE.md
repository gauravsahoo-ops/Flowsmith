# Flowsmith — REST & WebSocket API Specification

> **Base URL**: `/api`  
> **Versioning**: Not versioned in the URL (all routes live under `/api`); breaking changes are announced in `CHANGELOG.md`  
> **Protocol**: HTTPS / WSS  
> **Data Format**: JSON (`application/json`)  
> **Authentication**: `Bearer <JWT_TOKEN>` or `X-API-Key: <opaque service-account key>`  

---

## 1. Overview & Response Conventions

Successful responses use a standard envelope (`{"data": ..., "meta": ...}`, built by `ok()` in `backend/app/api/common.py`); errors use FastAPI's standard `{"detail": "..."}` shape.

### 1.1 Success Response Envelope
```json
{
  "data": {
    "id": "wf_8f7e6d5c",
    "name": "Lead Synchronization Pipeline",
    "active": true
  }
}
```

Paginated list responses carry pagination metadata:

```json
{
  "data": [ { "id": "wf_8f7e6d5c", "name": "Lead Synchronization Pipeline" } ],
  "meta": { "page": 1, "pageSize": 50, "total": 12 }
}
```

### 1.2 Error Response
Errors are returned as `{"detail": "..."}` with the appropriate HTTP status (`400`, `401`, `403`, `404`, `409`, `422`, `429`, …). Validation errors use FastAPI's standard `loc`/`msg`/`type` item list:

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

---

## 2. Authentication & Authorization

All private endpoints require an `Authorization` header containing a valid user JWT or an enterprise API key:

```bash
# User Session Bearer Token:
Authorization: Bearer <your-user-jwt>

# Automation / Service Account API Key (minted via /api/apikeys, shown once):
X-API-Key: Kx3f9Qz7Tm2pLw8vRb1nHs6Jd4Gy0Uc5
```

---

## 3. Endpoints Reference

### 3.1 Authentication (`/api/auth`)

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Register a new user account | No |
| `POST` | `/api/auth/login` | Authenticate; may return an MFA challenge instead of a JWT | No |
| `GET` | `/api/auth/mfa` | Get TOTP enrollment status | **Yes** |
| `POST` | `/api/auth/mfa/setup` | Generate a TOTP secret and `otpauth://` URI | **Yes** |
| `POST` | `/api/auth/mfa/enable` | Verify a code and enable MFA; returns recovery codes | **Yes** |
| `POST` | `/api/auth/mfa/verify` | Exchange an MFA challenge + code for a JWT | No |
| `POST` | `/api/auth/mfa/enroll/start` | Start forced MFA enrollment with a policy token | No |
| `POST` | `/api/auth/mfa/enroll/complete` | Verify enrollment and issue the login JWT | No |
| `POST` | `/api/auth/mfa/disable` | Disable MFA after password + code verification | **Yes** |
| `GET` | `/api/auth/webauthn` | List configured passkeys | **Yes** |
| `POST` | `/api/auth/webauthn/register/options` | Start passkey registration | **Yes** |
| `POST` | `/api/auth/webauthn/register/complete` | Verify and store a passkey | No |
| `POST` | `/api/auth/webauthn/authenticate/complete` | Exchange a passkey assertion for a JWT | No |
| `POST` | `/api/auth/webauthn/conditional/options` | Discoverable-credential options for passkey autofill | No |
| `POST` | `/api/auth/webauthn/conditional/complete` | Passwordless passkey sign-in | No |
| `DELETE` | `/api/auth/webauthn/{id}` | Remove a passkey | **Yes** |
| `GET` | `/api/auth/me` | Fetch authenticated user profile & organization | **Yes** |
| `POST` | `/api/auth/logout` | Revoke current token and terminate session | **Yes** |
| `POST` | `/api/auth/password-reset`| Request or complete password reset | No |
| `GET` | `/api/auth/sso/saml/metadata` | Native SAML 2.0 SP metadata | No |
| `GET` | `/api/auth/sso/saml/login` | Start SAML SP-initiated login | No |
| `POST` | `/api/auth/sso/saml/acs` | SAML assertion consumer service | No |
| `POST` | `/api/auth/sso/saml/logout` | Bearer-authenticated SAML SP logout | **Yes** |
| `GET/POST` | `/api/auth/sso/saml/slo` | SAML IdP-initiated Single Logout | No |
| `GET/POST` | `/scim/v2/Users` | SCIM 2.0 user list/create | SCIM bearer token |
| `GET/POST` | `/scim/v2/Groups` | SCIM 2.0 workspace-backed group list/create | SCIM bearer token |

`/api/auth/login` accepts an email address or an LDAP username. Local passwords
are checked first; when `LDAP_ENABLED=true`, a failed local check falls back to
a directory bind. Organization founders can set `require_mfa` on
`PATCH /api/organizations/{id}`; affected password/LDAP users receive an
`mfa_enrollment_required` response before a normal JWT is issued. See [LDAP](LDAP.md), [MFA](MFA.md), [WebAuthn](WEBAUTHN.md), [SAML](SAML.md),
and [SCIM](SCIM.md) for enterprise identity configuration and current
limitations.

---

### 3.2 Workflows (`/api/workflows`)

#### `GET /api/workflows`
Returns all workflows accessible to the authenticated user.
* **Query Parameters**:
  * `active` (boolean, optional): Filter by active status (`true` / `false`).
  * `search` (string, optional): Keyword search against name and description.
* **Response**: `200 OK` with list of workflow summaries.

#### `POST /api/workflows`
Creates a new workflow graph.
* **Request Body**:
  ```json
  {
    "name": "Customer Onboarding Sync",
    "description": "Sync new signups to Salesforce & Dynamics CRM",
    "data": {
      "nodes": [
        {
          "id": "trigger_1",
          "type": "webhook",
          "parameters": { "path": "customer-signup" }
        }
      ],
      "edges": []
    }
  }
  ```
* **Response**: `201 Created` with workflow object.

#### `GET /api/workflows/{id}`
Fetches full workflow graph definition including nodes, edges, and triggers.

#### `PUT /api/workflows/{id}`
Updates an existing workflow graph and creates a new version snapshot.

#### `DELETE /api/workflows/{id}`
Deletes the workflow and cancels any pending scheduled executions.

#### `POST /api/workflows/{id}/duplicate`
Creates an exact clone of the specified workflow.

#### `POST /api/workflows/{id}/run`
Triggers an immediate asynchronous execution of the workflow.
* **Request Body**:
  ```json
  {
    "data": {
      "email": "alex.morgan@contoso.com",
      "company": "Contoso Ltd"
    }
  }
  ```
* **Response**: `202 Accepted` returning `{"data": {"execution_id": "exec_4f3e2d1c"}}`.

---

### 3.3 Executions (`/api/executions`)

#### `GET /api/executions`
Lists execution runs with pagination and status filters.
* **Query Parameters**:
  * `workflow_id` (string, optional): Filter runs by workflow.
  * `status` (string, optional): `queued`, `running`, `success`, `failed`, `cancelled`.
  * `limit` (int, default: 50): Number of records per page.

#### `GET /api/executions/{id}`
Retrieves detailed status, start/finish timestamps, total duration, and output payload.

#### `POST /api/executions/{id}/cancel`
Signals a running execution to abort immediately.

#### `GET /api/executions/{id}/trace`
Returns fine-grained step-by-step telemetry, detailing input/output data and execution duration for every individual node.

---

### 3.4 Node Catalog & Testing (`/api/nodes`)

#### `GET /api/nodes`
Returns metadata and JSON schemas for all available node types in the palette.

#### `POST /api/nodes/{type}/test`
Executes an isolated single step ("Test Step") without running the full workflow DAG.
* **Request Body**:
  ```json
  {
    "parameters": {
      "resource": "Contact",
      "operation": "get",
      "record_id": "00000000-0000-0000-0000-000000000000"
    },
    "credentials": {
      "dynamics_crm": "cred_dynamics_prod"
    },
    "input_data": {}
  }
  ```
* **Response**: `200 OK` with node execution output payload or error details.

---

### 3.5 Credential Vault (`/api/credentials`)

#### `GET /api/credentials`
Lists all stored credentials with secrets securely redacted (`••••••••••••`).

#### `POST /api/credentials`
Creates and encrypts a new credential entry.
* **Request Body**:
  ```json
  {
    "name": "Salesforce Production",
    "type": "salesforce",
    "data": {
      "instance_url": "https://company.my.salesforce.com",
      "client_id": "3MVG9...",
      "client_secret": "91823...",
      "refresh_token": "5Aep8..."
    }
  }
  ```

#### `POST /api/credentials/{id}/test`
Executes a live health probe against the target service (e.g. `WhoAmI` call) to verify credential validity.

---

### 3.6 Embedded Relational Data Tables (`/api/data-tables`)

#### `GET /api/data-tables`
Lists custom relational tables defined in the current organization.

#### `POST /api/data-tables`
Creates a new custom table schema.

#### `GET /api/data-tables/{id}/rows`
Queries table records with optional SQL-like filtering, sorting, and pagination.

#### `POST /api/data-tables/{id}/rows`
Inserts or upserts a row into the specified data table.

#### `POST /api/data-tables/{id}/bulk-import`
Streams bulk CSV or JSON data directly into the table.

---

### 3.7 AI, Cognitive Memory & Autonomous Agents (`/api/ai`)

#### `POST /api/ai/chat`
Live interactive chat with Flowsmith's autonomous AI Agent runtime. Supports cloud LLMs (OpenAI, Anthropic, Gemini, Groq, DeepSeek), local Ollama, and the zero-dependency sovereign **Builtin Local Intelligence Engine**:
```json
{
  "message": "Calculate (450 * 12) + 80 and record result as fiscal_q1 in entity memory",
  "session_id": "cust_sess_9821",
  "memory_type": "complete",
  "allow_builtin": true,
  "tools": ["calculator", "current_time"]
}
```

#### `GET /api/ai/memory/{session_id}`
Retrieves session metadata, tier status, active message count, entity keys, and scratchpad tags.

#### `DELETE /api/ai/memory/{session_id}`
Clears active in-memory state and deletes persisted `.runtime/ai_memory/{session_id}.json` archive.

#### `GET /api/ai/memory/{session_id}/search?q={query}&top_k=5`
Executes semantic and lexical recall across all 6 memory tiers (vector and zero-embedding BM25 n-gram search).

#### `POST /api/ai/memory/{session_id}/entities`
Upserts structured entity facts or triggers rule-based fact extraction from raw conversational text.

#### `GET /api/ai/memory/{session_id}/entities`
Fetches all structured entities and attributes stored for the specified conversation session.

#### `POST /api/ai/memory/{session_id}/notes`
Creates or updates a tagged scratchpad note or task checkpoint in the session workspace.

#### `GET /api/ai/memory/{session_id}/notes?tag={optional_tag}`
Lists all scratchpad notes, optionally filtered by tag.

#### `POST /api/ai/intent`
Extracts structured intent, workflow objectives, parameters, and clarification questions from natural language requirements.

#### `POST /api/ai/compile`
Compiles an intermediate representation (`WorkflowIR`) into a visual Flowsmith DAG document.

#### `POST /api/ai/validate-pipeline`
Executes the comprehensive 6-stage validation pipeline across structural DAG, connector schemas, expressions, credentials, runtime bounds, and SSRF security.

#### `POST /api/ai/simulate`
Simulates workflow execution with synthetic data propagation, expression linting, and step-by-step latency estimation without side effects.

#### `POST /api/ai/repair-workflow`
Diagnoses execution trace errors and generates a validated before/after diff proposal for human review.

#### `POST /api/ai/modify-workflow`
Applies surgical natural language modifications to an existing workflow graph and returns an atomic DAG diff.

---

### 3.8 Human-in-the-Loop Approvals (`/api/approvals`)

#### `GET /api/approvals`
Lists pending approval requests assigned to the authenticated user.

#### `POST /api/approvals/{id}/respond`
Approves or rejects a suspended workflow execution:
```json
{
  "decision": "approved",
  "comment": "Expense request authorized by Finance Director",
  "data": {
    "approved_amount": 5400
  }
}
```

---

### 3.9 Real-Time Execution Streaming (WebSocket)

#### `WS /api/ws/executions/{id}`
Subscribes to live execution status updates. As nodes execute on distributed workers, status events are streamed to the client in real-time:

```json
{
  "event": "node_started",
  "execution_id": "exec_4f3e2d1c",
  "node_id": "dynamics_crm_1",
  "timestamp": 1727260800000
}
```

---

### 3.10 System Health & Readiness

#### `GET /api/health`
Liveness probe. Returns `200 OK` if the FastAPI gateway process is active.

#### `GET /api/readyz`
Readiness probe. Checks PostgreSQL database connection and (when configured) Redis connectivity; returns `503` while not ready:
```json
{
  "data": {
    "status": "ready",
    "checks": {
      "postgres": "ok",
      "redis": "ok"
    },
    "uptime_s": 9420
  }
}
```

---

### 3.11 Provider Webhooks (`/api/provider-webhooks`)

#### `POST /api/provider-webhooks/register`
Creates a provider-side webhook for an active GitHub, GitLab, Stripe, Shopify, or
Typeform trigger node. Requires workflow edit access and a provider credential:

```json
{
  "workflow_id": "wf_123",
  "node_id": "trigger",
  "credential_id": "cred_123",
  "config": {"repository": "acme/repo", "events": ["push"]}
}
```

`signing_secret` is optional for providers that allow a generated secret
(GitHub, GitLab, and Typeform) and required for Shopify. GitLab uses the
credential's configured `host` and authenticates with `X-Gitlab-Token`. Stripe
returns the endpoint secret from its API. Slack Events API registration is not
automated.

#### `GET /api/provider-webhooks?workflow_id=...`
Lists registrations for a workflow. Secrets are never returned.

#### `DELETE /api/provider-webhooks/{id}`
Removes the provider-side webhook and the local record. `?force=true` removes
the local record even if the provider API is unavailable.

---

### 3.12 Connector Packs (`/api/connector-packs`)

#### `GET /api/connector-packs`
Lists installed connector packs. Authenticated users may read the list;
`source_url` is returned only to administrators.

#### `POST /api/connector-packs/install`
Admin-only. Installs a manifest containing an OpenAPI/Swagger spec and optional
workflow templates. Provide either `manifest` (JSON object) or `manifest_url`
(SSRF-safe HTTP fetch):

```json
{
  "manifest": {
    "name": "petstore",
    "display_name": "Petstore",
    "version": "1.0.0",
    "spec": "https://api.example.com/openapi.json",
    "templates": []
  }
}
```

The installed connector becomes available to API and worker processes; generated
sources are stored in PostgreSQL. Remote `manifest_url` installs require HTTPS,
an Ed25519 signature, and signed URL specs require `spec_sha256`. Upgrade and
uninstall are available at `POST /api/connector-packs/{key}/upgrade` and
`DELETE /api/connector-packs/{key}`. `POST /api/connector-packs/registry/preview`
verifies a signed registry index without installing it. Pack `requires`
dependencies are enforced, and API/worker reconcilers propagate changes across
replicas. See [`CONNECTOR_PACKS.md`](CONNECTOR_PACKS.md) for the manifest schema,
registry format, signing commands, trusted/revoked-key configuration, limits,
and security boundaries.
