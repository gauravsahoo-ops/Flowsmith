# Flowsmith Connector Platform & SDK Specifications

**Version:** 1.0.0 Enterprise  
**Framework:** Connector Framework v2 SDK (`app.connectors`)  
**Catalog Coverage:** 86 Registered Enterprise Connectors (69 Native + 17 OpenAPI) + Dynamic OpenAPI 3.0 Importer

---

## 1. Connector Framework v2 Architecture

Flowsmith connectors are built on an object-oriented, contract-driven SDK that guarantees consistent behavior across all integrations:

```
┌────────────────────────────────────────────────────────┐
│               ConnectorDefinitionV1                    │
├────────────────────────────────────────────────────────┤
│ • metadata: id, name, category, icon, description      │
│ • authentication: type (OAuth2, ApiKey, Basic, Custom) │
│ • operations: search, get, create, update, delete, ... │
│ • triggers: webhook, polling, event_stream             │
│ • dynamic_schemas: custom object / field introspection │
│ • health_check: ping / token verification endpoint     │
└────────────────────────────────────────────────────────┘
```

All connectors register with the global **`ConnectorRegistry`** (`app.connectors.registry`), ensuring dynamic discovery by the UI marketplace, the DAG compiler, and the Model Context Protocol (MCP) server.

---

## 2. Standardized Operation & Trigger Contracts

Every connector adheres to uniform interface contracts:

### Standard Operations
- **`search`**: Query records matching filter criteria with pagination (`limit`, `offset`, `cursor`).
- **`get`**: Retrieve a single record by unique primary key or ID.
- **`create`**: Insert a new entity with schema-validated input payload.
- **`update`**: Patch or replace an existing entity.
- **`delete`**: Remove an entity by ID with confirmation flag.
- **`execute`**: Execute specialized actions (e.g. `send_message` in Slack, `generate_completion` in OpenAI).

### Standard Triggers
- **`webhook_trigger`**: Instant real-time event ingestion via incoming HTTPS POST with HMAC verification.
- **`polling_trigger`**: Periodic polling against external APIs with deduplication tracking via state cursors (`last_updated_at` / `last_id`).

---

## 3. First-Class Connector Catalog (86 Registered Connectors)

Flowsmith includes 86 registered enterprise connectors organized across 8 enterprise categories, governed by an authoritative 5-tier certification state machine:

### Authoritative Certification State Machine
$$\text{STATIC\_VALIDATED} \longrightarrow \text{MOCK\_VALIDATED} \longrightarrow \text{CONTRACT\_VALIDATED} \longrightarrow \text{LIVE\_API\_VALIDATED} \longrightarrow \text{PRODUCTION\_CERTIFIED}$$

- **Live API Validated (1)**: Universal HTTP verified against authenticated sandbox endpoints.
- **Contract Validated (12)**: Protocol and schema contract suites (`salesforce`, `github`, `slack`, `stripe`, `sendgrid`, `jira`, `hubspot`, `postgres`, `snowflake`, `openai`, `anthropic`, `gemini`).
- **Mock Validated (73)**: Full operation dispatch, error mapping, and mock schema validation.
- **Promotion Gate**: Enforces 12 negative validation rules (schema hash drift detection, 90-day evidence expiration, automated write cleanup verification).

| Category | Supported Integrations |
| :--- | :--- |
| **CRM & Sales** | Salesforce, Microsoft Dynamics 365, HubSpot, Pipedrive, Zoho CRM, Zendesk Sell |
| **Database & Cache** | PostgreSQL, MySQL, Redis, MongoDB, Snowflake, BigQuery, Supabase |
| **Communication** | Slack, Microsoft Teams, Discord, Twilio, SendGrid, Resend, WhatsApp Business |
| **Developer & DevOps** | GitHub, GitLab, Bitbucket, Jira, PagerDuty, Linear, Docker, AWS S3 |
| **AI & Vector** | OpenAI (GPT-4o), Anthropic (Claude 3.5), Ollama (Local Air-Gapped), Azure OpenAI, Groq, Cohere, Pinecone |
| **Finance & Billing** | Stripe, QuickBooks, Xero, PayPal, Chargebee |
| **Productivity & Docs** | Google Drive, Google Sheets, Gmail, Notion, Airtable, Asana, Trello |
| **Core Utilities** | HTTP Request (SSRF-guarded), Code (Python/JS), Data Tables, Approval, Wait, Filter, Transform |

---

## 4. Authentication Protocols & Credential Lifecycle

### Supported Auth Types

1. **OAuth 2.0 with PKCE & Token Refresh**:
   - Supports Authorization Code grant with Proof Key for Code Exchange (PKCE).
   - Automated background refresh token rotation before token expiration.
2. **Zero-Config Single-Click Reconnect**:
   - Solves modern browser popup blockers by pre-opening the OAuth consent popup on direct user click, then fetching the authorization URL asynchronously.
3. **API Key & Bearer Token**:
   - Header, query parameter, or basic auth injection with automatic encryption at rest.
4. **Custom Header / Mutual TLS (mTLS)**:
   - Client certificates and custom signature headers for high-security enterprise APIs.

---

## 5. Dynamic Schema Discovery

For systems with dynamic or user-customized schemas (e.g. Salesforce Custom Objects, HubSpot Custom Properties, PostgreSQL Relational Tables):

- The connector exposes an introspection method: `GET /api/connectors/{key}/schema?object={name}`.
- The UI dynamically queries the external service and updates the node inspector with exact live field types, picklist values, and required indicators.
- Eliminates manual typing of custom field IDs (e.g. `Custom_Lead_Score__c`).

---

## 6. OpenAPI 3.0 & Swagger Importer

When an enterprise uses proprietary in-house APIs or third-party services not in the catalog:

1. **Import Modal (`OpenApiImportModal.jsx`)**:
   - Operator pastes a raw OpenAPI/Swagger JSON/YAML spec or supplies a live URL.
2. **Parser (`app.connectors.openapi_importer`)**:
   - Inspects `paths`, `methods`, `parameters`, `requestBody`, and `securitySchemes`.
   - Generates a fully compliant `ConnectorDefinitionV1` in seconds.
3. **Instant Availability**:
   - Newly imported connectors appear immediately in the canvas node palette and can be used like any native connector.

---

## 7. Connector Health Checks & Diagnostics

Operators can test connectivity to any third-party system before activating workflows:

- **Endpoint**: `POST /api/connectors/{key}/health-check`
- **Actions Performed**:
  - Tests DNS resolution and network route.
  - Decrypts and tests vault credentials against a lightweight ping endpoint.
  - Measures round-trip API latency.
  - Returns clear diagnostic messages on failure (e.g. `Invalid OAuth Scope`, `Token Expired`, `IP Not Whitelisted`).
